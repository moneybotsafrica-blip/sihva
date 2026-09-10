from typing import Optional, List, Dict, Any
import structlog

from app.clients.qdrant_client import QdrantClientInterface, SearchResult
from app.clients.groq_client import GroqClientInterface, ChatMessage, LLMResponse
from app.ticket_center.service import TicketCenterService
from app.config import settings
from app.common.prompts import LANGUAGE_POLICY, HONESTY_CALIBRATION, VERIFICATION_PROMPT
from app.common.language_check import enforce_language_policy

logger = structlog.get_logger(__name__)


class StaffAIService:
    """Staff AI Assistant service using Groq to help support staff."""

    def __init__(
        self,
        qdrant_client: QdrantClientInterface,
        groq_client: GroqClientInterface,
        confidence_threshold: Optional[float] = None,
    ):
        self.qdrant_client = qdrant_client
        self.groq_client = groq_client
        self.confidence_threshold = confidence_threshold or settings.support_ai_confidence_threshold

    async def assist_staff_response(
        self,
        ticket_id: str,
        staff_query: str,
        ticket_service: TicketCenterService,
    ) -> Dict[str, Any]:
        """
        Provide AI assistance to staff for crafting responses to customers.

        Process:
        1. Retrieve ticket conversation history
        2. Search knowledge base for relevant context
        3. Generate suggested response using Groq
        4. Provide confidence and reasoning

        Returns:
            Dict with keys: suggested_response, confidence, kb_context_used, reasoning
        """
        try:
            # Step 1: Get conversation history
            conversation_history = await ticket_service.get_ticket_messages(ticket_id)

            # Step 2: Search knowledge base
            kb_context = await self._retrieve_knowledge_base_context(staff_query)

            # Step 3: Generate suggested response
            response = await self._generate_staff_assistance(
                staff_query=staff_query,
                conversation_history=conversation_history,
                kb_context=kb_context,
            )

            logger.info(
                "Staff AI assistance generated",
                ticket_id=ticket_id,
                confidence=response.confidence,
                kb_results_count=len(kb_context),
            )

            return {
                "suggested_response": response.content,
                "confidence": response.confidence,
                "kb_context_used": len(kb_context) > 0,
                "reasoning": self._extract_reasoning(response.metadata),
            }

        except Exception as e:
            logger.error(
                "Staff AI assistance failed",
                ticket_id=ticket_id,
                error=str(e),
            )
            return {
                "suggested_response": None,
                "confidence": 0.0,
                "kb_context_used": False,
                "error": str(e),
            }

    async def analyze_ticket_context(
        self,
        ticket_id: str,
        ticket_service: TicketCenterService,
    ) -> Dict[str, Any]:
        """
        Analyze the overall context of a ticket to help staff understand the situation.

        Returns:
            Dict with keys: issue_summary, customer_sentiment, suggested_actions, complexity_score
        """
        try:
            # Get conversation history
            conversation_history = await ticket_service.get_ticket_messages(ticket_id)

            if not conversation_history:
                return {
                    "issue_summary": "No conversation history available",
                    "customer_sentiment": "neutral",
                    "suggested_actions": ["Request more information from customer"],
                    "complexity_score": 0.5,
                }

            # Extract customer messages for analysis
            from app.db.models import MessageSender
            customer_messages = [msg for msg in conversation_history if msg.sender == MessageSender.CUSTOMER]

            if not customer_messages:
                return {
                    "issue_summary": "No customer messages found",
                    "customer_sentiment": "neutral",
                    "suggested_actions": ["Wait for customer response"],
                    "complexity_score": 0.3,
                }

            # Build analysis prompt
            analysis_prompt = self._build_analysis_prompt(customer_messages)

            # Generate analysis using Groq
            messages = [ChatMessage(role="system", content=analysis_prompt)]
            response = await self.groq_client.chat_completion(
                messages=messages,
                temperature=0.3,
                max_tokens=500,
            )

            # Parse the structured response
            analysis = self._parse_analysis_response(response.content)

            logger.info(
                "Ticket context analysis completed",
                ticket_id=ticket_id,
                complexity_score=analysis.get("complexity_score", 0.5),
            )

            return analysis

        except Exception as e:
            logger.error(
                "Ticket context analysis failed",
                ticket_id=ticket_id,
                error=str(e),
            )
            return {
                "issue_summary": "Analysis failed",
                "customer_sentiment": "neutral",
                "suggested_actions": ["Manual review required"],
                "complexity_score": 0.5,
                "error": str(e),
            }

    async def suggest_escalation_path(
        self,
        ticket_id: str,
        current_issue: str,
        ticket_service: TicketCenterService,
    ) -> Dict[str, Any]:
        """
        Suggest whether a ticket should be escalated and to whom.

        Returns:
            Dict with keys: should_escalate, suggested_escalation_target, reasoning, confidence
        """
        try:
            # Get conversation history for context
            conversation_history = await ticket_service.get_ticket_messages(ticket_id)

            # Build escalation analysis prompt
            escalation_prompt = self._build_escalation_prompt(current_issue, conversation_history)

            # Generate escalation recommendation
            messages = [ChatMessage(role="system", content=escalation_prompt)]
            response = await self.groq_client.chat_completion(
                messages=messages,
                temperature=0.2,
                max_tokens=300,
            )

            # Parse escalation recommendation
            escalation = self._parse_escalation_response(response.content)

            logger.info(
                "Escalation path suggestion completed",
                ticket_id=ticket_id,
                should_escalate=escalation.get("should_escalate", False),
            )

            return escalation

        except Exception as e:
            logger.error(
                "Escalation path suggestion failed",
                ticket_id=ticket_id,
                error=str(e),
            )
            return {
                "should_escalate": False,
                "suggested_escalation_target": None,
                "reasoning": "Analysis failed, recommend manual review",
                "confidence": 0.0,
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
            query_vector = await self.qdrant_client.embed_text(query)
            threshold = score_threshold or settings.qdrant_similarity_threshold

            results = await self.qdrant_client.search(
                query_vector=query_vector,
                limit=max_results,
                score_threshold=threshold,
            )

            logger.debug(
                "Retrieved KB context for staff assistance",
                query_length=len(query),
                results_count=len(results),
            )

            return results

        except Exception as e:
            logger.error(
                "Failed to retrieve KB context for staff",
                error=str(e),
            )
            return []

    async def _generate_staff_assistance(
        self,
        staff_query: str,
        conversation_history: List,
        kb_context: List[SearchResult],
    ) -> LLMResponse:
        """Generate suggested response for staff using Groq LLM."""

        # Build system prompt for staff assistance
        system_prompt = self._build_staff_assistant_prompt(kb_context, conversation_history)

        # Build messages
        messages = [ChatMessage(role="system", content=system_prompt)]
        messages.append(ChatMessage(role="user", content=staff_query))

        # Generate response
        response = await self.groq_client.chat_completion(
            messages=messages,
            temperature=0.4,  # Balanced creativity for staff assistance
            max_tokens=800,
        )

        # Enforce language policy on staff-facing responses
        response.content = enforce_language_policy(response.content, staff_query)

        logger.debug(
            "Generated staff assistance response",
            confidence=response.confidence,
            response_length=len(response.content),
        )

        return response

    def _build_staff_assistant_prompt(
        self,
        kb_context: List[SearchResult],
        conversation_history: List,
    ) -> str:
        """Build system prompt for staff assistance."""

        prompt_parts = [
            "You are an AI assistant helping support staff craft responses to customers.",
            "Your role is to provide helpful, professional, and accurate response suggestions.",
            "",
            "IMPORTANT RULES:",
            "- Provide responses that are empathetic, clear, and actionable",
            "- Use the knowledge base context when available to ensure accuracy",
            "- Consider the conversation history to maintain context",
            "- Suggest responses that resolve the customer's issue efficiently",
            "- If the issue is complex, break it down into clear steps",
            "- Always maintain a professional and helpful tone",
            "",
            HONESTY_CALIBRATION,
            "",
            VERIFICATION_PROMPT,
            "",
            LANGUAGE_POLICY,
            "",
        ]

        # Add conversation context
        if conversation_history:
            prompt_parts.extend([
                "CONVERSATION HISTORY:",
                "-------------------",
            ])
            from app.db.models import MessageSender
            for msg in conversation_history[-5:]:  # Last 5 messages
                sender_name = "Customer" if msg.sender == MessageSender.CUSTOMER else "Support"
                prompt_parts.append(f"{sender_name}: {msg.content[:100]}...")
            prompt_parts.append("-------------------")

        # Add knowledge base context
        if kb_context:
            prompt_parts.extend([
                "KNOWLEDGE BASE CONTEXT:",
                "-------------------",
            ])
            for i, result in enumerate(kb_context, 1):
                prompt_parts.extend([
                    f"Document {i} (confidence: {result.score:.2f}):",
                    result.content[:200],  # Truncate for context
                    "",
                ])
            prompt_parts.append("-------------------")
        else:
            prompt_parts.append("No specific knowledge base context found for this query.")

        prompt_parts.extend([
            "",
            "Based on the above context, provide a suggested response for the staff member.",
            "Format your response as a direct, professional message that can be sent to the customer.",
        ])

        return "\n".join(prompt_parts)

    def _build_analysis_prompt(self, customer_messages: List) -> str:
        """Build prompt for ticket context analysis (internal classifier - not shown to staff)."""

        conversation_text = "\n".join([f"- {msg.content}" for msg in customer_messages])

        prompt = f"""Analyze the following customer messages and provide a structured assessment.

CONVERSATION:
{conversation_text}

Provide your analysis in the following format:
ISSUE_SUMMARY: [Brief summary of the customer's issue]
CUSTOMER_SENTIMENT: [positive/neutral/negative/frustrated]
SUGGESTED_ACTIONS: [2-3 specific actions for staff to take]
COMPLEXITY_SCORE: [0.0 to 1.0, where 1.0 is most complex]"""

        return prompt

    def _build_escalation_prompt(self, current_issue: str, conversation_history: List) -> str:
        """Build prompt for escalation analysis (internal classifier - not shown to staff)."""

        history_text = "\n".join([f"- {msg.content[:100]}" for msg in conversation_history[-3:]])

        prompt = f"""Analyze whether this ticket should be escalated to a higher level of support.

CURRENT ISSUE: {current_issue}

RECENT CONVERSATION:
{history_text}

Consider:
- Has the issue been unresolved for multiple attempts?
- Does it require specialized technical knowledge?
- Is it a billing/account issue that needs specific authority?
- Is the customer showing signs of extreme frustration?

Provide your recommendation in this format:
SHOULD_ESCALATE: [true/false]
SUGGESTED_ESCALATION_TARGET: [none/technical_lead/billing_specialist/manager]
REASONING: [Brief explanation of why or why not]
CONFIDENCE: [0.0 to 1.0]"""

        return prompt

    def _parse_analysis_response(self, response_content: str) -> Dict[str, Any]:
        """Parse the structured analysis response from Groq."""
        analysis = {
            "issue_summary": "Unable to parse",
            "customer_sentiment": "neutral",
            "suggested_actions": ["Manual review required"],
            "complexity_score": 0.5,
        }

        try:
            lines = response_content.split('\n')
            for line in lines:
                line = line.strip()
                if line.startswith("ISSUE_SUMMARY:"):
                    analysis["issue_summary"] = line.replace("ISSUE_SUMMARY:", "").strip()
                elif line.startswith("CUSTOMER_SENTIMENT:"):
                    analysis["customer_sentiment"] = line.replace("CUSTOMER_SENTIMENT:", "").strip().lower()
                elif line.startswith("SUGGESTED_ACTIONS:"):
                    actions_text = line.replace("SUGGESTED_ACTIONS:", "").strip()
                    analysis["suggested_actions"] = [action.strip() for action in actions_text.split(',') if action.strip()]
                elif line.startswith("COMPLEXITY_SCORE:"):
                    score_text = line.replace("COMPLEXITY_SCORE:", "").strip()
                    try:
                        analysis["complexity_score"] = float(score_text)
                    except ValueError:
                        pass
        except Exception as e:
            logger.error("Failed to parse analysis response", error=str(e))

        return analysis

    def _parse_escalation_response(self, response_content: str) -> Dict[str, Any]:
        """Parse the structured escalation response from Groq."""
        escalation = {
            "should_escalate": False,
            "suggested_escalation_target": None,
            "reasoning": "Unable to parse recommendation",
            "confidence": 0.0,
        }

        try:
            lines = response_content.split('\n')
            for line in lines:
                line = line.strip()
                if line.startswith("SHOULD_ESCALATE:"):
                    should_escalate_text = line.replace("SHOULD_ESCALATE:", "").strip().lower()
                    escalation["should_escalate"] = should_escalate_text in ["true", "yes", "1"]
                elif line.startswith("SUGGESTED_ESCALATION_TARGET:"):
                    target = line.replace("SUGGESTED_ESCALATION_TARGET:", "").strip()
                    escalation["suggested_escalation_target"] = target if target.lower() != "none" else None
                elif line.startswith("REASONING:"):
                    escalation["reasoning"] = line.replace("REASONING:", "").strip()
                elif line.startswith("CONFIDENCE:"):
                    confidence_text = line.replace("CONFIDENCE:", "").strip()
                    try:
                        escalation["confidence"] = float(confidence_text)
                    except ValueError:
                        pass
        except Exception as e:
            logger.error("Failed to parse escalation response", error=str(e))

        return escalation

    def _extract_reasoning(self, metadata: Optional[Dict[str, Any]]) -> str:
        """Extract reasoning from response metadata if available."""
        if metadata and "reasoning" in metadata:
            return metadata["reasoning"]
        return "Generated using Groq LLM with knowledge base context"