from typing import Optional, List, Dict, Any, TYPE_CHECKING, AsyncIterator
from datetime import datetime
import structlog
from functools import lru_cache

from app.clients.qdrant_client import QdrantClientInterface, SearchResult
from app.clients.groq_client import GroqClientInterface, ChatMessage, LLMResponse
from app.ticket_center.service import TicketCenterService
from app.config import settings
from app.db.models import MessageSender
from app.support_ai.agents import AgentOrchestrator
from app.common.prompts import LANGUAGE_POLICY
from app.common.language_check import enforce_language_policy

if TYPE_CHECKING:
    from app.db.models import TicketMessage

logger = structlog.get_logger(__name__)


class SupportAIService:
    """Support AI service using RAG with Qdrant and Groq."""

    def __init__(
        self,
        qdrant_client: QdrantClientInterface,
        groq_client: GroqClientInterface,
        confidence_threshold: Optional[float] = None,
        complex_task_client: Optional[GroqClientInterface] = None,
    ):
        self.qdrant_client = qdrant_client
        self.groq_client = groq_client
        self.complex_task_client = complex_task_client  # Optional: Gemini for complex tasks
        self.confidence_threshold = confidence_threshold or settings.support_ai_confidence_threshold
        self.agent_orchestrator = AgentOrchestrator(groq_client)

    def _is_greeting_or_conversational(self, message: str) -> bool:
        """
        Check if the message is a greeting or conversational without a real issue.
        """
        greeting_patterns = [
            "hello", "hi", "hey", "good morning", "good afternoon", "good evening",
            "how are you", "how's it going", "what's up", "thanks", "thank you",
            "bye", "goodbye", "see you", "ok", "okay", "sure", "alright", "cool"
        ]
        
        message_lower = message.lower().strip()
        
        # Only treat a message as conversational when it contains no issue details.
        for pattern in greeting_patterns:
            if message_lower == pattern:
                return True
        
        # Check if message is very short (likely conversational)
        if len(message.split()) <= 2:
            return True
            
        return False

    async def _generate_conversation_title(
        self,
        message: str,
        conversation_history: List,
        client: Optional[GroqClientInterface] = None,
    ) -> Optional[str]:
        """
        Generate a short, factual conversation title based on the customer's issue.
        Returns None for greetings or conversational messages.
        """
        # Skip title generation for greetings
        if self._is_greeting_or_conversational(message):
            return None
        
        # Preserve an existing title when the caller carries it in the history.
        for history_item in conversation_history or []:
            if isinstance(history_item, dict):
                existing_title = history_item.get("analysis", {}).get("conversation_title")
                if existing_title:
                    return existing_title

        # Title the first meaningful customer message so follow-ups do not rename it.
        customer_messages = []
        for history_item in conversation_history or []:
            role = history_item.get("role") if isinstance(history_item, dict) else getattr(history_item, "role", None)
            content = history_item.get("content", "") if isinstance(history_item, dict) else getattr(history_item, "content", "")
            if role in (None, "user") and content and not self._is_greeting_or_conversational(content):
                customer_messages.append(content)
        issue_message = customer_messages[0] if customer_messages else message
        transcript = []
        for history_item in conversation_history or []:
            if isinstance(history_item, dict):
                role = history_item.get("role", "unknown")
                content = history_item.get("content", "")
            else:
                role = getattr(history_item, "role", None)
                if role is None and hasattr(history_item, "sender"):
                    role = str(history_item.sender).split(".")[-1].lower()
                content = getattr(history_item, "content", "")
            if content:
                transcript.append(f"{role}: {content}")
        title_context = (
            f"Initial customer issue: {issue_message}\n"
            f"Conversation flow:\n{chr(10).join(transcript)}\n"
            f"Latest customer message: {message}\n"
        )
        
        title_prompt = f"""Understand the meaning and progression of this support conversation, then generate a short, factual title based on the underlying customer issue.

Context:
{title_context}

Rules:
- 3-10 words maximum
- Maximum 120 characters
- No markdown, quotes, or emojis
- No customer names, passwords, tokens, or sensitive information
- Focus on the actual technical/business issue
- Use the conversation flow to resolve references such as "it", "that", or "still failing"
- Do not title the conversation after a greeting, request for a human, or generic follow-up
- Examples: "Product creation error 500", "Unable to log in", "Payment API timeout"

Return ONLY the title, nothing else. If this is just a greeting or conversational message, return empty string."""

        try:
            title_client = client or self.groq_client
            response = await title_client.chat_completion(
                messages=[ChatMessage(role="user", content=title_prompt)],
                max_tokens=50,
            )
            
            title = " ".join(response.content.strip().split())
            
            # Validate title length and content
            if not title or len(title) > 120 or not 3 <= len(title.split()) <= 10:
                return None
                
            # Clean up any quotes or markdown
            title = title.replace('"', '').replace("'", '').replace('*', '').replace('#', '').replace('`', '').strip()
            
            return title if title else None
            
        except Exception as e:
            logger.warning("Failed to generate conversation title", error=str(e))
            return None

    def _requires_product_selection(self, message: str, conversation_history: List) -> bool:
        """Return whether accurate troubleshooting needs an entitled product choice."""
        context = " ".join(
            [message]
            + [
                item.get("content", "") if isinstance(item, dict) else getattr(item, "content", "")
                for item in conversation_history or []
            ]
        ).lower()
        product_specific_indicators = [
            "401", "403", "404", "500", "error", "api", "integration", "webhook",
            "product", "checkout", "cart", "order", "payment", "shipping", "inventory",
            "catalog", "store", "shop", "purchase", "buy", "plugin", "module", "feature",
        ]
        general_indicators = [
            "how do i contact", "contact support", "reach support", "talk to support",
            "what is shiva", "about shiva", "shiva support",
        ]
        return (
            any(indicator in context for indicator in product_specific_indicators)
            and not any(indicator in context for indicator in general_indicators)
        )

    def _is_explicit_agent_request(self, message: str) -> bool:
        """Detect a direct request for human support that must bypass product gating."""
        agent_request_indicators = [
            "talk to agent", "speak to agent", "speak to staff", "talk to staff",
            "human agent", "real person", "talk to human", "speak to human",
            "agent please", "human please", "real agent", "live agent",
            "i want to speak to a person", "i need to talk to someone",
            "transfer me", "escalate this",
        ]
        message_lower = message.lower()
        return any(indicator in message_lower for indicator in agent_request_indicators)

    async def _product_selection_response(self, message: str, conversation_history: List) -> str:
        """Explain the product requirement without exposing or inventing product choices."""
        try:
            messages = [
                ChatMessage(
                    role="system",
                    content=(
                        "You are a helpful Shiva Support assistant. Explain in clean Markdown "
                        "that the customer's product is needed to provide accurate troubleshooting. "
                        "Do not name, list, guess, or invent products. Ask them to select a product "
                        "from the options shown by the client. Use the conversation history and do "
                        "not repeat steps already tried."
                    ) + LANGUAGE_POLICY,
                )
            ]
            messages.extend(
                self.agent_orchestrator.agents[0]._build_conversation_messages(
                    conversation_history, message
                )
                if conversation_history
                else [ChatMessage(role="user", content=message)]
            )
            response = await self.groq_client.chat_completion(
                messages=messages, temperature=0.7, max_tokens=400, reasoning_effort="low"
            )
            return enforce_language_policy(response.content, message)
        except Exception as e:
            logger.error("Failed to generate product selection response", error=str(e))
            return (
                "To troubleshoot this accurately, I need to know which Shiva product you are "
                "using. Please select your product from the options provided."
            )

    async def handle_customer_message(
        self,
        ticket_id: str,
        customer_id: str,
        message: str,
        ticket_service: Optional[TicketCenterService],
        is_agent_request: bool = False,
        conversation_history: Optional[List] = None,
        customer_data: Optional[Dict[str, Any]] = None,
        product_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Handle a customer message through the Support AI pipeline.

        Process:
        1. Retrieve conversation history (or use provided)
        2. Use customer data provided by frontend (eliminates external API dependency)
        3. Use product context if provided for product-specific guidance
        4. Search knowledge base for relevant context
        5. Check if issue is complex (if agent request)
        6. Generate response using Groq LLM
        7. Based on confidence and complexity, either auto-respond or queue for staff

        Args:
            customer_data: Dict containing customer information provided by frontend
                         (e.g., name, email, account_type, subscription_status, etc.)
            product_context: Dict containing product-specific information:
                          - product_id: str
                          - product_name: str
                          - enabled_modules: List[str]
                          - client_entitled: bool
                          - relevant_knowledge_articles: List[str]

        Returns:
            Dict with keys: action, response, confidence, should_queue, complexity_analysis
        """
        try:
            # Step 1: Get conversation history (or use provided)
            if conversation_history is None and ticket_service:
                conversation_history = await ticket_service.get_ticket_messages(ticket_id)
            elif conversation_history is None:
                conversation_history = []
            else:
                # Convert conversation history to ChatMessage format if it's a list of dicts (from Shiva Support)
                if conversation_history and isinstance(conversation_history[0], dict):
                    # Map Shiva Support role format to LLM role format
                    role_mapping = {
                        "user": "user",
                        "assistant": "assistant",
                        "system": "system"
                    }
                    conversation_history = [
                        ChatMessage(
                            role=role_mapping.get(msg.get("role", "user"), "user"),
                            content=msg.get("content", "")
                        )
                        for msg in conversation_history
                    ]
                elif conversation_history and hasattr(conversation_history[0], 'sender'):
                    # Already in database object format, agents will handle conversion
                    pass
                elif conversation_history and hasattr(conversation_history[0], 'role'):
                    # Already in ChatMessage format from Shiva Support - keep as is
                    pass
                elif not conversation_history:
                    # Empty conversation history is valid (first message)
                    conversation_history = []
                else:
                    # Unknown format - log warning but don't discard
                    logger.warning(
                        "Unknown conversation history format",
                        history_type=type(conversation_history[0]) if conversation_history else None,
                        history_length=len(conversation_history) if conversation_history else 0
                    )
                    # Try to preserve the history anyway
                    conversation_history = list(conversation_history)

            # Determine if this is a follow-up message (customer has received AI help before)
            if conversation_history:
                # Check if history contains ChatMessage format (role/content) or database objects (sender)
                if hasattr(conversation_history[0], 'role'):
                    # ChatMessage format from Shiva Support
                    previous_ai_attempts = [msg for msg in conversation_history if msg.role == "assistant"]
                elif hasattr(conversation_history[0], 'sender'):
                    # Database object format
                    previous_ai_attempts = [
                        msg for msg in conversation_history
                        if hasattr(msg, 'sender') and msg.sender == MessageSender.SUPPORT_AI
                    ]
                else:
                    # Unknown format - assume not follow-up
                    previous_ai_attempts = []
                is_follow_up = len(previous_ai_attempts) > 0
            else:
                is_follow_up = False

            # Initialize complexity_analysis early (needed for early returns)
            complexity_analysis = {
                "is_complex": False,
                "complexity_score": 0.0,
                "reasons": []
            }

            # Step 2: Check for ticket inquiries VERY EARLY in the flow
            # KEY PRINCIPLE: Understand the problem before creating any ticket
            # Ticket-related inquiries (should be handled conversationally, not with instructions)
            ticket_inquiry = [
                "raise a ticket", "raise me a ticket", "raise for me a ticket", "create a ticket", "open a ticket", "submit a ticket",
                "ticket for me", "raise ticket", "create ticket", "open ticket", "i need a ticket", "want a ticket",
                "get a ticket", "need ticket", "want ticket", "i want to raise a ticket", "i want to create a ticket",
                "can you create a ticket", "please create a ticket", "help me create a ticket",
                "file a ticket", "file ticket", "log a ticket", "log ticket", "escalate this to a ticket", "escalate to ticket"
            ]
            has_ticket_inquiry = any(indicator in message.lower() for indicator in ticket_inquiry)

            # Check if message contains actual problem description vs just requesting a ticket
            problem_description_indicators = [
                "error", "issue", "problem", "not working", "doesn't work", "broken", "fail", "failed",
                "can't", "unable", "stuck", "help", "question", "how", "what", "why", "when"
            ]
            has_problem_description = any(indicator in message.lower() for indicator in problem_description_indicators)

            # Typed human requests must use the same immediate escalation path as the UI button.
            if self._is_explicit_agent_request(message):
                is_agent_request = True

            # CRITICAL: Detect gibberish/random keystrokes - NEVER create tickets for these
            def is_gibberish(text: str) -> bool:
                """Detect if text is random keystrokes/gibberish."""
                if len(text) < 10:
                    return False
                # Check for excessive consecutive consonants or repetitive patterns
                words = text.split()
                if not words:
                    return False
                # Check if most words are very long with many consonants (indicative of random typing)
                long_gibberish_words = [w for w in words if len(w) > 8 and sum(1 for c in w.lower() if c in 'bcdfghjklmnpqrstvwxyz') > len(w) * 0.8]
                return len(long_gibberish_words) > len(words) * 0.5

            is_gibberish_message = is_gibberish(message)

            if is_gibberish_message:
                logger.info(
                    "Gibberish/random keystrokes detected - will not create ticket",
                    ticket_id=ticket_id,
                    message=message,
                )
                should_queue = False
                action = "out_of_scope"

                # Use Groq to generate appropriate response for gibberish
                try:
                    # Build messages with conversation history for context
                    messages = [
                        ChatMessage(
                            role="system",
                            content="You are a helpful customer support AI. The user sent a message that appears to be random keystrokes or gibberish. Respond politely and ask them what they need help with. If there is conversation history, read it carefully to understand the context before responding." + LANGUAGE_POLICY
                        )
                    ]
                    
                    # Add conversation history if available
                    if conversation_history:
                        conversation_messages = self.agent_orchestrator.agents[0]._build_conversation_messages(conversation_history, message)
                        messages.extend(conversation_messages)
                    else:
                        messages.append(ChatMessage(role="user", content=message))
                    
                    gibberish_response = await self.groq_client.chat_completion(
                        messages=messages,
                        temperature=0.7,
                        max_tokens=400,
                        reasoning_effort="low",
                    )
                    response_text = gibberish_response.content
                    # Enforce language policy
                    response_text = enforce_language_policy(response_text, message)
                except Exception as e:
                    logger.error("Failed to generate gibberish response", error=str(e))
                    response_text = "It looks like that might have been a typo. How can I help you today?"

                return {
                    "action": action,
                    "response": response_text,
                    "confidence": 0.3,  # Low confidence for fallback hardcoded response
                    "should_queue": should_queue,
                    "kb_context_used": False,
                    "complexity_analysis": complexity_analysis,
                    "kb_similarity_score": None,
                    "kb_article_ids": None,
                    "metadata": {},
                    "needs_product_selection": False,
                    "needs_ticket": False,
                }

            # Check for simple greetings - do this BEFORE vague issue detection
            simple_greetings = ["hello", "hi", "hey", "good morning", "good afternoon", "good evening"]
            is_simple_greeting = any(indicator in message.lower().strip() == indicator for indicator in simple_greetings)
            
            if is_simple_greeting and len(message.split()) <= 3:
                # Just a simple greeting, respond naturally without asking for details
                logger.info(
                    "Simple greeting detected - will respond naturally",
                    ticket_id=ticket_id,
                    message=message,
                )
                should_queue = False
                action = "auto_resolve"
                
                # Use Groq to generate natural greeting response
                try:
                    # Build messages with conversation history for context
                    messages = [
                        ChatMessage(
                            role="system",
                            content="You are a helpful customer support AI for Shiva Softwares. Respond naturally and friendly to the user's greeting. Be conversational and ready to help. If there is conversation history, read it carefully to understand the context before responding." + LANGUAGE_POLICY
                        )
                    ]
                    
                    # Add conversation history if available
                    if conversation_history:
                        conversation_messages = self.agent_orchestrator.agents[0]._build_conversation_messages(conversation_history, message)
                        messages.extend(conversation_messages)
                    else:
                        messages.append(ChatMessage(role="user", content=message))
                    
                    greeting_response = await self.groq_client.chat_completion(
                        messages=messages,
                        temperature=0.8,
                        max_tokens=400,
                        reasoning_effort="low",
                    )
                    response_text = greeting_response.content
                    # Enforce language policy
                    response_text = enforce_language_policy(response_text, message)
                except Exception as e:
                    logger.error("Failed to generate greeting response", error=str(e))
                    response_text = "Hello! I'm here to help you with any Shiva Softwares questions or issues. What can I assist you with today?"
                
                return {
                    "action": action,
                    "response": response_text,
                    "confidence": 0.3,  # Low confidence for fallback hardcoded response
                    "should_queue": should_queue,
                    "kb_context_used": False,
                    "complexity_analysis": complexity_analysis,
                    "kb_similarity_score": None,
                    "kb_article_ids": None,
                    "metadata": {},
                    "needs_product_selection": False,
                    "needs_ticket": False,
                }
            
            # Check for informational questions about raising tickets
            # Provide a fixed response without inventing portals, emails, or phone numbers
            ticket_info_indicators = [
                "how do i raise a ticket",
                "how do i create a ticket",
                "how to raise a ticket",
                "how to create a ticket",
                "how can i raise a ticket",
                "how can i create a ticket",
                "where do i raise a ticket",
                "where can i raise a ticket"
            ]
            
            is_ticket_info_question = any(indicator in message.lower() for indicator in ticket_info_indicators)
            
            if is_ticket_info_question:
                logger.info(
                    "Ticket information question detected - using Groq for response",
                    ticket_id=ticket_id,
                    message=message,
                )
                should_queue = False
                action = "auto_resolve"
                
                # Use Groq to generate helpful response about tickets
                try:
                    # Build messages with conversation history for context
                    messages = [
                        ChatMessage(
                            role="system",
                            content="You are a helpful customer support AI for Shiva Softwares. The user is asking about how to create support tickets. Explain that they should describe their issue and you'll help directly, and only create tickets for complex issues you can't resolve. Be helpful and solution-oriented. If there is conversation history, read it carefully to understand the context before responding." + LANGUAGE_POLICY
                        )
                    ]
                    
                    # Add conversation history if available
                    if conversation_history:
                        conversation_messages = self.agent_orchestrator.agents[0]._build_conversation_messages(conversation_history, message)
                        messages.extend(conversation_messages)
                    else:
                        messages.append(ChatMessage(role="user", content=message))
                    
                    ticket_info_response = await self.groq_client.chat_completion(
                        messages=messages,
                        temperature=0.7,
                        max_tokens=400,
                        reasoning_effort="low",
                    )
                    response_text = ticket_info_response.content
                    # Enforce language policy
                    response_text = enforce_language_policy(response_text, message)
                except Exception as e:
                    logger.error("Failed to generate ticket info response", error=str(e))
                    response_text = "If you're experiencing an issue, just describe what's happening and I'll help you directly. For complex issues, I can create a support ticket. What problem are you facing?"
                
                return {
                    "action": action,
                    "response": response_text,
                    "confidence": 0.3,  # Low confidence for fallback hardcoded response
                    "should_queue": should_queue,
                    "kb_context_used": False,
                    "complexity_analysis": complexity_analysis,
                    "kb_similarity_score": None,
                    "kb_article_ids": None,
                    "metadata": {},
                    "needs_product_selection": False,
                    "needs_ticket": False,
                }
            
            # Skip complexity analysis for simple cases to improve speed
            skip_complexity_analysis = False

            # Check for vague technical issues that need more information
            vague_technical_indicators = [
                "not working", "doesn't work", "broken", "error", "issue", "problem",
                "can't access", "unable to", "fail", "failed", "having trouble"
            ]
            has_vague_technical_issue = any(indicator in message.lower() for indicator in vague_technical_indicators)

            # Check if message is too short or lacks details
            message_too_short = len(message.split()) < 5
            lacks_details = not any([
                "error" in message.lower(),
                "message" in message.lower(),
                "screen" in message.lower(),
                "page" in message.lower(),
                "button" in message.lower(),
                "step" in message.lower(),
                "when" in message.lower(),
                "after" in message.lower()
            ])

            logger.info(
                "Ticket inquiry check",
                message=message,
                message_lower=message.lower(),
                has_ticket_inquiry=has_ticket_inquiry,
                is_follow_up=is_follow_up,
                ticket_inquiry_indicators=ticket_inquiry,
            )

            # EXPLICIT TICKET REQUEST: Detect direct requests to raise/open/create a ticket
            # This must be checked BEFORE the general ticket inquiry check to distinguish
            # between "raise a ticket" (command) vs "how do I raise a ticket" (question)
            ticket_request_indicators = [
                "raise a ticket", "please raise a ticket", "raise ticket for me",
                "open a ticket", "please open a ticket", "open ticket for me",
                "create a ticket", "please create a ticket", "create ticket for me",
                "file a ticket", "please file a ticket", "file ticket for me",
                "submit a ticket", "please submit a ticket", "submit ticket for me",
                "log a ticket", "please log a ticket", "log ticket for me",
                "escalate to a ticket", "escalate this to a ticket", "make a ticket",
                "i need a ticket", "i want a ticket", "can you raise a ticket",
                "can you open a ticket", "can you create a ticket", "need ticket created"
            ]
            is_direct_ticket_request = any(indicator in message.lower() for indicator in ticket_request_indicators)
            
            if is_direct_ticket_request:
                logger.info(
                    "Direct ticket request detected - escalating directly",
                    ticket_id=ticket_id,
                    message=message,
                )
                should_escalate = True
                escalation_reason = "explicit_ticket_request"
                should_queue = True
                action = "queue_for_staff"
                
                # Generate a response acknowledging the ticket creation with context
                try:
                    # Build messages with conversation history for context
                    messages = [
                        ChatMessage(
                            role="system",
                            content="You are a helpful customer support AI for Shiva Softwares. The customer has explicitly requested a support ticket. Acknowledge their request and confirm that you're escalating it to the support team. If there is conversation history, read it carefully to understand the context before responding - acknowledge the issue they've been discussing." + LANGUAGE_POLICY
                        )
                    ]
                    
                    # Add conversation history if available
                    if conversation_history:
                        conversation_messages = self.agent_orchestrator.agents[0]._build_conversation_messages(conversation_history, message)
                        messages.extend(conversation_messages)
                    else:
                        messages.append(ChatMessage(role="user", content=message))
                    
                    ticket_request_response = await self.groq_client.chat_completion(
                        messages=messages,
                        temperature=0.7,
                        max_tokens=400,
                        reasoning_effort="low",
                    )
                    response_text = ticket_request_response.content
                    # Enforce language policy
                    response_text = enforce_language_policy(response_text, message)
                    if not any(term in response_text.lower() for term in ("ticket", "escalat")):
                        response_text = "I understand you'd like a support ticket created. I'm escalating your request to our support team right away."
                except Exception as e:
                    logger.error("Failed to generate ticket request response", error=str(e))
                    response_text = "I understand you'd like a support ticket created. I'm escalating this to our support team right away."
                
                return {
                    "action": action,
                    "response": response_text,
                    "confidence": 1.0,
                    "should_queue": should_queue,
                    "kb_context_used": False,
                    "complexity_analysis": complexity_analysis,
                    "escalation_reason": escalation_reason,
                }

            # Check for ticket inquiries - handle conversationally by asking for the issue
            # KEY PRINCIPLE: Never create a ticket without understanding the problem first
            if has_ticket_inquiry and not is_follow_up:
                # Check if this is a general "how to" question about tickets (informational)
                how_to_ticket_questions = [
                    "how do i raise a ticket", "how to raise a ticket", "how to create a ticket",
                    "how do i create a ticket", "how to submit a ticket", "how do i submit a ticket",
                    "what is a ticket", "what is a support ticket", "how does ticket work",
                    "how do tickets work", "ticket process", "ticket system", "raise ticket",
                    "create ticket", "open ticket", "submit ticket"
                ]
                is_how_to_question = any(question in message.lower() for question in how_to_ticket_questions)
                
                if is_how_to_question:
                    # This is just an informational question about the ticket process
                    # Let the AI answer it naturally without creating a ticket
                    logger.info(
                        "Informational question about ticket process - will answer without creating ticket",
                        ticket_id=ticket_id,
                        message=message,
                    )
                    should_queue = False
                    action = "auto_resolve"
                    
                    # Let the agent system handle this as a normal question
                    # Don't return early - let the agent provide the answer
                elif not has_problem_description:
                    # Customer asked for a ticket but didn't describe the problem
                    logger.info(
                        "Ticket inquiry without problem description - asking for issue details first",
                        ticket_id=ticket_id,
                        message=message,
                        has_ticket_inquiry=has_ticket_inquiry,
                        has_problem_description=has_problem_description,
                    )
                    should_queue = False
                    action = "gather_issue_info"

                    # Generate conversational response asking for the issue
                    # Use Groq to generate conversational response asking for the issue
                    try:
                        # Build messages with conversation history for context
                        messages = [
                            ChatMessage(
                                role="system",
                                content="You are a helpful customer support AI for Shiva Softwares. The customer asked to create a ticket but didn't describe their problem. Respond conversationally, explain that you can help solve their issue directly instead of creating a ticket, and ask them to describe what problem they're experiencing. Be friendly and solution-oriented. If there is conversation history, read it carefully to understand the context before responding." + LANGUAGE_POLICY
                            )
                        ]
                        
                        # Add conversation history if available
                        if conversation_history:
                            conversation_messages = self.agent_orchestrator.agents[0]._build_conversation_messages(conversation_history, message)
                            messages.extend(conversation_messages)
                        else:
                            messages.append(ChatMessage(role="user", content=message))
                        
                        ticket_inquiry_response_obj = await self.groq_client.chat_completion(
                            messages=messages,
                            temperature=0.7,
                            max_tokens=400,
                            reasoning_effort="low",
                        )
                        ticket_inquiry_response = ticket_inquiry_response_obj.content
                        # Enforce language policy
                        ticket_inquiry_response = enforce_language_policy(ticket_inquiry_response, message)
                    except Exception as e:
                        logger.error("Failed to generate ticket inquiry response", error=str(e))
                        ticket_inquiry_response = "I can help you with that! Instead of creating a ticket right away, let me try to solve your issue directly. What problem are you experiencing?"

                    return {
                        "action": action,
                        "response": ticket_inquiry_response,
                        "confidence": 0.3,  # Low confidence for fallback hardcoded response
                        "should_queue": should_queue,
                        "kb_context_used": False,
                        "complexity_analysis": complexity_analysis,
                    }
                else:
                    # Customer described a problem AND asked for a ticket
                    # Try to solve it first instead of immediately creating a ticket
                    logger.info(
                        "Ticket inquiry with problem description - will attempt to solve first",
                        ticket_id=ticket_id,
                        message=message,
                        has_ticket_inquiry=has_ticket_inquiry,
                        has_problem_description=has_problem_description,
                    )
                    # Continue to normal processing to try to solve the issue
                    # Don't create ticket immediately - let the AI try to help first

            # EXPLICIT AGENT REQUEST: If is_agent_request parameter is True, escalate directly
            # This is a hard trigger from the "talk to a human" button - should bypass all gating
            # Check this early to bypass all other logic
            if is_agent_request:
                logger.info(
                    "Explicit agent request detected - escalating directly",
                    ticket_id=ticket_id,
                    is_agent_request=is_agent_request,
                )
                should_escalate = True
                escalation_reason = "explicit_agent_request"
                should_queue = True
                action = "queue_for_staff"
                
                # Keep this acknowledgment deterministic so a model cannot block
                # the handoff by asking for product details.
                response_text = (
                    "I understand you'd like to speak with a human support agent. "
                    "I'm escalating this conversation to the support team now."
                )
                
                return {
                    "action": action,
                    "response": response_text,
                    "confidence": 1.0,
                    "should_queue": should_queue,
                    "kb_context_used": False,
                    "complexity_analysis": complexity_analysis,
                    "escalation_reason": escalation_reason,
                }

            # Check for vague technical issues - but be more lenient with error codes
            # KEY PRINCIPLE: Provide solutions for common errors, ask details only for truly vague issues
            if has_vague_technical_issue and (message_too_short or lacks_details) and not is_follow_up:
                # Check if it's a common error code that we can help with immediately
                common_error_codes = ["401", "402", "403", "404", "500", "502", "503", "504"]
                has_common_error = any(code in message.lower() for code in common_error_codes)
                
                if has_common_error:
                    # For common error codes, try to help immediately instead of asking for details
                    logger.info(
                        "Common error code detected - will attempt to provide solution",
                        ticket_id=ticket_id,
                        message=message,
                    )
                    # Continue to normal processing to try to solve the issue
                else:
                    # Only ask for details if it's truly vague without specific error indicators
                    logger.info(
                        "Vague technical issue detected - asking for more details before resolution",
                        ticket_id=ticket_id,
                        message=message,
                        message_too_short=message_too_short,
                        lacks_details=lacks_details,
                    )
                    should_queue = False
                    action = "gather_details"

                    # Use Groq to generate targeted details gathering response
                    try:
                        # Build messages with conversation history for context
                        messages = [
                            ChatMessage(
                                role="system",
                                content="You are a helpful customer support AI for Shiva Softwares. The user has a vague technical issue. Ask them for specific details like what error message they see, what they were trying to do, which part of the system they were using, and if they have a screenshot. Be helpful and solution-oriented. If there is conversation history, read it carefully to understand the context before responding - never ask for information already provided." + LANGUAGE_POLICY
                            )
                        ]
                        
                        # Add conversation history if available
                        if conversation_history:
                            conversation_messages = self.agent_orchestrator.agents[0]._build_conversation_messages(conversation_history, message)
                            messages.extend(conversation_messages)
                        else:
                            messages.append(ChatMessage(role="user", content=message))
                        
                        details_response_obj = await self.groq_client.chat_completion(
                            messages=messages,
                            temperature=0.7,
                            max_tokens=400,
                            reasoning_effort="low",
                        )
                        details_response = details_response_obj.content
                        # Enforce language policy
                        details_response = enforce_language_policy(details_response, message)
                    except Exception as e:
                        logger.error("Failed to generate details response", error=str(e))
                        details_response = "I can help you troubleshoot this issue! To provide the most accurate solution, could you share what specific error message you're seeing, what you were trying to do when this happened, and which part of the system you were using?"

                    return {
                        "action": action,
                        "response": details_response,
                        "confidence": 0.3,  # Low confidence for fallback hardcoded response
                        "should_queue": should_queue,
                        "kb_context_used": False,
                        "complexity_analysis": complexity_analysis,
                    }

            # Step 3: Use customer data provided by frontend
            # Frontend passes customer data directly since customer is logged in
            customer_account = customer_data

            # Step 4: Search knowledge base with intelligent KB selection
            selected_collection = self._select_knowledge_base(customer_data, message)
            kb_context = await self._retrieve_knowledge_base_context(
                message, 
                customer_data=customer_data, 
                selected_collection=selected_collection,
                product_context=product_context,
            )

            # Step 4.5: Check if product selection is needed.
            # Skip product selection for explicit agent requests - they should escalate immediately
            needs_product_selection = False
            if (
                not is_agent_request  # Don't ask for product if user wants to speak to staff
                and product_context is None
                and ticket_service is None
                and self._requires_product_selection(message, conversation_history)
            ):
                logger.info(
                    "Product-specific issue requires product selection",
                    message=message,
                    ticket_id=ticket_id,
                )
                needs_product_selection = True
                response_text = await self._product_selection_response(message, conversation_history)

                return {
                    "action": "product_selection",
                    "response": response_text,
                    "confidence": 0.3,
                    "should_queue": False,
                    "needs_product_selection": True,
                    "needs_ticket": False,
                    "complexity_analysis": complexity_analysis,
                    "kb_context_used": False,
                    "kb_similarity_score": None,
                    "kb_article_ids": None,
                    "metadata": {},
                }

            # Step 4.5: Use Groq to determine if question is out-of-scope based on KB context
            # This replaces hardcoded keyword matching with intelligent LLM-based classification
            # But be more lenient - only treat as out-of-scope if clearly unrelated and high confidence
            try:
                out_of_scope_analysis = await self.groq_client.is_out_of_scope(
                    message=message,
                    kb_context=kb_context,
                    customer_data=customer_data,
                )
                
                # Only block if very high confidence (>0.9) to avoid blocking legitimate Shiva issues
                if out_of_scope_analysis["is_out_of_scope"] and out_of_scope_analysis["confidence"] > 0.9:
                    logger.info(
                        "Groq determined question is out-of-scope with high confidence",
                        ticket_id=ticket_id,
                        message=message,
                        reasoning=out_of_scope_analysis["reasoning"],
                        confidence=out_of_scope_analysis["confidence"],
                    )
                    should_queue = False
                    action = "out_of_scope"

                    # Use Groq to generate out-of-scope response
                    try:
                        # Build messages with conversation history for context
                        messages = [
                            ChatMessage(
                                role="system",
                                content="You are a helpful customer support AI for Shiva Softwares. The user's question appears to be outside the scope of Shiva Softwares-related topics. Politely redirect them to ask about Shiva Softwares-related questions such as their account, orders, products, payments, or any other Shiva Softwares features. Be helpful and welcoming. If there is conversation history, read it carefully to understand the context before responding." + LANGUAGE_POLICY
                            )
                        ]
                        
                        # Add conversation history if available
                        if conversation_history:
                            conversation_messages = self.agent_orchestrator.agents[0]._build_conversation_messages(conversation_history, message)
                            messages.extend(conversation_messages)
                        else:
                            messages.append(ChatMessage(role="user", content=message))
                        
                        out_of_scope_response_obj = await self.groq_client.chat_completion(
                            messages=messages,
                            temperature=0.7,
                            max_tokens=400,
                            reasoning_effort="low",
                        )
                        out_of_scope_response = out_of_scope_response_obj.content
                        # Enforce language policy
                        out_of_scope_response = enforce_language_policy(out_of_scope_response, message)
                    except Exception as e:
                        logger.error("Failed to generate out-of-scope response", error=str(e))
                        out_of_scope_response = "I'm here to help with any Shiva Softwares-related questions or issues you might have—feel free to ask about your account, orders, products, payments, or anything else Shiva Softwares! What can I assist with today?"

                    return {
                        "action": action,
                        "response": out_of_scope_response,
                        "confidence": out_of_scope_analysis["confidence"],
                        "should_queue": should_queue,
                        "kb_context_used": len(kb_context) > 0,
                        "complexity_analysis": complexity_analysis,
                    }
            except Exception as e:
                logger.error(
                    "Error in Groq out-of-scope analysis, continuing with normal processing",
                    error=str(e),
                    message=message,
                )
                # If Groq analysis fails, continue with normal processing
                # This is a safe fallback

            # Step 6: Use cached complexity analysis for speed
            complexity_analysis = self._analyze_complexity_cached(
                message=message,
                has_kb_context=len(kb_context) > 0,
                history_length=len(conversation_history),
            )

            # Step 7: Determine which client to use based on complexity
            # Use Gemini for complex tasks if configured and threshold met
            complexity_score = complexity_analysis.get("complexity_score", 0.0)
            use_complex_client = (
                self.complex_task_client is not None and
                complexity_score >= settings.gemini_complexity_threshold
            )
            
            client_to_use = self.complex_task_client if use_complex_client else self.groq_client
            
            if use_complex_client:
                logger.info(
                    "Using complex task client (Gemini) for high-complexity issue",
                    complexity_score=complexity_score,
                    threshold=settings.gemini_complexity_threshold,
                )

            # Step 8: Generate response using specialized agent system
            # Try to use specialized agents first, fall back to general if needed
            try:
                agent_response, agent_name = await self.agent_orchestrator.handle_with_agent(
                    message=message,
                    customer_data=customer_data,
                    kb_context=kb_context,
                    conversation_history=conversation_history,
                    product_context=product_context,
                    client=client_to_use,
                )
                
                logger.info(
                    "Response generated by specialized agent",
                    agent=agent_name,
                    client_used="gemini" if use_complex_client else "groq",
                    complexity_score=complexity_score,
                    message_length=len(agent_response),
                )
            except Exception as e:
                # Fallback to Groq if complex client fails
                if use_complex_client:
                    logger.warning(
                        "Complex task client failed, falling back to Groq",
                        error=str(e),
                        complexity_score=complexity_score,
                    )
                    agent_response, agent_name = await self.agent_orchestrator.handle_with_agent(
                        message=message,
                        customer_data=customer_data,
                        kb_context=kb_context,
                        conversation_history=conversation_history,
                        product_context=product_context,
                        client=self.groq_client,
                    )
                    logger.info(
                        "Response generated with fallback to Groq",
                        agent=agent_name,
                        message_length=len(agent_response),
                    )
                else:
                    raise
            
            # Check if this is a simple task
            is_simple_task = self.agent_orchestrator.is_simple_task(message)
            
            # Create LLMResponse from agent response
            response = LLMResponse(
                content=agent_response,
                confidence=0.9 if is_simple_task else 0.8,  # Higher confidence for simple tasks
                metadata={
                    "agent_used": agent_name,
                    "is_simple_task": is_simple_task,
                    "client_used": "gemini" if use_complex_client else "groq",
                    "complexity_score": complexity_score,
                }
            )

            # Step 9: Skip solution validation for simple cases to improve speed
            if not skip_complexity_analysis:
                solution_validation = self._validate_solution_completeness(
                    response.content, 
                    kb_context, 
                    message
                )
            else:
                solution_validation = {"is_complete": True, "confidence": 0.8}
            
            # Step 9: Determine action based on confidence, complexity, and solution quality
            should_queue = False
            action = "auto_resolve"

            # NEW APPROACH: Always try to provide a solution first
            # Only escalate if this is a follow-up message indicating previous solution failed
            solution_failed = self._detect_solution_failure(conversation_history, message)

            # Check if this is a follow-up after an AI provided solution
            previous_ai_attempts = []
            if conversation_history:
                # Check if history contains ChatMessage format (role/content) or database objects (sender)
                if hasattr(conversation_history[0], 'role'):
                    # ChatMessage format from Shiva Support
                    previous_ai_attempts = [msg for msg in conversation_history if msg.role == "assistant"]
                elif hasattr(conversation_history[0], 'sender'):
                    # Database object format
                    previous_ai_attempts = [msg for msg in conversation_history if hasattr(msg, 'sender') and msg.sender == MessageSender.SUPPORT_AI]
                else:
                    # Unknown format
                    previous_ai_attempts = []
                is_follow_up = len(previous_ai_attempts) > 0
            else:
                is_follow_up = False

            # ESCALATION LOGIC - Only create tickets when we understand the problem and cannot solve it
            # KEY PRINCIPLE: Understand first, solve when possible, escalate only when necessary
            # Escalate only when:
            # 1. Previous solution failed (customer indicates it didn't work after trying it)
            # 2. Staff-only issues (security, legal, complex investigations - must have problem description)
            # 3. Multiple failed attempts (customer has tried multiple AI solutions that didn't work)
            # 4. Issue is complex AND we understand it (not in knowledge base, requires investigation)
            # 5. Explicit agent/human request (customer insists on speaking to human - bypasses other checks)
            # Note: Explicit agent request is handled early in the function and returns immediately

            # Require problem description for any escalation (unless explicit agent request handled above)
            if not has_problem_description and not is_follow_up:
                logger.info(
                    "No problem description provided - will not escalate, asking for details",
                    ticket_id=ticket_id,
                    message=message,
                )
                should_queue = False
                action = "gather_details"

                # Use Groq to generate details gathering response
                try:
                    # Build messages with conversation history for context
                    messages = [
                        ChatMessage(
                            role="system",
                            content="You are a helpful customer support AI for Shiva Softwares. The user has a technical issue but hasn't provided enough details. Ask them politely for more specific information like what they were trying to do, any error messages they see, which part of the system they were using, and when the issue started. Be helpful and solution-oriented. If there is conversation history, read it carefully to understand the context before responding - never ask for information already provided." + LANGUAGE_POLICY
                        )
                    ]
                    
                    # Add conversation history if available
                    if conversation_history:
                        conversation_messages = self.agent_orchestrator.agents[0]._build_conversation_messages(conversation_history, message)
                        messages.extend(conversation_messages)
                    else:
                        messages.append(ChatMessage(role="user", content=message))
                    
                    details_response_obj = await self.groq_client.chat_completion(
                        messages=messages,
                        temperature=0.7,
                        max_tokens=400,
                        reasoning_effort="low",
                    )
                    details_response = details_response_obj.content
                    # Enforce language policy
                    details_response = enforce_language_policy(details_response, message)
                except Exception as e:
                    logger.error("Failed to generate details response", error=str(e))
                    details_response = "I'd like to help you with this! To give you the best solution, could you share a bit more detail about what's happening? For example, what exactly are you trying to do when the issue occurs, do you see any error messages, and when did this start?"

                return {
                    "action": action,
                    "response": details_response,
                    "confidence": 0.3,  # Low confidence for fallback hardcoded response
                    "should_queue": should_queue,
                    "kb_context_used": False,
                    "complexity_analysis": complexity_analysis,
                    "escalation_reason": None,
                }

            # Initialize escalation variables for normal flow
            should_escalate = False
            escalation_reason = None

            staff_only_indicators = [
                "charged twice", "unauthorized charge", "refund missing",
                "account hacked", "security breach", "data loss",
                "legal", "complaint"
            ]
            has_staff_only_issue = any(indicator in message.lower() for indicator in staff_only_indicators)
            
            # Removed from automatic escalation - try to solve first:
            # - "account locked" (Groq can often provide password reset guidance)
            # - "production down" (try troubleshooting first)
            # - Server errors (try debugging steps first)
            
            # Additional check: most issues should be solved by Groq first
            # Only escalate for truly complex or security-critical issues
            simple_login_indicators = ["login", "password", "reset", "can't access", "unable to login", "account locked"]
            is_simple_login_issue = any(indicator in message.lower() for indicator in simple_login_indicators)
            
            if is_simple_login_issue and not is_follow_up:
                has_staff_only_issue = False  # Don't escalate simple login issues on first attempt
            
            # Production and server errors - try to solve first
            server_indicators = ["production down", "server error", "500 error", "error 500", "outage"]
            has_server_issue = any(indicator in message.lower() for indicator in server_indicators)
            
            if has_server_issue and not is_follow_up:
                has_staff_only_issue = False  # Try to solve server issues first
            
            # Check for explicit agent/human requests - only escalate if customer insists
            # after AI has attempted to help, or uses strong escalation language
            agent_request_indicators = [
                "talk to agent", "speak to agent", "human agent", "real person",
                "talk to human", "speak to human", "agent please", "human please",
                "real agent", "live agent", "escalate", "escalation", "manager", "supervisor",
                "i want to speak to a person", "i need to talk to someone", "transfer me"
            ]
            # Also include direct ticket request indicators here for defense in depth
            ticket_request_indicators = [
                "raise a ticket", "please raise a ticket", "raise ticket for me",
                "open a ticket", "please open a ticket", "open ticket for me",
                "create a ticket", "please create a ticket", "create ticket for me",
                "file a ticket", "please file a ticket", "file ticket for me",
                "submit a ticket", "please submit a ticket", "submit ticket for me",
                "log a ticket", "please log a ticket", "log ticket for me",
                "escalate to a ticket", "escalate this to a ticket", "make a ticket",
                "i need a ticket", "i want a ticket", "can you raise a ticket",
                "can you open a ticket", "can you create a ticket", "need ticket created",
                "file a ticket", "file ticket", "log a ticket", "log ticket"
            ]
            # General staff inquiry indicators (should be handled with helpful info, not escalation)
            general_staff_inquiry = [
                "can i speak to staff", "can i talk to staff", "speak to staff",
                "talk to staff", "customer service", "support team", "help center"
            ]
            has_general_staff_inquiry = any(indicator in message.lower() for indicator in general_staff_inquiry)
            # Removed: "customer service", "support team" from escalation - these are too general
            has_agent_request = (
                any(indicator in message.lower() for indicator in agent_request_indicators) or
                any(indicator in message.lower() for indicator in ticket_request_indicators)
            )

            multiple_failed_attempts = len(previous_ai_attempts) >= 2 and solution_failed

            # Check for general staff inquiries - provide helpful info instead of escalating
            if has_general_staff_inquiry and not is_follow_up:
                logger.info(
                    "General staff inquiry detected - providing helpful information",
                    ticket_id=ticket_id,
                )
                should_queue = False
                action = "provide_staff_info"

                # Use Groq to generate helpful staff info response
                try:
                    # Build messages with conversation history for context
                    messages = [
                        ChatMessage(
                            role="system",
                            content="You are a helpful customer support AI for Shiva Softwares. The customer is asking about speaking to staff or customer service. Explain that you can help them directly with most issues including account access, order questions, technical problems, or how to use different features. Ask them what specific issue they're facing so you can help immediately instead of making them wait for a ticket. Be friendly and solution-oriented. If there is conversation history, read it carefully to understand the context before responding." + LANGUAGE_POLICY
                        )
                    ]
                    
                    # Add conversation history if available
                    if conversation_history:
                        conversation_messages = self.agent_orchestrator.agents[0]._build_conversation_messages(conversation_history, message)
                        messages.extend(conversation_messages)
                    else:
                        messages.append(ChatMessage(role="user", content=message))
                    
                    staff_info_response_obj = await self.groq_client.chat_completion(
                        messages=messages,
                        temperature=0.7,
                        max_tokens=400,
                        reasoning_effort="low",
                    )
                    staff_info_response = staff_info_response_obj.content
                    # Enforce language policy
                    staff_info_response = enforce_language_policy(staff_info_response, message)
                except Exception as e:
                    logger.error("Failed to generate staff info response", error=str(e))
                    staff_info_response = "I'm here to help you directly! I can assist with most common issues right away, including account access, billing questions, technical problems, or how to use different features of the platform. What specific issue are you facing?"

                return {
                    "action": action,
                    "response": staff_info_response,
                    "confidence": 0.3,  # Low confidence for fallback hardcoded response
                    "should_queue": should_queue,
                    "kb_context_used": False,
                    "complexity_analysis": complexity_analysis,
                }

            # Check if customer is showing frustration or strong insistence
            frustration_indicators = [
                "this is not working", "still not working", "doesn't work",
                "i already tried that", "that didn't help", "useless", "terrible",
                "i'm tired of this", "enough", "just let me talk", "i insist"
            ]
            has_frustration = any(indicator in message.lower() for indicator in frustration_indicators)

            # Only escalate for agent requests if:
            # 1. Customer has already received AI help (follow-up message)
            # 2. Customer shows frustration/insistence
            # 3. Multiple failed attempts
            # Note: Explicit agent request is handled early in the function and returns immediately
            should_escalate_for_agent = has_agent_request and (is_follow_up or has_frustration or multiple_failed_attempts)

            # Debug logging
            logger.debug(
                "Escalation decision factors",
                solution_failed=solution_failed,
                has_staff_only_issue=has_staff_only_issue,
                multiple_failed_attempts=multiple_failed_attempts,
                has_agent_request=has_agent_request,
                should_escalate_for_agent=should_escalate_for_agent,
                has_frustration=has_frustration,
                previous_ai_attempts=len(previous_ai_attempts),
                is_follow_up=is_follow_up,
                complexity_analysis=complexity_analysis,
            )

            # AI-DRIVEN TICKET DECISION: Gemini owns escalation decisions when configured.
            # Groq remains the fallback if Gemini is unavailable or fails.
            escalation_client = self.complex_task_client or self.groq_client
            escalation_client_name = "gemini" if self.complex_task_client else "groq"
            try:
                escalation_decision = await escalation_client.should_escalate(
                    message=message,
                    response=response.content,
                    kb_context=str(kb_context),
                    conversation_history=conversation_history,
                    customer_data=customer_data,
                )
                if not isinstance(escalation_decision, dict):
                    raise ValueError("Escalation client returned non-structured metadata")
                ai_decides_ticket = bool(escalation_decision.get("escalate", False))
                escalation_decision_reason = escalation_decision["reason"]
                escalation_confidence = escalation_decision["confidence"]
                
                logger.info(
                    "AI-driven escalation decision",
                    ticket_id=ticket_id,
                    escalation_client=escalation_client_name,
                    escalate=ai_decides_ticket,
                    reason=escalation_decision_reason,
                    confidence=escalation_confidence,
                )
                
                logger.info(
                    "Structured escalation decision",
                    ticket_id=ticket_id,
                    escalation_client=escalation_client_name,
                    escalate=ai_decides_ticket,
                    reason=escalation_decision_reason,
                    confidence=escalation_confidence,
                )
            except Exception as e:
                logger.error(
                    "Error in structured escalation decision, falling back to phrase-matching",
                    error=str(e),
                    ticket_id=ticket_id,
                )
                # Fallback to phrase-matching if structured decision fails
                ticket_creation_phrases = [
                    "i'll create a ticket", "let me create a ticket", "i'll get this escalated",
                    "let me escalate this", "i'll connect you with", "i'll get our team",
                    "i'll raise a ticket", "create a ticket for you", "escalate to our team",
                    "i'll open a ticket", "let me open a ticket"
                ]
                
                response_lower = response.content.lower()
                ai_decides_ticket = any(phrase in response_lower for phrase in ticket_creation_phrases)
                escalation_decision_reason = "fallback_phrase_matching"
                escalation_confidence = 0.6
                escalation_client_name = "phrase_fallback"
            
            # ADDITIONAL CHECK: If this was an informational ticket question, NEVER create a ticket
            # Only treat as informational if it's actually phrased as a question (how/what/does/is or contains ?)
            informational_ticket_indicators = [
                "how do i raise a ticket", "how to raise a ticket", "how to create a ticket",
                "how do i create a ticket", "how to submit a ticket", "how do i submit a ticket",
                "what is a ticket", "what is a support ticket", "how does ticket work",
                "how do tickets work", "ticket process", "ticket system"
            ]
            message_lower = message.lower()
            # Check if it's a question (starts with question words or contains ?)
            is_question_format = (
                message_lower.startswith(("how ", "what ", "does ", "is ", "can ", "do ")) or
                "?" in message_lower
            )
            # Only treat as informational if it contains ticket indicators AND is a question
            is_informational_ticket_question = (
                is_question_format and
                any(indicator in message_lower for indicator in informational_ticket_indicators)
            )
            
            if is_informational_ticket_question:
                # Force no ticket creation for informational questions
                ai_decides_ticket = False
                logger.info(
                    "Informational ticket question detected - forcing no ticket creation",
                    ticket_id=ticket_id,
                    message=message,
                )
            
            # Force no ticket creation if AI decided against it
            if not ai_decides_ticket:
                # Conservative fallback - only escalate for truly critical issues
                should_escalate = False
                
                # Only escalate for critical security/legal issues
                if has_staff_only_issue:
                    should_escalate = True
                    escalation_reason = "critical_security_legal_issue"
                
                # Only escalate after multiple failed attempts (3+)
                elif multiple_failed_attempts and len(previous_ai_attempts) >= 3:
                    should_escalate = True
                    escalation_reason = f"multiple_failed_attempts_{len(previous_ai_attempts)}"
                
                # Only escalate for high complexity (0.7+ threshold to catch novel issues)
                elif complexity_analysis.get("complexity_score", 0) >= 0.7:
                    should_escalate = True
                    escalation_reason = f"high_complexity_{complexity_analysis.get('complexity_score')}"
            else:
                # AI explicitly decided to create a ticket - use the structured reason
                should_escalate = True
                escalation_reason = f"{escalation_client_name}_ai_decision: {escalation_decision_reason}"
            
            # AI attempts cap: force escalation if cap reached, regardless of other factors
            if ticket_service and await ticket_service.check_ai_attempts_cap(ticket_id):
                should_escalate = True
                escalation_reason = f"ai_attempts_cap_reached_{len(previous_ai_attempts)}"
            
            if should_escalate:
                should_queue = True
                action = "queue_for_staff"

                logger.info(
                    "AI-driven ticket decision",
                    ticket_id=ticket_id,
                    reason=escalation_reason,
                    escalation_client=escalation_client_name,
                    ai_decided=ai_decides_ticket,
                    is_informational=is_informational_ticket_question,
                    previous_attempts=len(previous_ai_attempts),
                    complexity_score=complexity_analysis.get("complexity_score"),
                )
            else:
                # If not escalating, auto-resolve
                should_queue = False
                action = "auto_resolve"

            logger.info(
                "Support AI processed message",
                ticket_id=ticket_id,
                confidence=response.confidence,
                action=action,
                kb_results_count=len(kb_context),
                is_agent_request=is_agent_request,
            )

            # Calculate KB similarity score for analytics
            kb_similarity_score = max([r.score for r in kb_context]) if kb_context else None
            kb_article_ids = [r.id for r in kb_context] if kb_context else None

            # Use the appropriate response based on action
            final_response = response.content if action != "out_of_scope" else response

            # Generate conversation title for meaningful issues
            conversation_title = await self._generate_conversation_title(
                message,
                conversation_history,
                client=client_to_use,
            )

            # Build response with analysis metadata
            result = {
                "action": action,
                "response": response.content,
                "confidence": response.confidence,
                "should_queue": should_queue,
                "kb_context_used": len(kb_context) > 0,
                "complexity_analysis": complexity_analysis,
                "kb_similarity_score": kb_similarity_score,
                "kb_article_ids": kb_article_ids,
                "metadata": response.metadata,
                "ticket_decision_provider": escalation_client_name,
                "escalation_reason": escalation_reason if should_escalate else None,
                "needs_product_selection": False,
                "needs_ticket": should_queue,
                "analysis": {
                    "needs_ticket": should_queue
                }
            }
            
            # Only add conversation_title if it was generated (not a greeting)
            if conversation_title:
                result["analysis"]["conversation_title"] = conversation_title

            return result

        except Exception as e:
            logger.error(
                "Support AI processing failed",
                ticket_id=ticket_id,
                error=str(e),
            )
            # On error, queue for staff
            return {
                "action": "queue_for_staff",
                "response": None,
                "confidence": 0.0,
                "should_queue": True,
                "error": str(e),
                "kb_similarity_score": None,
                "kb_article_ids": None,
                "metadata": {},
            }

    async def handle_customer_message_stream(
        self,
        ticket_id: str,
        customer_id: str,
        message: str,
        ticket_service: Optional[TicketCenterService],
        is_agent_request: bool = False,
        conversation_history: Optional[List] = None,
        customer_data: Optional[Dict[str, Any]] = None,
        product_context: Optional[Dict[str, Any]] = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        """
        Handle a customer message with streaming response.

        This is a simplified streaming version that focuses on the core streaming
        functionality. For production use, this should be expanded to include the
        full pipeline (KB retrieval, escalation decision, etc.).

        Args:
            product_context: Dict containing product-specific information:
                          - product_id: str
                          - product_name: str
                          - enabled_modules: List[str]
                          - client_entitled: bool
                          - relevant_knowledge_articles: List[str]

        Yields dictionaries with keys:
        - content: str (streamed content chunks)
        - done: bool (true on final chunk)
        """
        try:
            # Detect typed agent requests - same logic as normal path
            if self._is_explicit_agent_request(message):
                is_agent_request = True

            # EXPLICIT TICKET REQUEST: Detect direct requests to raise/open/create a ticket
            # This should bypass streaming and escalate immediately
            ticket_request_indicators = [
                "raise a ticket", "please raise a ticket", "raise ticket for me",
                "open a ticket", "please open a ticket", "open ticket for me",
                "create a ticket", "please create a ticket", "create ticket for me",
                "file a ticket", "please file a ticket", "file ticket for me",
                "submit a ticket", "please submit a ticket", "submit ticket for me",
                "log a ticket", "please log a ticket", "log ticket for me",
                "escalate to a ticket", "escalate this to a ticket", "make a ticket",
                "i need a ticket", "i want a ticket", "can you raise a ticket",
                "can you open a ticket", "can you create a ticket", "need ticket created",
                "file a ticket", "file ticket", "log a ticket", "log ticket"
            ]
            is_direct_ticket_request = any(indicator in message.lower() for indicator in ticket_request_indicators)
            
            if is_direct_ticket_request:
                logger.info(
                    "Direct ticket request detected in streaming - escalating immediately",
                    ticket_id=ticket_id,
                    message=message,
                )
                
                # Generate a response acknowledging the ticket creation with context
                try:
                    # Build messages with conversation history for context
                    messages = [
                        ChatMessage(
                            role="system",
                            content="You are a helpful customer support AI for Shiva Softwares. The customer has explicitly requested a support ticket. Acknowledge their request and confirm that you're escalating it to the support team. If there is conversation history, read it carefully to understand the context before responding - acknowledge the issue they've been discussing." + LANGUAGE_POLICY
                        )
                    ]
                    
                    # Add conversation history if available
                    if conversation_history:
                        conversation_messages = self.agent_orchestrator.agents[0]._build_conversation_messages(conversation_history, message)
                        messages.extend(conversation_messages)
                    else:
                        messages.append(ChatMessage(role="user", content=message))
                    
                    ticket_request_response = await self.groq_client.chat_completion(
                        messages=messages,
                        temperature=0.7,
                        max_tokens=400,
                        reasoning_effort="low",
                    )
                    response_text = ticket_request_response.content
                    # Enforce language policy
                    response_text = enforce_language_policy(response_text, message)
                except Exception as e:
                    logger.error("Failed to generate ticket request response in streaming", error=str(e))
                    response_text = "I understand you'd like a support ticket created. I'm escalating this to our support team right away."
                
                # Yield a single chunk with the escalation message
                yield {
                    "content": response_text,
                    "done": False,
                }
                # Yield final chunk with escalation metadata
                yield {
                    "content": "",
                    "done": True,
                    "action": "queue_for_staff",
                    "confidence": 1.0,
                    "should_queue": True,
                    "escalation_reason": "explicit_ticket_request",
                    "agent_name": "SupportAgent",
                }
                return

            # EXPLICIT AGENT REQUEST: Handle typed requests to speak to staff
            if is_agent_request:
                logger.info(
                    "Explicit agent request detected in streaming - escalating immediately",
                    ticket_id=ticket_id,
                    message=message,
                )
                
                # Generate a response acknowledging the escalation with context
                try:
                    # Build messages with conversation history for context
                    messages = [
                        ChatMessage(
                            role="system",
                            content="You are a helpful customer support AI for Shiva Softwares. The customer has explicitly requested to speak with a human agent. Acknowledge their request and confirm that you're escalating it to the support team. Do not ask them to select or identify a product. If there is conversation history, read it carefully to understand the context before responding - acknowledge the issue they've been discussing." + LANGUAGE_POLICY
                        )
                    ]
                    
                    # Add conversation history if available
                    if conversation_history:
                        conversation_messages = self.agent_orchestrator.agents[0]._build_conversation_messages(conversation_history, message)
                        messages.extend(conversation_messages)
                    else:
                        messages.append(ChatMessage(role="user", content=message))
                    
                    agent_request_response = await self.groq_client.chat_completion(
                        messages=messages,
                        temperature=0.7,
                        max_tokens=400,
                        reasoning_effort="low",
                    )
                    response_text = agent_request_response.content
                    # Enforce language policy
                    response_text = enforce_language_policy(response_text, message)
                except Exception as e:
                    logger.error("Failed to generate agent request response in streaming", error=str(e))
                    response_text = "I understand you'd like to speak with a human agent. I'm escalating your request to our support team right away."
                
                # Yield a single chunk with the escalation message
                yield {
                    "content": response_text,
                    "done": False,
                }
                # Yield final chunk with escalation metadata
                yield {
                    "content": "",
                    "done": True,
                    "action": "queue_for_staff",
                    "confidence": 1.0,
                    "should_queue": True,
                    "needs_product_selection": False,
                    "needs_ticket": True,
                    "analysis": {"needs_product_selection": False, "needs_ticket": True},
                    "escalation_reason": "explicit_agent_request",
                    "agent_name": "SupportAgent",
                }
                return

            # Convert conversation history to ChatMessage format if it's a list of dicts (from Shiva Support)
            if conversation_history and isinstance(conversation_history[0], dict):
                # Map Shiva Support role format to LLM role format
                role_mapping = {
                    "user": "user",
                    "assistant": "assistant",
                    "system": "system"
                }
                conversation_history = [
                    ChatMessage(
                        role=role_mapping.get(msg.get("role", "user"), "user"),
                        content=msg.get("content", "")
                    )
                    for msg in conversation_history
                ]
            elif conversation_history and hasattr(conversation_history[0], 'sender'):
                # Already in database object format, agents will handle conversion
                pass
            else:
                # Empty or unknown format
                conversation_history = []

            # Stop before retrieval and answer generation when product-specific context is required.
            # Skip product selection for explicit agent requests - they should escalate immediately
            needs_product_selection = (
                not is_agent_request  # Don't ask for product if user wants to speak to staff
                and product_context is None
                and ticket_service is None
                and self._requires_product_selection(message, conversation_history)
            )
            if needs_product_selection:
                response_text = await self._product_selection_response(message, conversation_history)
                yield {"content": response_text, "done": False}
                yield {
                    "content": "",
                    "done": True,
                    "action": "product_selection",
                    "confidence": 0.3,
                    "should_queue": False,
                    "needs_product_selection": True,
                    "needs_ticket": False,
                    "analysis": {
                        "needs_product_selection": True,
                        "needs_ticket": False,
                    },
                }
                return

            # Retrieve KB context (same as normal path)
            selected_collection = self._select_knowledge_base(customer_data, message)
            kb_context = await self._retrieve_knowledge_base_context(
                message, 
                customer_data=customer_data, 
                selected_collection=selected_collection,
                product_context=product_context,
            )

            # Stream the AI response
            full_response = ""
            agent_name = ""

            async for chunk, chunk_agent_name in self.agent_orchestrator.handle_with_agent_stream(
                message=message,
                customer_data=customer_data,
                kb_context=kb_context,
                conversation_history=conversation_history,
                product_context=product_context,
            ):
                if chunk_agent_name:  # First chunk contains agent name
                    agent_name = chunk_agent_name
                full_response += chunk
                yield {
                    "content": chunk,
                    "done": False,
                }

            # Generate conversation title for meaningful issues
            conversation_title = await self._generate_conversation_title(
                message,
                conversation_history,
                client=self.complex_task_client or self.groq_client,
            )

            # Build analysis metadata
            analysis_metadata = {
                "needs_ticket": False
            }
            
            # Only add conversation_title if it was generated (not a greeting)
            if conversation_title:
                analysis_metadata["conversation_title"] = conversation_title

            # Yield final chunk with metadata
            yield {
                "content": "",
                "done": True,
                "action": "auto_resolve",
                "confidence": 0.8,
                "should_queue": False,
                "kb_context_used": len(kb_context) > 0,
                "complexity_analysis": {"is_complex": False, "complexity_score": 0.0, "reasons": []},
                "kb_similarity_score": max([r.score for r in kb_context]) if kb_context else None,
                "kb_article_ids": [r.id for r in kb_context] if kb_context else None,
                "metadata": {"agent_used": agent_name},
                "escalation_reason": None,
                "needs_product_selection": needs_product_selection,
                "needs_ticket": False,
                "analysis": analysis_metadata
            }

        except Exception as e:
            logger.error(
                "Support AI streaming processing failed",
                ticket_id=ticket_id,
                error=str(e),
            )
            # Yield error as final chunk
            yield {
                "content": "",
                "done": True,
                "error": str(e),
            }
            raise

    def _select_knowledge_base(
        self,
        customer_data: Optional[Dict[str, Any]],
        message: str,
    ) -> str:
        """
        Select the appropriate knowledge base based on the customer's application.
        
        The frontend provides the application information in customer_data.
        Selection priority:
        1. Application-based (from customer_data.application)
        2. Default KB as fallback
        """
        # Application-based selection (primary method)
        if customer_data:
            application = customer_data.get("application", "").lower()
            app_rules = settings.kb_selection_rules["application_based"]
            
            if application and application in app_rules:
                selected_kb = app_rules[application]
                logger.info(
                    "KB selected based on customer application",
                    application=application,
                    selected_kb=selected_kb,
                    customer_id=customer_data.get("customer_id"),
                )
                return selected_kb
        
        # Default fallback
        default_kb = settings.qdrant_collections["default"]
        logger.info(
            "Using default knowledge base (no application specified)",
            default_kb=default_kb,
            message=message,
            application=customer_data.get("application") if customer_data else None,
        )
        return default_kb

    async def _retrieve_knowledge_base_context(
        self,
        query: str,
        max_results: int = 5,
        score_threshold: Optional[float] = None,
        customer_data: Optional[Dict[str, Any]] = None,
        selected_collection: Optional[str] = None,
        product_context: Optional[Dict[str, Any]] = None,
    ) -> List[SearchResult]:
        """Retrieve relevant context from knowledge base with intelligent KB selection and product filtering."""
        try:
            # Select appropriate KB based on customer data and message (if not provided)
            if selected_collection is None:
                selected_collection = self._select_knowledge_base(customer_data, query)
            
            # Embed the query
            query_vector = await self.qdrant_client.embed_text(query)
            
            # Use provided threshold or default to settings
            threshold = score_threshold or settings.qdrant_similarity_threshold
            
            # Build filter for product_id if product_context is present
            filter_condition = None
            if product_context and product_context.get("product_id"):
                product_id = product_context["product_id"]
                # Filter by product_id in the payload
                filter_condition = {
                    "must": [
                        {
                            "key": "product_id",
                            "match": {"value": product_id}
                        }
                    ]
                }
                logger.info(
                    "Filtering KB by product_id",
                    product_id=product_id,
                    product_name=product_context.get("product_name"),
                )
            
            # Search for similar documents in the selected collection
            search_kwargs = {
                "query_vector": query_vector,
                "limit": max_results,
                "score_threshold": threshold,
                "collection_name": selected_collection,
            }
            if filter_condition is not None:
                search_kwargs["filter"] = filter_condition
            results = await self.qdrant_client.search(**search_kwargs)
            
            logger.debug(
                "Retrieved KB context",
                query_length=len(query),
                results_count=len(results),
                threshold=threshold,
                selected_collection=selected_collection,
                customer_plan=customer_data.get("plan") if customer_data else None,
                product_id=product_context.get("product_id") if product_context else None,
            )
            
            return results
            
        except Exception as e:
            logger.error(
                "Failed to retrieve KB context",
                error=str(e),
            )
            return []




    async def _is_out_of_scope_groq(self, message: str) -> bool:
        """
        Use Groq API to intelligently determine if a message is out of scope for Shiva Softwares support.
        
        This is more accurate than keyword matching as it understands context and nuance.
        """
        try:
            # Use Groq to classify if the message is in-scope
            classification_prompt = f"""Classify if this customer message is IN-SCOPE or OUT-OF-SCOPE for Shiva Softwares customer support.

IN-SCOPE messages relate to:
- Account access (login, password, account locked, verification)
- Billing and payments (payment failed, card declined, refund, invoice)
- Orders and delivery (order tracking, delivery issues, shipping)
- Account management (login, password, profile, addresses)
- Products and browsing (catalogue, search, product details)
- Shopping and checkout (cart, coupons, payment process)
- Returns and refunds (return policy, refund requests)
- Technical issues (errors, bugs, checkout problems)
- Product reviews and ratings
- General Shiva Softwares support questions

OUT-OF-SCOPE messages include:
- Personal feelings/emotions (bored, tired, happy, sad, frustrated, angry)
- Casual conversation (how are you, nice to meet you, what's up)
- Entertainment requests (jokes, games, movies, music, fun facts)
- General knowledge questions unrelated to Shiva Softwares
- Personal life matters (relationships, health, family, personal advice)
- Political/religious discussions
- News/current events (unless directly related to Shiva Softwares)
- Weather, sports scores, entertainment news
- Philosophical or abstract questions
- Creative writing or content generation requests
- Role-playing or fictional scenarios

Customer message: "{message}"

Respond with ONLY "IN-SCOPE" or "OUT-OF-SCOPE" (no explanation needed)."""

            classification_response = await self.groq_client.chat_completion(
                messages=[ChatMessage(role="user", content=classification_prompt)],
                temperature=0.1,  # Low temperature for consistent classification
                max_tokens=10,   # Only need classification result
                reasoning_effort="low",  # Classification doesn't need reasoning
            )
            
            classification = classification_response.content.strip().upper()
            
            is_out_of_scope = classification == "OUT-OF-SCOPE"
            
            logger.debug(
                "Groq-based scope classification",
                message=message[:50] + "..." if len(message) > 50 else message,
                classification=classification,
                is_out_of_scope=is_out_of_scope,
            )
            
            return is_out_of_scope
            
        except Exception as e:
            logger.error(
                "Groq scope classification failed, falling back to conservative approach",
                error=str(e),
            )
            # If Groq fails, assume in-scope to avoid blocking legitimate issues
            return False


    def _detect_solution_failure(
        self,
        conversation_history: List,
        current_message: str
    ) -> bool:
        """
        Detect if the customer is indicating that a previous solution didn't work.
        
        This analyzes the conversation history and current message to identify
        patterns that suggest previous AI solutions were unsuccessful.
        """
        if not conversation_history:
            return False
        
        current_message_lower = current_message.lower()
        
        # Direct indicators that previous solution failed
        failure_indicators = [
            "didn't work", "did not work", "not working", "still not working",
            "still broken", "still failing", "still getting error", "same error",
            "tried that", "already tried", "doesn't help", "didn't help",
            "nothing changed", "no change", "still the same", "still having",
            "didn't fix", "didn't resolve", "didn't solve", "no luck",
            "worse", "getting worse", "even worse", "different error",
            "doesn't work", "still doesn't", "still not", "doesn't seem"
        ]

        # Indicators that customer needs more help after receiving solution
        # This suggests the solution wasn't clear or sufficient
        repeated_guidance_indicators = [
            "guide me step by step", "guide me through this", "walk me through this",
            "help me with this", "explain this more", "need more help",
            "don't understand", "confused", "not clear", "clarify",
            "more details", "step by step", "walkthrough", "guide"
        ]
        
        # Check for explicit agent/human requests
        agent_request_indicators = [
            "talk to agent", "speak to agent", "human agent", "real person",
            "talk to human", "speak to human", "agent please", "human please",
            "customer service", "support team", "real agent", "live agent"
        ]
        
        for indicator in failure_indicators:
            if indicator in current_message_lower:
                logger.debug(
                    "Solution failure detected",
                    indicator=indicator,
                )
                return True
        
        # Check for repeated guidance requests (indicates solution wasn't clear)
        for indicator in repeated_guidance_indicators:
            if indicator in current_message_lower:
                logger.debug(
                    "Repeated guidance request detected - solution unclear",
                    indicator=indicator,
                )
                return True
        
        # Check for explicit agent/human requests
        for indicator in agent_request_indicators:
            if indicator in current_message_lower:
                logger.debug(
                    "Explicit agent request detected",
                    indicator=indicator,
                )
                return True
        
        # Check if customer is repeating the same issue after AI provided solution
        if conversation_history:
            # Check if history contains ChatMessage format (role/content) or database objects (sender)
            if hasattr(conversation_history[0], 'role'):
                # ChatMessage format from Shiva Support
                previous_ai_messages = [msg for msg in conversation_history if msg.role == "assistant"]
            elif hasattr(conversation_history[0], 'sender'):
                # Database object format
                previous_ai_messages = [msg for msg in conversation_history if hasattr(msg, 'sender') and msg.sender == MessageSender.SUPPORT_AI]
            else:
                # Unknown format
                previous_ai_messages = []
        else:
            previous_ai_messages = []
        
        if not previous_ai_messages:
            return False
        
        # Check if current message contains similar keywords to initial problem
        # but after AI has already provided a solution
        if len(previous_ai_messages) >= 1:
            # Get the initial customer message
            initial_customer_msg = None
            if conversation_history:
                if hasattr(conversation_history[0], 'role'):
                    # ChatMessage format
                    for msg in conversation_history:
                        if msg.role == "user":
                            initial_customer_msg = msg
                            break
                elif hasattr(conversation_history[0], 'sender'):
                    # Database object format
                    for msg in conversation_history:
                        if hasattr(msg, 'sender') and msg.sender == MessageSender.CUSTOMER:
                            initial_customer_msg = msg
                            break
            
            if initial_customer_msg:
                # Check if current message has significant overlap with initial problem
                initial_words = set(initial_customer_msg.content.lower().split())
                current_words = set(current_message_lower.split())
                overlap = len(initial_words & current_words) / len(initial_words) if initial_words else 0
                
                # If high overlap (>60%) after AI already provided solution, suggests solution failed
                if overlap > 0.6:
                    logger.debug(
                        "Recurring issue detected after AI solution",
                        overlap=overlap,
                    )
                    return True
        
        return False

    def _validate_solution_completeness(
        self,
        response_content: str,
        kb_context: List[SearchResult],
        original_message: str
    ) -> Dict[str, Any]:
        """
        Validate that the AI response provides a complete, actionable solution.
        
        This ensures customers receive working solutions rather than just information.
        """
        if not response_content:
            return {
                "is_complete": False,
                "missing_elements": ["No response content"],
                "confidence": 0.0
            }
        
        response_lower = response_content.lower()
        missing_elements = []
        
        # Check for step-by-step structure
        step_indicators = ["step", "first", "then", "next", "finally", "1.", "2.", "3."]
        has_steps = any(indicator in response_lower for indicator in step_indicators)
        if not has_steps:
            missing_elements.append("Missing step-by-step instructions")
        
        # Check for actionable elements (UI elements, specific actions)
        actionable_elements = ["click", "select", "go to", "navigate", "button", "menu", "tab", "settings"]
        has_actionable = any(element in response_lower for element in actionable_elements)
        if not has_actionable:
            missing_elements.append("Missing specific actionable elements")
        
        # Check for verification or confirmation
        verification_elements = ["verify", "check", "confirm", "should see", "will appear", "successful"]
        has_verification = any(element in response_lower for element in verification_elements)
        if not has_verification:
            missing_elements.append("Missing verification steps")
        
        # Check if response addresses the original question
        original_words = set(original_message.lower().split())
        response_words = set(response_lower.split())
        overlap = len(original_words & response_words) / len(original_words) if original_words else 0
        
        if overlap < 0.3:  # Less than 30% word overlap
            missing_elements.append("Response may not address the original question")
        
        # Check for escalation without solution
        escalation_without_solution = any(phrase in response_lower for phrase in [
            "contact support", "reach out", "speak to agent", "cannot help"
        ])
        if escalation_without_solution and len(missing_elements) > 0:
            missing_elements.append("Escalating without providing attempted solution")
        
        # Calculate completeness score
        completeness_score = 1.0
        if not has_steps:
            completeness_score -= 0.3
        if not has_actionable:
            completeness_score -= 0.3
        if not has_verification:
            completeness_score -= 0.2
        if overlap < 0.3:
            completeness_score -= 0.2
        if escalation_without_solution and len(missing_elements) > 0:
            completeness_score -= 0.3
        
        # REVISED APPROACH: Always consider solutions complete enough to try
        # We want to give customers something to try first, then escalate if it fails
        # Only mark as incomplete if there's truly no actionable content at all
        if not kb_context and not has_actionable:
            # Only incomplete if no KB AND no actionable steps
            missing_elements.append("No knowledge base support and no actionable steps")
            is_complete = False
        else:
            # Always consider it complete if there are any actionable steps
            # Let the customer try it and report back if it doesn't work
            is_complete = True
        
        logger.debug(
            "Solution completeness validation",
            is_complete=is_complete,
            completeness_score=completeness_score,
            missing_elements=missing_elements,
            has_steps=has_steps,
            has_actionable=has_actionable,
            has_verification=has_verification,
            has_kb_context=len(kb_context) > 0,
        )
        
        return {
            "is_complete": is_complete,
            "missing_elements": missing_elements,
            "completeness_score": completeness_score,
            "confidence": completeness_score
        }



    @lru_cache(maxsize=100)
    def _analyze_complexity_cached(
        self,
        message: str,
        has_kb_context: bool,
        history_length: int,
    ) -> Dict[str, Any]:
        """
        Cached version of complexity analysis for frequently seen messages.
        """
        complexity_score = 0.0
        reasons = []

        # Factor 1: No knowledge base match
        if not has_kb_context:
            complexity_score += 0.7
            reasons.append("No knowledge base match - issue not documented, requires human investigation")

        # Factor 2: Long conversation history
        if history_length > 8:
            complexity_score += 0.3
            reasons.append(f"Long conversation history ({history_length} messages)")

        # Factor 3: Emotional language
        frustration_indicators = [
            "frustrated", "angry", "upset", "annoyed", "disappointed",
            "not working", "still broken", "never works", "again",
            "this is ridiculous", "unacceptable", "terrible", "awful"
        ]
        message_lower = message.lower()
        for indicator in frustration_indicators:
            if indicator in message_lower:
                complexity_score += 0.2
                reasons.append(f"Frustration detected: '{indicator}'")
                break

        # Factor 4: Multiple topics
        topic_indicators = ["and", "also", "plus", "another", "additionally"]
        topic_count = sum(1 for indicator in topic_indicators if indicator in message_lower)
        if topic_count >= 2:
            complexity_score += 0.2
            reasons.append(f"Multiple topics detected ({topic_count} topic indicators)")

        # Determine if complex - lowered threshold to catch novel undocumented issues
        # A calm, novel, undocumented issue (0.7 from no KB match) should still escalate
        is_complex = complexity_score >= 0.7  # Lowered from 0.8 to catch novel issues

        return {
            "is_complex": is_complex,
            "complexity_score": complexity_score,
            "reasons": reasons
        }

    async def _analyze_complexity(
        self,
        message: str,
        kb_context: List[SearchResult],
        conversation_history: List,
    ) -> Dict[str, Any]:
        """
        Analyze if an issue is complex enough to require human intervention.
        This is now a simple wrapper around the cached version for compatibility.
        """
        return self._analyze_complexity_cached(
            message=message,
            has_kb_context=len(kb_context) > 0,
            history_length=len(conversation_history),
        )

        return {
            "is_complex": is_complex,
            "complexity_score": complexity_score,
            "reasons": reasons,
        }

    async def generate_chat_summary(
        self,
        ticket_id: str,
        conversation_history: List,
        escalation_reason: str,
    ) -> str:
        """
        Generate a comprehensive summary of the conversation for staff review.

        This creates a detailed summary that helps staff understand:
        - What the customer's issue is
        - What the AI tried to resolve and why it failed
        - What solutions were attempted
        - What specific information is missing
        - Clear next steps for staff
        """
        if not conversation_history:
            return "No conversation history available."

        from app.db.models import MessageSender

        # Build a comprehensive summary from the conversation
        summary_parts = [
            "=== TICKET ESCALATION SUMMARY ===",
            f"Ticket ID: {ticket_id}",
            f"Total Messages: {len(conversation_history)}",
            f"Escalation Reason: {escalation_reason}",
            "",
            LANGUAGE_POLICY,
            "",
            "=== CUSTOMER ISSUE ANALYSIS ===",
        ]

        # Get customer's initial message and classify the issue
        if conversation_history:
            first_message = conversation_history[0]
            # Check if it's a database object or ChatMessage format
            if hasattr(first_message, 'sender') and not hasattr(first_message, 'role'):
                # Database object format (has sender but not role)
                if first_message.sender == MessageSender.CUSTOMER:
                    summary_parts.append(f"Initial Issue: {first_message.content[:200]}...")
                    
                    # Classify issue type
                    issue_content = first_message.content.lower()
                    issue_type = "General Support"
                    if "password" in issue_content or "login" in issue_content:
                        issue_type = "Account Access"
                    elif "billing" in issue_content or "payment" in issue_content:
                        issue_type = "Billing/Payment"
                    elif "error" in issue_content or "crash" in issue_content or "500" in issue_content:
                        issue_type = "Technical Error"
                    elif "delivery" in issue_content or "shipping" in issue_content:
                        issue_type = "Order/Shipping"
                    
                    summary_parts.append(f"Classified Issue Type: {issue_type}")
            else:
                # ChatMessage format
                if first_message.role == "user":
                    summary_parts.append(f"Initial Issue: {first_message.content[:200]}...")
                    
                    # Classify issue type
                    issue_content = first_message.content.lower()
                    issue_type = "General Support"
                    if "password" in issue_content or "login" in issue_content:
                        issue_type = "Account Access"
                    elif "billing" in issue_content or "payment" in issue_content:
                        issue_type = "Billing/Payment"
                    elif "error" in issue_content or "crash" in issue_content or "500" in issue_content:
                        issue_type = "Technical Error"
                    elif "delivery" in issue_content or "shipping" in issue_content:
                        issue_type = "Order/Shipping"
                    
                    summary_parts.append(f"Classified Issue Type: {issue_type}")

        # Count messages by sender
        # Categorize messages by sender/role
        if conversation_history:
            # Check if history contains ChatMessage format (role/content) or database objects (sender)
            if hasattr(conversation_history[0], 'role'):
                # ChatMessage format from Shiva Support
                customer_messages = [m for m in conversation_history if m.role == "user"]
                ai_messages = [m for m in conversation_history if m.role == "assistant"]
                system_messages = [m for m in conversation_history if m.role == "system"]
            elif hasattr(conversation_history[0], 'sender'):
                # Database object format
                customer_messages = [m for m in conversation_history if hasattr(m, 'sender') and m.sender == MessageSender.CUSTOMER]
                ai_messages = [m for m in conversation_history if hasattr(m, 'sender') and m.sender == MessageSender.SUPPORT_AI]
                system_messages = [m for m in conversation_history if hasattr(m, 'sender') and m.sender == MessageSender.SYSTEM]
        else:
            customer_messages = []
            ai_messages = []
            system_messages = []

        summary_parts.extend([
            f"Customer Messages: {len(customer_messages)}",
            f"AI Response Attempts: {len(ai_messages)}",
            f"System Messages: {len(system_messages)}",
            "",
        ])

        # Extract detailed information from customer messages
        if customer_messages:
            summary_parts.append("=== CUSTOMER COMMUNICATION ===")
            for i, msg in enumerate(customer_messages[-3:], 1):  # Last 3 customer messages
                summary_parts.append(f"{i}. Customer: {msg.content[:150]}...")
            summary_parts.append("")

        # Analyze AI attempts and what was tried
        if ai_messages:
            summary_parts.append("=== AI ATTEMPT ANALYSIS ===")
            summary_parts.append(f"The AI attempted to resolve this issue {len(ai_messages)} time(s).")
            
            # Analyze what solutions AI provided
            solutions_attempted = []
            for ai_msg in ai_messages:
                # Check if it's a database object or ChatMessage format
                if hasattr(ai_msg, 'sender'):
                    # Database object format
                    content_lower = ai_msg.content.lower()
                else:
                    # ChatMessage format
                    content_lower = ai_msg.content.lower()
                    
                if "step" in content_lower or "follow" in content_lower:
                    solutions_attempted.append("Step-by-step instructions")
                if "settings" in content_lower or "button" in content_lower:
                    solutions_attempted.append("UI navigation guidance")
                if "contact support" in content_lower or "escalate" in content_lower:
                    solutions_attempted.append("Escalation without solution")
            
            if solutions_attempted:
                summary_parts.append("Solutions Attempted:")
                for solution in set(solutions_attempted):
                    summary_parts.append(f"- {solution}")
            
            # Last AI response analysis
            last_ai_response = ai_messages[-1]
            # Check if it's a database object or ChatMessage format
            if hasattr(last_ai_response, 'sender'):
                # Database object format
                summary_parts.append(f"Final AI Response: {last_ai_response.content[:200]}...")
            else:
                # ChatMessage format
                summary_parts.append(f"Final AI Response: {last_ai_response.content[:200]}...")
            
            # Check if AI provided incomplete solution
            if len(ai_messages) > 1:
                summary_parts.append("Note: Multiple AI attempts suggest incomplete or unclear guidance provided.")
            
            # Detect failure indicators from customer follow-ups
            if len(customer_messages) > 1:
                summary_parts.append("=== WHY AI SOLUTIONS FAILED ===")
                failure_indicators = []
                for msg in customer_messages[1:]:  # Skip initial message
                    content_lower = msg.content.lower()
                    if "doesn't work" in content_lower or "didn't work" in content_lower or "still" in content_lower:
                        failure_indicators.append("Customer reported solution didn't work")
                    if "error" in content_lower:
                        failure_indicators.append("Customer encountering errors")
                    if "confused" in content_lower or "unclear" in content_lower:
                        failure_indicators.append("Customer found instructions unclear")
                
                if failure_indicators:
                    for indicator in set(failure_indicators):
                        summary_parts.append(f"- {indicator}")
                else:
                    summary_parts.append("- Customer continued asking questions, suggesting AI solution was insufficient")
            summary_parts.append("")

        # Identify what's missing for resolution
        summary_parts.extend([
            "=== MISSING INFORMATION FOR AI RESOLUTION ===",
            "- Specific details about what exactly isn't working",
            "- Error messages or screenshots if applicable",
            "- Customer's current step in the process",
            "- Account-specific information (plan type, account status)",
            "",
        ])

        # Provide clear next steps for staff
        summary_parts.extend([
            "=== RECOMMENDED NEXT STEPS FOR STAFF ===",
            "1. Review the full conversation history to understand the issue context",
            "2. Ask specific clarifying questions about what isn't working",
            "3. Request screenshots or error messages if technical issue",
            "4. Check customer account status and plan limitations",
            "5. Provide step-by-step solution with verification steps",
            "6. If solution provided, ask customer to verify it worked",
            "7. Document the final solution for knowledge base improvement",
            "",
            "=== EXPECTED RESOLUTION TIME ===",
            "- Simple clarification: 5-10 minutes",
            "- Account investigation: 15-30 minutes", 
            "- Technical troubleshooting: 30-60 minutes",
            "- Complex issue: 1-2 hours or escalation to specialist",
        ])

        return "\n".join(summary_parts)

    async def process_and_respond(
        self,
        ticket_id: str,
        customer_id: str,
        message: str,
        ticket_service: Optional[TicketCenterService],
        is_agent_request: bool = False,
    ) -> bool:
        """
        Process message and send response if confident.

        Returns True if response was sent, False if queued for staff.
        """
        result = await self.handle_customer_message(
            ticket_id=ticket_id,
            customer_id=customer_id,
            message=message,
            ticket_service=ticket_service,
            is_agent_request=is_agent_request,
        )

        if result["action"] == "auto_resolve" and result["response"]:
            # Send the AI response (only if ticket_service exists)
            if ticket_service:
                await ticket_service.append_message(
                    ticket_id=ticket_id,
                    sender=MessageSender.SUPPORT_AI,
                    content=result["response"],
                )

                # Increment AI attempts counter on the ticket
                await ticket_service.increment_ai_attempts(ticket_id)

                # Store AI confidence before auto-resolving
                await ticket_service.store_ai_confidence(ticket_id, result["confidence"])

                # Store AI resolution metadata for analytics
                agent_type = result.get("metadata", {}).get("agent_used") if result.get("metadata") else None
                kb_similarity = result.get("kb_similarity_score")
                kb_article_ids = result.get("kb_article_ids")
                
                await ticket_service.store_ai_resolution_metadata(
                    ticket_id=ticket_id,
                    agent_type=agent_type,
                    kb_article_ids=kb_article_ids,
                    kb_similarity_score=kb_similarity,
                )

                # Auto-resolve the ticket if confident
                await ticket_service.resolve_auto(ticket_id)

                logger.info(
                    "Support AI auto-responded and resolved ticket",
                    ticket_id=ticket_id,
                    confidence=result["confidence"],
                    is_agent_request=is_agent_request,
                )

            return True
        elif result["action"] == "out_of_scope":
            # Send the out-of-scope response without creating/resolving tickets
            if ticket_service:
                await ticket_service.append_message(
                    ticket_id=ticket_id,
                    sender=MessageSender.SUPPORT_AI,
                    content=result["response"],
                )
                logger.info(
                    "Support AI responded to out-of-scope message without ticket resolution",
                    ticket_id=ticket_id,
                )
            return True
        else:
            # Queue for staff with chat summary (only if ticket_service exists)
            if ticket_service:
                # Use the actual escalation reason from handle_customer_message
                reason = result.get("escalation_reason")
                if not reason:
                    # Fallback to complexity analysis if escalation_reason not available
                    if result.get("complexity_analysis") and result["complexity_analysis"]["is_complex"]:
                        reason = f"Complex issue detected: {', '.join(result['complexity_analysis']['reasons'])}"
                    else:
                        reason = result.get("error", "Low confidence in AI response")

                # Generate chat summary before queuing
                conversation_history = await ticket_service.get_ticket_messages(ticket_id)
                chat_summary = await self.generate_chat_summary(
                    ticket_id=ticket_id,
                    conversation_history=conversation_history,
                    escalation_reason=reason,
                )

                # Store AI's solution as staff-only artifact
                await ticket_service.create_ai_suggested_resolution(
                    ticket_id=ticket_id,
                    suggested_solution=result.get("response", ""),
                    confidence=result.get("confidence", 0.0),
                    escalation_reason=reason,
                    kb_article_ids=result.get("kb_article_ids"),
                    kb_similarity_score=result.get("kb_similarity_score"),
                    agent_type=result.get("metadata", {}).get("agent_used") if result.get("metadata") else None,
                )

                # Send customer-facing status message (not the AI's technical solution)
                customer_status_message = self._generate_escalation_status_message(message)
                await ticket_service.append_message(
                    ticket_id=ticket_id,
                    sender=MessageSender.SUPPORT_AI,
                    content=customer_status_message,
                )

                await ticket_service.queue_for_staff(ticket_id, reason, chat_summary)
                assigned_ticket = await ticket_service.auto_assign_staff(ticket_id)

                logger.info(
                    "Support AI queued ticket for staff with auto-assignment",
                    ticket_id=ticket_id,
                    reason=reason,
                    assigned_staff_id=assigned_ticket.assigned_staff_id,
                    confidence=result["confidence"],
                    is_agent_request=is_agent_request,
                    summary_length=len(chat_summary),
                    stored_ai_solution=True,
                )

            return False

    def _generate_escalation_status_message(self, original_message: str) -> str:
        """
        Generate a customer-facing status message for escalation.
        
        This is a short, honest acknowledgment that the issue has been escalated
        to staff. It does NOT include the AI's technical diagnosis or proposed solution.
        """
        # Detect if the message is in Kiswahili to respond in the same language
        kiswahili_indicators = ["hii", "hiyo", "haya", "naumwa", "tatizo", "haifanyi kazi", "nisaidie"]
        is_kiswahili = any(indicator in original_message.lower() for indicator in kiswahili_indicators)
        
        if is_kiswahili:
            return "Asante kwa maelezo - hii inahitiliangilia zaidi kutoka kwa timu yetu, hivyo nimeirusha kwa mtaalamu. Watafuatilia tiketi hii hivi karibuni."
        else:
            return "Thanks for the details — this needs a closer look from our team, so I've escalated it to a specialist. They'll follow up on this ticket shortly."
