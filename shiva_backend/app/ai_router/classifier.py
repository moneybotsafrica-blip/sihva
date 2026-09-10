from typing import List, Optional, Literal, Union
import re
import structlog

from app.clients.qdrant_client import QdrantClientInterface, SearchResult
from app.config import settings
from app.ai_router.dynamic_router import DynamicRouter, RoutingContext, RoutingDecision
from app.db.models import RoutingRule
from sqlalchemy import select

logger = structlog.get_logger(__name__)

RouteDecision = Literal["code", "support", "staff"]


class AIRouter:
    """AI Router for classifying incoming support messages."""

    # Greeting patterns (use word boundaries to avoid false matches)
    GREETING_PATTERNS = [
        r"\bhi\b",
        r"\bhello\b",
        r"\bhey\b",
        r"\bgood morning\b",
        r"\bgood afternoon\b",
        r"\bgood evening\b",
        r"\bgreetings\b",
    ]

    # Technical signal patterns
    HTTP_ERROR_CODES = r"\b[45]\d{2}\b"  # 4xx and 5xx HTTP status codes
    STACK_TRACE_PATTERNS = [
        r"Traceback \(most recent call last\):",
        r"at\s+[a-zA-Z0-9_.]+\.[a-zA-Z0-9_]+\(",
        r"Error:\s+.*",
        r"Exception:\s+.*",
        r"TypeError|ValueError|KeyError|AttributeError|ImportError",
    ]
    TECHNICAL_TRIGGER_PHRASES = [
        "crash",
        "broken",
        "not working",
        "fails when",
        "exception",
        "bug",
        "doesn't work",
        "unable to",
        "cannot",
    ]

    # Attachment patterns indicating technical issues
    TECHNICAL_ATTACHMENT_TYPES = [
        ".log",
        ".txt",  # Could be logs
        ".png",  # Could be error screenshots
        ".jpg",
        ".jpeg",
        ".stacktrace",
    ]

    def __init__(
        self,
        qdrant_client: Optional[QdrantClientInterface] = None,
        similarity_threshold: Optional[float] = None,
        use_dynamic_routing: bool = False,
    ):
        self.qdrant_client = qdrant_client
        self.similarity_threshold = similarity_threshold or settings.qdrant_similarity_threshold
        self.use_dynamic_routing = use_dynamic_routing
        
        # Initialize dynamic router if enabled
        if use_dynamic_routing:
            self.dynamic_router = DynamicRouter(qdrant_client=qdrant_client)
        else:
            self.dynamic_router = None

    async def classify(
        self,
        message: str,
        attachments: Optional[List[str]] = None,
        session=None,
        customer_id: Optional[str] = None,
        customer_data: Optional[dict] = None,
        conversation_history: Optional[List] = None,
    ) -> Union[RouteDecision, RoutingDecision]:
        """
        Classify an incoming message to determine routing destination.
        
        If dynamic routing is enabled, uses database-driven rules.
        Otherwise, uses static pattern matching (legacy behavior).
        
        Decision order (static mode):
        1. Greeting check → route to Support AI (for friendly interaction)
        2. Technical-signal check → route to Code/Server AI
        3. Knowledge-base check (Qdrant) → route to Support AI if confident match
        4. Fallback → route to staff queue
        
        Args:
            message: The customer's message content
            attachments: List of attachment filenames/IDs
            session: Database session (required for dynamic routing)
            customer_id: Customer identifier (for dynamic routing)
            customer_data: Customer data (for dynamic routing)
            conversation_history: Conversation history (for dynamic routing)
            
        Returns:
            RouteDecision or RoutingDecision: Route destination and metadata
        """
        attachments = attachments or []
        
        # Use dynamic routing if enabled and session is provided
        if self.use_dynamic_routing and self.dynamic_router and session:
            logger.info("Using dynamic routing for classification")
            
            # Build routing context
            context = RoutingContext(
                message=message,
                customer_id=customer_id,
                customer_data=customer_data,
                attachments=attachments,
                conversation_history=conversation_history,
            )
            
            # Get KB similarity score if Qdrant client is available
            if self.qdrant_client:
                try:
                    query_vector = await self.qdrant_client.embed_text(message)
                    results = await self.qdrant_client.search(
                        query_vector=query_vector,
                        limit=1,
                        score_threshold=self.similarity_threshold,
                    )
                    if results:
                        context.kb_similarity_score = results[0].score
                except Exception as e:
                    logger.error("Failed to get KB similarity for dynamic routing", error=str(e))
            
            # Use dynamic router
            return await self.dynamic_router.route(context, session)
        
        # Fall back to static routing (legacy behavior)
        logger.info("Using static routing for classification")
        message_lower = message.lower()

        # Preserve the meaning of short follow-ups and explicit handoff requests.
        history_text = " ".join(
            item.get("content", "") if isinstance(item, dict) else getattr(item, "content", "")
            for item in (conversation_history or [])
        ).lower()
        staff_request_phrases = [
            "speak to staff", "talk to staff", "speak to human", "talk to human",
            "speak to an agent", "talk to an agent", "speak to a person",
            "talk to a person", "real person", "human agent", "live agent",
            "escalate this", "i want a ticket", "raise a ticket", "create a ticket",
        ]
        if any(phrase in message_lower for phrase in staff_request_phrases):
            logger.info("Explicit staff intent detected, routing to staff", message_length=len(message))
            return "staff"

        follow_up_phrases = [
            "i tried that", "i tried those", "already tried", "still failing",
            "still not working", "that did not work", "that didn't work",
            "same issue", "same error", "as before", "help me with this again",
        ]
        if history_text and any(phrase in message_lower for phrase in follow_up_phrases):
            logger.info("Conversation follow-up detected, routing to support", message_length=len(message))
            return "support"

        # For an elliptical follow-up, classify the complete conversation rather than
        # routing a phrase such as "I tried that" as an unrelated new request.
        routing_text = f"{history_text} {message_lower}" if history_text else message_lower
        
        # Step 1: Greeting check
        if self._is_greeting(message_lower) and not history_text:
            logger.info(
                "Greeting detected, routing to Support AI",
                message_length=len(message),
            )
            return "support"
        
        # Step 2: Technical-signal check
        if self._has_technical_signal(routing_text, attachments):
            logger.info(
                "Technical signal detected, routing to Code/Server AI",
                message_length=len(message),
                attachments_count=len(attachments),
            )
            return "code"

        # Step 3: Knowledge-base check (only if step 1 and 2 found nothing)
        if self.qdrant_client:
            try:
                has_kb_match = await self._check_knowledge_base(message)
                if has_kb_match:
                    logger.info(
                        "Knowledge base match found, routing to Support AI",
                        message_length=len(message),
                    )
                    return "support"
            except Exception as e:
                logger.error(
                    "Knowledge base check failed, falling back to staff",
                    error=str(e),
                )
                # Fall through to staff routing on error

        # Step 4: Fallback to staff queue
        logger.info(
            "No greeting, technical signal or KB match, routing to staff queue",
            message_length=len(message),
        )
        return "staff"

    def _has_technical_signal(self, message: str, attachments: List[str]) -> bool:
        """
        Check if message contains technical signals indicating code/server issues.
        
        Checks for:
        - HTTP error codes (500, 404, etc.)
        - Stack traces or exceptions
        - Technical trigger phrases
        - Technical attachment types (logs, error screenshots)
        """
        message_lower = message.lower()

        # Check for HTTP error codes
        if re.search(self.HTTP_ERROR_CODES, message):
            logger.debug("HTTP error code detected")
            return True

        # Check for stack traces
        for pattern in self.STACK_TRACE_PATTERNS:
            if re.search(pattern, message, re.IGNORECASE):
                logger.debug("Stack trace pattern detected")
                return True

        # Check for technical trigger phrases
        for phrase in self.TECHNICAL_TRIGGER_PHRASES:
            if phrase in message_lower:
                logger.debug(f"Technical trigger phrase detected: {phrase}")
                return True

        # Check for technical attachment types
        for attachment in attachments:
            attachment_lower = attachment.lower()
            for ext in self.TECHNICAL_ATTACHMENT_TYPES:
                if attachment_lower.endswith(ext):
                    logger.debug(f"Technical attachment detected: {attachment}")
                    return True

        return False

    def _is_greeting(self, message_lower: str) -> bool:
        """
        Check if message is a greeting.
        
        Returns True if message contains greeting patterns.
        """
        for greeting in self.GREETING_PATTERNS:
            if re.search(greeting, message_lower, re.IGNORECASE):
                logger.debug(f"Greeting pattern detected: {greeting}")
                return True
        return False

    async def _check_knowledge_base(self, message: str) -> bool:
        """
        Check if message has a confident match in the knowledge base.
        
        Returns True if similarity score meets threshold.
        """
        try:
            # Embed the message
            query_vector = await self.qdrant_client.embed_text(message)

            # Search for similar documents
            results = await self.qdrant_client.search(
                query_vector=query_vector,
                limit=3,
                score_threshold=self.similarity_threshold,
            )

            # Check if we have any confident matches
            has_match = len(results) > 0

            if has_match:
                logger.debug(
                    "Knowledge base match found",
                    match_count=len(results),
                    top_score=results[0].score if results else 0,
                )
            else:
                logger.debug(
                    "No confident knowledge base match",
                    top_score=results[0].score if results else 0,
                    threshold=self.similarity_threshold,
                )

            return has_match
        except Exception as e:
            logger.error(
                "Error checking knowledge base",
                error=str(e),
            )
            return False


# Pure function for easier unit testing
def classify_message(
    message: str,
    attachments: Optional[List[str]] = None,
    qdrant_client: Optional[QdrantClientInterface] = None,
    similarity_threshold: float = 0.75,
) -> RouteDecision:
    """
    Pure function version of classify for unit testing.
    This is a synchronous wrapper that doesn't require async.
    
    For the technical signal check (step 1), this works synchronously.
    For the knowledge base check (step 2), if qdrant_client is provided,
    this will need to be called in an async context.
    """
    router = AIRouter(
        qdrant_client=qdrant_client,
        similarity_threshold=similarity_threshold,
        use_dynamic_routing=False,  # Disable dynamic routing for pure function
    )
    
    # For unit testing, we can use the synchronous check only
    if router._has_technical_signal(message, attachments or []):
        return "code"
    
    # If no technical signal and no Qdrant client, default to staff (matching async behavior)
    if qdrant_client is None:
        return "staff"
    
    # This would need to be called in async context for full functionality
    return "support"  # Placeholder for synchronous testing


async def initialize_default_routing_rules(session):
    """
    Initialize default routing rules and destinations in the database.
    This converts the static patterns from the legacy classifier into dynamic rules.
    """
    from app.ai_router.routing_service import RoutingRuleService, RoutingDestinationService
    import uuid
    
    rule_service = RoutingRuleService(session)
    dest_service = RoutingDestinationService(session)
    
    # Create default destinations
    destinations_to_create = [
        {
            "name": "support_ai",
            "display_name": "Support AI",
            "destination_type": "ai",
            "description": "AI-powered customer support using knowledge base",
            "priority": 10,
        },
        {
            "name": "code_ai",
            "display_name": "Code/Server AI",
            "destination_type": "ai",
            "description": "AI for technical issues and code analysis",
            "priority": 20,
        },
        {
            "name": "staff",
            "display_name": "Human Staff",
            "destination_type": "human",
            "description": "Human support staff for complex issues",
            "priority": 30,
        },
    ]
    
    for dest_data in destinations_to_create:
        existing = await dest_service.get_destination_by_name(dest_data["name"])
        if not existing:
            await dest_service.create_destination(**dest_data)
            logger.info(f"Created default destination: {dest_data['name']}")
    
    # Create default routing rules (converted from static patterns)
    
    # Rule 1: Greeting detection → Support AI
    greeting_rule = {
        "name": "Greeting Detection",
        "description": "Routes greetings to Support AI for friendly interaction",
        "conditions": [
            {
                "type": "contains",
                "field": "message",
                "value": "hi",
                "case_sensitive": False,
            },
        ],
        "actions": [
            {
                "type": "route_to",
                "destination": "support_ai",
            },
        ],
        "priority": 1,  # Highest priority
        "weight": 1.0,
    }
    
    # Create additional greeting rules
    greeting_patterns = ["hello", "hey", "good morning", "good afternoon", "good evening", "greetings"]
    for pattern in greeting_patterns:
        rule_data = greeting_rule.copy()
        rule_data["name"] = f"Greeting: {pattern}"
        rule_data["conditions"] = [{"type": "contains", "field": "message", "value": pattern, "case_sensitive": False}]
        
        existing = await session.execute(
            select(RoutingRule).where(RoutingRule.name == rule_data["name"])
        )
        if not existing.scalar_one_or_none():
            await rule_service.create_rule(**rule_data)
    
    # Rule 2: HTTP error codes → Code AI
    http_error_rule = {
        "name": "HTTP Error Code Detection",
        "description": "Routes messages with HTTP error codes to Code AI",
        "conditions": [
            {
                "type": "regex",
                "field": "message",
                "value": r"\b[45]\d{2}\b",
                "case_sensitive": False,
            },
        ],
        "actions": [
            {
                "type": "route_to",
                "destination": "code_ai",
            },
        ],
        "priority": 10,
        "weight": 0.9,
    }
    
    existing = await session.execute(
        select(RoutingRule).where(RoutingRule.name == http_error_rule["name"])
    )
    if not existing.scalar_one_or_none():
        await rule_service.create_rule(**http_error_rule)
    
    # Rule 3: Stack traces → Code AI
    stack_trace_rule = {
        "name": "Stack Trace Detection",
        "description": "Routes messages with stack traces to Code AI",
        "conditions": [
            {
                "type": "regex",
                "field": "message",
                "value": r"Traceback \(most recent call last\):",
                "case_sensitive": False,
            },
        ],
        "actions": [
            {
                "type": "route_to",
                "destination": "code_ai",
            },
        ],
        "priority": 11,
        "weight": 0.9,
    }
    
    existing = await session.execute(
        select(RoutingRule).where(RoutingRule.name == stack_trace_rule["name"])
    )
    if not existing.scalar_one_or_none():
        await rule_service.create_rule(**stack_trace_rule)
    
    # Rule 4: Technical trigger phrases → Code AI
    technical_phrases = ["crash", "broken", "not working", "fails when", "exception", "bug", "doesn't work", "unable to", "cannot"]
    for phrase in technical_phrases:
        rule_data = {
            "name": f"Technical: {phrase}",
            "description": f"Routes messages containing '{phrase}' to Code AI",
            "conditions": [
                {
                    "type": "contains",
                    "field": "message",
                    "value": phrase,
                    "case_sensitive": False,
                },
            ],
            "actions": [
                {
                    "type": "route_to",
                    "destination": "code_ai",
                },
            ],
            "priority": 12,
            "weight": 0.8,
        }
        
        existing = await session.execute(
            select(RoutingRule).where(RoutingRule.name == rule_data["name"])
        )
        if not existing.scalar_one_or_none():
            await rule_service.create_rule(**rule_data)
    
    # Rule 5: Log attachments → Code AI
    log_attachment_rule = {
        "name": "Log Attachment Detection",
        "description": "Routes messages with log attachments to Code AI",
        "conditions": [
            {
                "type": "attachment_type",
                "value": ".log",
            },
        ],
        "actions": [
            {
                "type": "route_to",
                "destination": "code_ai",
            },
        ],
        "priority": 15,
        "weight": 0.85,
    }
    
    existing = await session.execute(
        select(RoutingRule).where(RoutingRule.name == log_attachment_rule["name"])
    )
    if not existing.scalar_one_or_none():
        await rule_service.create_rule(**log_attachment_rule)
    
    # Rule 6: KB similarity high → Support AI
    kb_similarity_rule = {
        "name": "High KB Similarity",
        "description": "Routes messages with high knowledge base similarity to Support AI",
        "conditions": [
            {
                "type": "kb_similarity",
                "value": 0.75,
            },
        ],
        "actions": [
            {
                "type": "route_to",
                "destination": "support_ai",
            },
        ],
        "priority": 20,
        "weight": 0.95,
    }
    
    existing = await session.execute(
        select(RoutingRule).where(RoutingRule.name == kb_similarity_rule["name"])
    )
    if not existing.scalar_one_or_none():
        await rule_service.create_rule(**kb_similarity_rule)
    
    logger.info("Default routing rules initialized successfully")
