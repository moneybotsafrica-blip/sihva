from typing import Optional, List, Dict, Any, TYPE_CHECKING
from datetime import datetime
import structlog

from app.clients.qdrant_client import QdrantClientInterface, SearchResult
from app.clients.groq_client import GroqClientInterface, ChatMessage, LLMResponse
from app.clients.customer_api import CustomerApiClientInterface, CustomerAccount
from app.ticket_center.service import TicketCenterService
from app.config import settings
from app.db.models import MessageSender

if TYPE_CHECKING:
    from app.db.models import TicketMessage

logger = structlog.get_logger(__name__)


class SupportAIService:
    """Support AI service using RAG with Qdrant and Groq."""

    def __init__(
        self,
        qdrant_client: QdrantClientInterface,
        groq_client: GroqClientInterface,
        customer_api_client: CustomerApiClientInterface,
        confidence_threshold: Optional[float] = None,
    ):
        self.qdrant_client = qdrant_client
        self.groq_client = groq_client
        self.customer_api_client = customer_api_client
        self.confidence_threshold = confidence_threshold or settings.support_ai_confidence_threshold

    async def handle_customer_message(
        self,
        ticket_id: str,
        customer_id: str,
        message: str,
        ticket_service: Optional[TicketCenterService],
        is_agent_request: bool = False,
        conversation_history: Optional[List] = None,
    ) -> Dict[str, Any]:
        """
        Handle a customer message through the Support AI pipeline.

        Process:
        1. Retrieve conversation history (or use provided)
        2. Retrieve customer account info
        3. Search knowledge base for relevant context
        4. Check if issue is complex (if agent request)
        5. Generate response using Groq LLM
        6. Based on confidence and complexity, either auto-respond or queue for staff

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
                # Convert conversation history to the expected format if it's a list of dicts
                if conversation_history and isinstance(conversation_history[0], dict):
                    # Convert dict format to object format expected by the system
                    from collections import namedtuple
                    TicketMessageLike = namedtuple('TicketMessageLike', ['id', 'ticket_id', 'sender', 'content', 'attachments', 'created_at'])
                    conversation_history = [
                        TicketMessageLike(
                            id=msg.get('id', 'temp_id'),
                            ticket_id='temp_ticket',
                            sender=msg.get('sender', 'customer'),
                            content=msg.get('content', ''),
                            attachments=msg.get('attachments'),
                            created_at=datetime.fromisoformat(msg.get('created_at', datetime.now().isoformat())) if msg.get('created_at') else datetime.now()
                        )
                        for msg in conversation_history
                    ]

            # Step 2: Get customer account info
            try:
                customer_account = await self.customer_api_client.get_account(customer_id)
            except Exception as e:
                logger.warning(f"Failed to get customer account: {e}")
                customer_account = None

            # Step 3: Search knowledge base
            kb_context = await self._retrieve_knowledge_base_context(message)

            # Step 4: Check every request for complexity.  A customer should not
            # have to explicitly request an agent before a clearly complex issue
            # is routed to staff.
            complexity_analysis = await self._analyze_complexity(
                message=message,
                kb_context=kb_context,
                conversation_history=conversation_history,
            )

            # Step 5: Generate response
            response = await self._generate_response(
                message=message,
                conversation_history=conversation_history,
                customer_account=customer_account,
                kb_context=kb_context,
                is_agent_request=is_agent_request,
            )

            # Step 6: Validate solution completeness
            solution_validation = self._validate_solution_completeness(
                response.content, 
                kb_context, 
                message
            )
            
            # Step 7: Determine action based on confidence, complexity, and solution quality
            should_queue = False
            action = "auto_resolve"

            # Check for out-of-scope messages using Groq AI classification
            is_out_of_scope = await self._is_out_of_scope_groq(message)
            if is_out_of_scope:
                logger.info("Out-of-scope message detected - will provide scope-appropriate response")
                # Don't create tickets for out-of-scope messages
                should_queue = False
                action = "out_of_scope"
                
                # Generate a helpful out-of-scope response
                out_of_scope_response = "I am here to help with any Shiva-related questions or issues you might have—feel free to ask about your account, service, payments, or anything else Shivasoftwares! What can I assist with today?"
                
                return {
                    "action": action,
                    "response": out_of_scope_response,
                    "confidence": 0.0,
                    "should_queue": should_queue,
                    "kb_context_used": False,
                    "complexity_analysis": complexity_analysis,
                }

            # Check for simple greetings - never escalate these
            simple_greetings = ["hi", "hello", "hey", "good morning", "good afternoon", "good evening", "thanks", "thank you", "bye", "goodbye"]
            is_simple_greeting = any(greeting in message.lower() for greeting in simple_greetings)

            if is_simple_greeting:
                logger.info("Simple greeting detected - auto-resolving without escalation")
                should_queue = False
                action = "auto_resolve"
            else:
                # NEW APPROACH: Always try to provide a solution first
                # Only escalate if this is a follow-up message indicating previous solution failed
                solution_failed = self._detect_solution_failure(conversation_history, message)

                # Check if this is a follow-up after an AI provided solution
                previous_ai_attempts = [msg for msg in conversation_history if msg.sender == MessageSender.SUPPORT_AI]
                is_follow_up = len(previous_ai_attempts) > 0

                # Escalate only when:
                # 1. Previous solution failed (customer indicates it didn't work)
                # 2. Staff-only issues (security, legal, complex investigations)
                # 3. Multiple failed attempts (customer has tried multiple AI solutions)
                # 4. Issue is complex (not in knowledge base, requires investigation)
                # 5. Explicit agent/human request (customer insists on speaking to human)
                staff_only_indicators = [
                    "charged twice", "unauthorized charge", "refund missing",
                    "account locked", "account hacked", "security breach", "data loss",
                    "legal", "complaint", "production down", "server error", "500"
                ]
                has_staff_only_issue = any(indicator in message.lower() for indicator in staff_only_indicators)
                
                # Check for explicit agent/human requests
                agent_request_indicators = [
                    "talk to agent", "speak to agent", "human agent", "real person",
                    "talk to human", "speak to human", "agent please", "human please",
                    "customer service", "support team", "real agent", "live agent",
                    "escalate", "escalation", "manager", "supervisor"
                ]
                has_agent_request = any(indicator in message.lower() for indicator in agent_request_indicators)

                multiple_failed_attempts = len(previous_ai_attempts) >= 2 and solution_failed

                # Debug logging
                logger.debug(
                    "Escalation decision factors",
                    solution_failed=solution_failed,
                    has_staff_only_issue=has_staff_only_issue,
                    multiple_failed_attempts=multiple_failed_attempts,
                    has_agent_request=has_agent_request,
                    previous_ai_attempts=len(previous_ai_attempts),
                    is_follow_up=is_follow_up,
                    complexity_analysis=complexity_analysis,
                )

                if solution_failed or has_staff_only_issue or multiple_failed_attempts or has_agent_request or complexity_analysis.get("is_complex"):
                    should_queue = True
                    action = "queue_for_staff"

                    if solution_failed:
                        logger.info(
                            "Previous solution failed - escalating to staff",
                            ticket_id=ticket_id,
                            previous_attempts=len(previous_ai_attempts),
                        )
                    elif has_staff_only_issue:
                        logger.info(
                            "Staff-only issue detected - escalating to staff",
                            ticket_id=ticket_id,
                        )
                    elif multiple_failed_attempts:
                        logger.info(
                            "Multiple failed solution attempts - escalating to staff",
                            ticket_id=ticket_id,
                            attempts=len(previous_ai_attempts),
                        )
                    elif has_agent_request:
                        logger.info(
                            "Explicit agent request detected - escalating to staff",
                            ticket_id=ticket_id,
                        )
                    elif complexity_analysis.get("is_complex"):
                        logger.info(
                            "Complex issue detected - escalating to staff",
                            ticket_id=ticket_id,
                            complexity_score=complexity_analysis.get("complexity_score"),
                            reasons=complexity_analysis.get("reasons"),
                        )

            logger.info(
                "Support AI processed message",
                ticket_id=ticket_id,
                confidence=response.confidence,
                action=action,
                kb_results_count=len(kb_context),
                is_agent_request=is_agent_request,
            )

            # Use the appropriate response based on action
            final_response = response.content if action != "out_of_scope" else response
            
            return {
                "action": action,
                "response": response.content,
                "confidence": response.confidence,
                "should_queue": should_queue,
                "kb_context_used": len(kb_context) > 0,
                "complexity_analysis": complexity_analysis,
            }

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
            }

    async def _retrieve_knowledge_base_context(
        self,
        query: str,
        max_results: int = 5,
        score_threshold: Optional[float] = None,
    ) -> List[SearchResult]:
        """Retrieve relevant context from knowledge base."""
        try:
            # Embed the query
            query_vector = await self.qdrant_client.embed_text(query)
            
            # Use provided threshold or default to settings
            threshold = score_threshold or settings.qdrant_similarity_threshold
            
            # Search for similar documents
            results = await self.qdrant_client.search(
                query_vector=query_vector,
                limit=max_results,
                score_threshold=threshold,
            )
            
            logger.debug(
                "Retrieved KB context",
                query_length=len(query),
                results_count=len(results),
                threshold=threshold,
            )
            
            return results
            
        except Exception as e:
            logger.error(
                "Failed to retrieve KB context",
                error=str(e),
            )
            return []

    async def _generate_response(
        self,
        message: str,
        conversation_history: List["TicketMessage"],
        customer_account: Optional[CustomerAccount],
        kb_context: List[SearchResult],
        is_agent_request: bool = False,
    ) -> LLMResponse:
        """Generate response using Groq LLM with RAG context."""
        
        # Build system prompt
        system_prompt = self._build_system_prompt(kb_context, customer_account, is_agent_request)
        
        # Build conversation messages
        messages = [ChatMessage(role="system", content=system_prompt)]

        # Add conversation history (last 10 messages to avoid context overflow)
        recent_history = conversation_history[-10:] if len(conversation_history) > 10 else conversation_history
        for msg in recent_history:
            # Determine role based on sender (works for both TicketMessage and ChatMessage)
            role = "user" if msg.sender == MessageSender.CUSTOMER else "assistant"
            messages.append(ChatMessage(role=role, content=msg.content))
        
        # Add current message
        messages.append(ChatMessage(role="user", content=message))
        
        # Generate response with higher token limit for detailed solutions
        response = await self.groq_client.chat_completion(
            messages=messages,
            temperature=0.2,  # Even lower temperature for more consistent, actionable responses
            max_tokens=1500,  # Higher token limit for more detailed solutions
        )
        
        # Enhance confidence calculation based on solution quality
        enhanced_confidence = self._enhance_confidence_calculation(
            response.content, 
            kb_context, 
            response.confidence
        )
        
        response.confidence = enhanced_confidence
        
        logger.debug(
            "Generated Support AI response",
            original_confidence=response.confidence,
            enhanced_confidence=enhanced_confidence,
            response_length=len(response.content),
            kb_context_count=len(kb_context),
        )
        
        return response

    def _enhance_confidence_calculation(
        self,
        response_content: str,
        kb_context: List[SearchResult],
        original_confidence: float
    ) -> float:
        """
        Enhance confidence calculation based on solution quality indicators.
        
        This analyzes the response to ensure it provides actionable solutions
        rather than just information.
        """
        if not response_content:
            return 0.0
        
        response_lower = response_content.lower()
        enhanced_confidence = original_confidence
        
        # Positive indicators that increase confidence
        positive_indicators = [
            "step", "follow", "click", "go to", "navigate", "select",
            "first", "then", "next", "after", "finally", "complete",
            "solution", "fix", "resolve", "should", "can", "will"
        ]
        
        # Check for step-by-step format
        step_count = 0
        for indicator in positive_indicators:
            if indicator in response_lower:
                step_count += 1
        
        # Bonus for structured solutions
        if step_count >= 3:
            enhanced_confidence += 0.1  # Strong step-by-step structure
        elif step_count >= 1:
            enhanced_confidence += 0.05  # Some actionable content
        
        # Check for specific actionable elements
        actionable_elements = [
            "settings", "button", "menu", "tab", "page", "link",
            "option", "field", "form", "account", "profile"
        ]
        actionable_count = sum(1 for element in actionable_elements if element in response_lower)
        if actionable_count >= 2:
            enhanced_confidence += 0.05  # Contains specific UI elements
        
        # Check for verification steps (shows completeness)
        verification_indicators = [
            "verify", "check", "confirm", "ensure", "make sure",
            "test", "try", "should see", "will appear"
        ]
        if any(indicator in response_lower for indicator in verification_indicators):
            enhanced_confidence += 0.05  # Includes verification steps
        
        # Check for alternative solutions (shows robustness)
        if "alternatively" in response_lower or "or" in response_lower and "if" in response_lower:
            enhanced_confidence += 0.03  # Provides alternatives
        
        # Negative indicators that decrease confidence
        negative_indicators = [
            "might", "maybe", "possibly", "probably", "should work",
            "try to", "i think", "not sure", "unclear", "unsure"
        ]
        if any(indicator in response_lower for indicator in negative_indicators):
            enhanced_confidence -= 0.1  # Uncertain language
        
        # Check for incomplete solutions
        incomplete_indicators = [
            "contact support", "reach out", "speak to", "cannot help",
            "not available", "don't have information", "unable to"
        ]
        if any(indicator in response_lower for indicator in incomplete_indicators):
            enhanced_confidence -= 0.15  # Escalation without solution
        
        # Check for knowledge base quality
        if kb_context:
            avg_kb_score = sum(result.score for result in kb_context) / len(kb_context)
            if avg_kb_score >= 0.8:
                enhanced_confidence += 0.05  # High-quality KB matches
            elif avg_kb_score < 0.5:
                enhanced_confidence -= 0.1  # Low-quality KB matches
        
        # Ensure confidence stays within valid range
        enhanced_confidence = max(0.0, min(1.0, enhanced_confidence))
        
        logger.debug(
            "Enhanced confidence calculation",
            original_confidence=original_confidence,
            enhanced_confidence=enhanced_confidence,
            step_count=step_count,
            actionable_count=actionable_count,
        )
        
        return enhanced_confidence

    async def _is_out_of_scope_groq(self, message: str) -> bool:
        """
        Use Groq API to intelligently determine if a message is out of scope for Shiva AI Platform support.
        
        This is more accurate than keyword matching as it understands context and nuance.
        """
        try:
            # Use Groq to classify if the message is in-scope
            classification_prompt = f"""Classify if this customer message is IN-SCOPE or OUT-OF-SCOPE for Shiva AI Platform customer support.

IN-SCOPE messages relate to:
- Account access (login, password, account locked)
- Billing and payments (payment failed, card declined, refund)
- Technical issues (errors, bugs, integration problems)
- Platform features and usage (dashboard, API, specific functionality)
- Subscription management (plans, upgrades, cancellations)

OUT-OF-SCOPE messages include:
- Personal feelings/emotions (bored, tired, happy, sad)
- Casual conversation (how are you, nice to meet you)
- Entertainment requests (jokes, games, movies)
- General questions unrelated to Shiva AI Platform
- Personal life matters

Customer message: "{message}"

Respond with ONLY "IN-SCOPE" or "OUT-OF-SCOPE" (no explanation needed)."""

            classification_response = await self.groq_client.chat_completion(
                messages=[ChatMessage(role="user", content=classification_prompt)],
                temperature=0.1,  # Low temperature for consistent classification
                max_tokens=10,   # Only need classification result
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

    def _is_out_of_scope(self, message: str) -> bool:
        """
        Fallback method: Detect if a message is out of scope using keyword matching.
        Only used if Groq classification fails.
        """
        message_lower = message.lower()
        
        # Out-of-scope indicators
        out_of_scope_indicators = [
            "bored", "boring", "im bored", "feel bored",
            "tired", "im tired", "exhausted", "sleepy",
            "hungry", "thirsty", "im hungry", "im thirsty",
            "happy", "sad", "angry", "excited", "scared", "worried",
            "love", "hate", "like", "dislike",
            "funny", "joke", "laugh", "humor",
            "game", "play", "movie", "music", "song",
            "weather", "temperature", "raining", "sunny",
            "how are you", "how do you do", "whats up", "sup",
            "nice to meet you", "hello there", "hey there",
            "friend", "friendship", "relationship",
            "life", "my life", "personal", "my personal",
            "opinion", "what do you think", "do you think",
            "advice", "give me advice", "need advice",
            "recommend", "recommendation", "suggest something",
            "random", "random question", "just asking",
            "curious", "just curious", "wondering",
            "tell me about", "tell me something", "can you tell me",
            "interesting", "interesting fact", "fun fact",
            "conversation", "chat", "talk", "just talking",
            "free time", "spare time", "killing time",
            "nothing to do", "have nothing to do", "nothing"
        ]
        
        # Check for out-of-scope indicators
        for indicator in out_of_scope_indicators:
            if indicator in message_lower:
                logger.debug(
                    "Out-of-scope message detected (fallback)",
                    indicator=indicator,
                )
                return True
        
        # Check if message is very short and doesn't contain platform-related terms
        platform_keywords = [
            "account", "login", "password", "billing", "payment", "card",
            "subscription", "plan", "upgrade", "downgrade", "cancel",
            "error", "bug", "issue", "problem", "help", "support",
            "shiva", "platform", "ai", "feature", "dashboard", "api",
            "integration", "code", "development", "deployment", "server"
        ]
        
        has_platform_keyword = any(keyword in message_lower for keyword in platform_keywords)
        
        # If message is short (<15 chars) and has no platform keywords, it's likely out of scope
        if len(message) < 15 and not has_platform_keyword:
            logger.debug(
                "Short message without platform keywords detected as out of scope (fallback)",
                message_length=len(message),
            )
            return True
        
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
        previous_ai_messages = [msg for msg in conversation_history if msg.sender == MessageSender.SUPPORT_AI]
        if not previous_ai_messages:
            return False
        
        # Check if current message contains similar keywords to initial problem
        # but after AI has already provided a solution
        if len(previous_ai_messages) >= 1:
            # Get the initial customer message
            initial_customer_msg = None
            for msg in conversation_history:
                if msg.sender == MessageSender.CUSTOMER:
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

    def _build_system_prompt(
        self,
        kb_context: List[SearchResult],
        customer_account: Optional[CustomerAccount],
        is_agent_request: bool = False,
    ) -> str:
        """Build system prompt with RAG context and customer info."""
        
        prompt_parts = [
            "You are a helpful customer support AI assistant for Shiva AI Platform.",
            "Your role is to provide actionable, working solutions to customer issues based on the provided knowledge base context.",
            "",
            "SCOPE CONTEXT:",
            "- This message has been pre-classified as relevant to Shiva AI Platform support.",
            "- Focus on helping with: account access, billing, payments, technical errors, product features, platform usage.",
            "- Provide practical solutions based on the knowledge base context provided below.",
            "",
            "CRITICAL APPROACH: SOLUTION-FIRST POLICY",
            "- ALWAYS provide a solution first, even if you're not 100% certain it will work",
            "- Give customers something they can try immediately rather than escalating immediately",
            "- Only mention escalation if the customer indicates the solution didn't work",
            "- Your primary goal is to be helpful and reduce customer frustration",
            "",
            "CRITICAL ROUTING RULE:",
            "- When relevant knowledge-base context is supplied, answer only from that context and give the customer a complete solution.",
            "- Do not invent product behavior, account data, policies, URLs, or troubleshooting steps that are absent from the knowledge base.",
            "- If the request is complex, account-specific, security-sensitive, or not covered by the supplied context, do not pretend it is solved; it will be routed to a staff member.",
            "",
            "CRITICAL RULES FOR PREVENTING USER FRUSTRATION:",
            "- Give customers a concise solution they can use immediately when the knowledge base supports it",
            "- Focus on being helpful and supportive rather than avoiding mistakes",
            "- If information is incomplete, provide the best possible solution based on available context",
            "- Ask the customer to try the solution and report back if it doesn't work",
            "- Provide multiple options when possible so customers have choices",
            "- Include troubleshooting tips for common issues that might occur",
            "- NEVER apologize or say 'I'm sorry' - be direct and solution-focused",
            "- NEVER show confidence scores or technical metrics to customers",
            "",
            "OUT-OF-SCOPE RESPONSE:",
            "- If a customer asks about topics outside Shiva AI Platform support (weather, sports, entertainment, personal advice, etc.), respond with: 'I am here to help with any Shiva-related questions or issues you might have—feel free to ask about your account, service, payments, or anything else Shivasoftwares! What can I assist with today?'",
            "- Do not provide information about topics unrelated to Shiva AI Platform",
            "",
            "CRITICAL RULES FOR PROVIDING WORKING SOLUTIONS:",
            "- Provide step-by-step, actionable instructions that customers can follow immediately",
            "- Include specific paths, button names, and exact text the customer should look for",
            "- If suggesting a solution, verify it's complete and actionable",
            "- Include troubleshooting steps if the solution might not work on first try",
            "- Provide alternative solutions if the primary solution might fail",
            "- Include relevant warnings or common mistakes to avoid",
            "- If the solution requires specific customer information (account type, plan, etc.), reference it",
            "- ALWAYS end with: 'Please try this solution and let me know if it works or if you need further assistance.'",
            "",
            "KNOWLEDGE BASE USAGE:",
            "- Use the provided knowledge base context as your primary source",
            "- If the context doesn't contain a complete solution, provide the best partial solution available",
            "- Combine information from multiple knowledge base documents if needed",
            "- If information is missing, acknowledge this but still provide helpful guidance",
            "- Never make up information, but always try to be helpful with what you know",
            "",
            "RESPONSE STRUCTURE:",
            "- Start with **Solution** and a one-sentence outcome.",
            "- Use clear section headers with **bold** formatting",
            "- Provide clear, numbered steps for any solution",
            "- Include what to expect at each step",
            "- End with how to verify the solution worked",
            "- Always provide alternatives or next steps if the primary solution might fail",
            "- Include contact information as a LAST resort, not the first option",
            "- DO NOT include confidence scores, error messages, or technical details",
            "- Format responses with clear hierarchy: Main solution → Steps → Verification → Alternatives",
            "- ALWAYS ask customer to try the solution and report back",
            "",
            "CONFIDENCE GUIDELINES:",
            "- High confidence (0.8+): Solution is complete, actionable, and from reliable sources",
            "- Medium confidence (0.6-0.8): Solution is likely correct but may need verification",
            "- Low confidence (<0.6): Information is incomplete but still provide helpful guidance",
            "- Even with low confidence, give customers actionable steps they can try",
            "- Keep all confidence calculations internal - never show them to customers",
            "",
        ]

        # Add special instructions for agent requests
        if is_agent_request:
            prompt_parts.extend([
                "SPECIAL INSTRUCTIONS FOR AGENT REQUESTS:",
                "- The customer requested to speak to a human agent.",
                "- However, if the issue is simple and well-documented in the knowledge base,",
                "  provide the complete solution and explain that you can handle this.",
                "- Only escalate to staff if the issue is truly complex or not in the knowledge base.",
                "- Be empathetic but efficient - don't escalate unnecessarily.",
                "",
            ])
        
        # Add knowledge base context
        if kb_context:
            prompt_parts.extend([
                "KNOWLEDGE BASE CONTEXT:",
                "-------------------",
            ])
            for i, result in enumerate(kb_context, 1):
                prompt_parts.extend([
                    f"Document {i} (relevance: {result.score:.2f}):",
                    result.content,
                    "",
                ])
            prompt_parts.append("-------------------")
        else:
            prompt_parts.append("No relevant knowledge base context found for this query.")
        
        # Add customer context
        if customer_account:
            prompt_parts.extend([
                "",
                "CUSTOMER CONTEXT:",
                f"- Customer ID: {customer_account.customer_id}",
                f"- Name: {customer_account.name}",
                f"- Email: {customer_account.email}",
                f"- Plan: {customer_account.plan}",
                "- Use this information to tailor your response to their specific situation",
            ])
        
        prompt_parts.extend([
            "",
            "Based on the above context, provide a complete, actionable solution to the customer's issue.",
            "Focus on giving them steps they can take right now to solve their problem.",
        ])
        
        return "\n".join(prompt_parts)

    async def _analyze_complexity(
        self,
        message: str,
        kb_context: List[SearchResult],
        conversation_history: List,
    ) -> Dict[str, Any]:
        """
        Analyze if an issue is complex enough to require human intervention.

        Optimized to reduce false escalations and maximize AI resolution rate.

        Complexity factors:
        1. No knowledge base match (issue not documented) - lowered weight
        2. Long conversation history (multiple failed attempts) - increased threshold
        3. Emotional language (frustration indicators) - kept
        4. Multiple topics/issues in one message - kept
        5. Account-specific issues (billing, plan changes, etc.) - lowered weight

        Returns:
            Dict with keys: is_complex, complexity_score, reasons
        """
        complexity_score = 0.0
        reasons = []

        # Factor 1: No knowledge base match. Issues not in knowledge base should be escalated
        # as they may require investigation or specialized knowledge.
        if not kb_context:
            complexity_score += 0.7  # Increased from 0.25 to ensure escalation for unknown issues
            reasons.append("No knowledge base match - issue not documented, requires human investigation")

        # Factor 2: Long conversation history (increased threshold from 5 to 8)
        if len(conversation_history) > 8:
            complexity_score += 0.3
            reasons.append(f"Long conversation history ({len(conversation_history)} messages)")

        # Factor 3: Emotional language (frustration indicators) - kept
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

        # Factor 4: Multiple topics/issues in one message - kept
        topic_indicators = ["and", "also", "plus", "another", "additionally"]
        topic_count = sum(1 for indicator in topic_indicators if indicator in message_lower)
        if topic_count >= 2:
            complexity_score += 0.15
            reasons.append("Multiple topics/issues detected in message")

        # Factor 5: Account-specific issues (lowered from 0.1 to 0.05)
        # Removed generic terms like "payment", "account" that don't indicate complexity
        account_keywords = [
            "billing", "invoice", "charge", "refund",
            "plan", "subscription", "upgrade", "downgrade", "cancel",
            "profile", "settings", "user"
        ]
        for keyword in account_keywords:
            if keyword in message_lower:
                complexity_score += 0.05
                reasons.append(f"Account-specific issue: '{keyword}'")
                break

        # Factor 6: Issues that require investigation or a staff-controlled
        # action. These cannot be safely resolved from general KB instructions.
        # However, if KB content exists for payment issues, allow AI to handle them.
        staff_only_indicators = [
            "charged twice", "unauthorized charge", "refund missing",
            "account locked", "account hacked", "security breach", "data loss",
            "cannot access", "outage", "production down", "server error", "500",
            "bug report", "integration failing", "api error", "legal", "complaint",
            "security vulnerability", "security issue", "security report", "vulnerability",
            "hack", "breach", "compromise", "exploit", "attack"
        ]
        
        # Payment-related issues that can be handled with good KB content
        payment_troubleshooting_indicators = ["payment failed", "payment declined", "card declined"]
        
        for indicator in staff_only_indicators:
            if indicator in message_lower:
                complexity_score += 0.65
                reasons.append(f"Requires staff investigation: '{indicator}'")
                break
        
        # Special handling for payment issues: only escalate if KB content is poor
        for indicator in payment_troubleshooting_indicators:
            if indicator in message_lower:
                # Check if we have good KB content for payment troubleshooting
                has_payment_kb = any(
                    "payment" in result.content.lower() and result.score >= 0.7
                    for result in kb_context
                )
                
                if not has_payment_kb:
                    complexity_score += 0.4
                    reasons.append(f"Payment issue without KB guidance: '{indicator}'")
                else:
                    # Good KB content exists, let AI handle it
                    complexity_score += 0.1  # Small increase for payment complexity
                    reasons.append(f"Payment issue with KB support: '{indicator}'")
                break

        # A staff-only signal is intentionally enough to escalate immediately;
        # otherwise require several signals to avoid routing ordinary KB questions.
        # Lowered threshold to 0.6 to ensure unknown issues (0.7 score) are escalated
        is_complex = complexity_score >= 0.6

        logger.debug(
            "Complexity analysis completed",
            complexity_score=complexity_score,
            is_complex=is_complex,
            reasons=reasons,
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
            "=== CUSTOMER ISSUE ANALYSIS ===",
        ]

        # Get customer's initial message and classify the issue
        if conversation_history:
            first_message = conversation_history[0]
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

        # Count messages by sender
        customer_messages = [m for m in conversation_history if m.sender == MessageSender.CUSTOMER]
        ai_messages = [m for m in conversation_history if m.sender == MessageSender.SUPPORT_AI]
        system_messages = [m for m in conversation_history if m.sender == MessageSender.SYSTEM]

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
            summary_parts.append(f"Final AI Response: {last_ai_response.content[:200]}...")
            
            # Check if AI provided incomplete solution
            if len(ai_messages) > 1:
                summary_parts.append("Note: Multiple AI attempts suggest incomplete or unclear guidance provided.")
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

                # Store AI confidence before auto-resolving
                await ticket_service.store_ai_confidence(ticket_id, result["confidence"])

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
                )

            return False
