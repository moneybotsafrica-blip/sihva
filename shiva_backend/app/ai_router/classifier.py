from typing import List, Optional, Literal
import re
import structlog

from app.clients.qdrant_client import QdrantClientInterface, SearchResult
from app.config import settings

logger = structlog.get_logger(__name__)

RouteDecision = Literal["code", "support"]


class AIRouter:
    """AI Router for classifying incoming support messages."""

    # Greeting patterns
    GREETING_PATTERNS = [
        "hi",
        "hello",
        "hey",
        "good morning",
        "good afternoon",
        "good evening",
        "greetings",
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
    ):
        self.qdrant_client = qdrant_client
        self.similarity_threshold = similarity_threshold or settings.qdrant_similarity_threshold

    async def classify(
        self,
        message: str,
        attachments: Optional[List[str]] = None,
    ) -> RouteDecision:
        """
        Classify an incoming message to determine routing destination.
        
        Decision order (exact):
        1. Greeting check → route to Support AI (for friendly interaction)
        2. Technical-signal check → route to Code/Server AI
        3. Knowledge-base check (Qdrant) → route to Support AI if confident match
        4. Fallback → route to staff queue
        
        Args:
            message: The customer's message content
            attachments: List of attachment filenames/IDs
            
        Returns:
            RouteDecision: "code", "support", or "staff"
        """
        attachments = attachments or []
        message_lower = message.lower()
        
        # Step 1: Greeting check
        if self._is_greeting(message_lower):
            logger.info(
                "Greeting detected, routing to Support AI",
                message_length=len(message),
            )
            return "support"
        
        # Step 2: Technical-signal check
        if self._has_technical_signal(message, attachments):
            logger.info(
                "Technical signal detected, routing to Code/Server AI",
                message_length=len(message),
                attachments_count=len(attachments),
            )
            return "code"

        # Step 2: Technical-signal check
        if self._has_technical_signal(message, attachments):
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
            if greeting in message_lower:
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
    )
    
    # For unit testing, we can use the synchronous check only
    if router._has_technical_signal(message, attachments or []):
        return "code"
    
    # If no technical signal and no Qdrant client, default to support (AI-first)
    if qdrant_client is None:
        return "support"
    
    # This would need to be called in async context for full functionality
    return "support"  # Placeholder for synchronous testing
