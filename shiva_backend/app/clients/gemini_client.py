from typing import Optional, Dict, Any, List, AsyncIterator
import httpx
import structlog
import json

from app.clients.groq_client import (
    GroqClientInterface,
    ChatMessage,
    LLMResponse,
)
from app.config import settings

logger = structlog.get_logger(__name__)


class GeminiClient(GroqClientInterface):
    """Gemini client implementing GroqClientInterface for complex task handling."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
    ):
        self.api_key = api_key or settings.gemini_api_key
        self.model = model or settings.gemini_model
        self.client = httpx.AsyncClient(
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=60.0,  # Longer timeout for complex reasoning
        )

    async def chat_completion(
        self,
        messages: List[ChatMessage],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        reasoning_effort: Optional[str] = None,
    ) -> LLMResponse:
        """Generate chat completion using Gemini API."""
        model = model or self.model

        try:
            # Convert messages to Gemini format
            # Gemini expects a different format: contents array with role and parts
            contents = []
            for msg in messages:
                if msg.role == "system":
                    # Gemini doesn't have a system role, prepend to first user message
                    continue
                contents.append({
                    "role": msg.role,
                    "parts": [{"text": msg.content}]
                })

            # If there was a system message, prepend it to the first user message
            system_messages = [msg for msg in messages if msg.role == "system"]
            if system_messages and contents:
                contents[0]["parts"][0]["text"] = system_messages[0].content + "\n\n" + contents[0]["parts"][0]["text"]

            payload = {
                "contents": contents,
                "generationConfig": {
                    "temperature": temperature,
                }
            }

            if max_tokens:
                payload["generationConfig"]["maxOutputTokens"] = max_tokens

            response = await self.client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={self.api_key}",
                json=payload,
            )
            response.raise_for_status()

            data = response.json()

            # Extract content from Gemini response
            content = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")

            # Start with high confidence for complex tasks
            confidence = 0.85

            metadata = {
                "provider": "gemini",
                "model": model,
                "temperature": temperature,
            }

            return LLMResponse(
                content=content,
                confidence=confidence,
                metadata=metadata,
            )

        except httpx.HTTPStatusError as e:
            logger.error("Gemini API HTTP error", status_code=e.response.status_code, error=str(e))
            raise
        except Exception as e:
            logger.error("Gemini API error", error=str(e))
            raise

    async def chat_completion_stream(
        self,
        messages: List[ChatMessage],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        reasoning_effort: Optional[str] = None,
    ) -> AsyncIterator[str]:
        """Generate streaming chat completion using Gemini API."""
        model = model or self.model

        try:
            # Convert messages to Gemini format
            contents = []
            for msg in messages:
                if msg.role == "system":
                    continue
                contents.append({
                    "role": msg.role,
                    "parts": [{"text": msg.content}]
                })

            # Handle system message
            system_messages = [msg for msg in messages if msg.role == "system"]
            if system_messages and contents:
                contents[0]["parts"][0]["text"] = system_messages[0].content + "\n\n" + contents[0]["parts"][0]["text"]

            payload = {
                "contents": contents,
                "generationConfig": {
                    "temperature": temperature,
                }
            }

            if max_tokens:
                payload["generationConfig"]["maxOutputTokens"] = max_tokens

            async with self.client.stream(
                "POST",
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:streamGenerateContent?key={self.api_key}",
                json=payload,
            ) as response:
                response.raise_for_status()

                async for line in response.aiter_lines():
                    if line.strip():
                        try:
                            data = json.loads(line)
                            # Extract content from streaming response
                            content = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                            if content:
                                yield content
                        except json.JSONDecodeError:
                            continue

        except httpx.HTTPStatusError as e:
            logger.error("Gemini streaming HTTP error", status_code=e.response.status_code, error=str(e))
            raise
        except Exception as e:
            logger.error("Gemini streaming error", error=str(e))
            raise

    async def should_escalate(
        self,
        message: str,
        response: str,
        kb_context: str,
        conversation_history: List,
        customer_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Determine if conversation should be escalated to human agent using Gemini's advanced reasoning.

        Gemini is particularly good at complex decision-making and understanding nuanced context,
        making it ideal for escalation decisions that require deep analysis of conversation history
        and customer intent.

        Returns:
            Dict with keys:
            - escalate: bool (whether to escalate to human)
            - reason: str (specific reason for escalation decision)
            - confidence: float (0.0-1.0 confidence in the decision)
        """
        system_prompt = """You are a support AI escalation decision system with advanced reasoning capabilities. Your task is to determine if a customer conversation should be escalated to a human agent.

Consider escalating if:
- The AI's solution doesn't address the customer's specific situation
- The customer indicates previous solutions didn't work (e.g., "didn't work", "still failing", "tried that")
- The issue involves security, legal matters, or complex investigations
- The customer is expressing frustration or strong dissatisfaction
- The issue is highly complex and requires human judgment
- The customer explicitly requests to speak to a human
- Multiple AI attempts have failed to resolve the issue
- The conversation shows a pattern of repeated attempts without resolution

Do NOT escalate if:
- The AI provided a clear, actionable solution that addresses the customer's question
- The customer is asking for clarification or additional information
- The issue is straightforward and within the AI's capabilities
- The customer is satisfied with the AI's assistance
- The conversation is just beginning and initial troubleshooting hasn't been attempted

ANALYSIS GUIDELINES:
- Carefully analyze the full conversation history to understand the progression
- Look for patterns that indicate the AI's approach isn't working
- Consider the customer's emotional state and frustration level
- Evaluate whether human judgment is truly needed vs. if AI can continue helping
- Be conservative about escalation but don't hesitate when human intervention is clearly needed
- Remember that escalation should be a last resort after reasonable AI attempts

Respond in JSON format:
{
    "escalate": true/false,
    "reason": "specific reason for the decision",
    "confidence": 0.0-1.0
}"""

        # Build conversation context for Gemini
        context_parts = []
        context_parts.append(f"Current customer message: {message}")
        context_parts.append(f"AI response: {response}")
        
        if kb_context:
            context_parts.append(f"Knowledge base context: {kb_context}")
        
        if conversation_history:
            context_parts.append("Conversation history:")
            for i, msg in enumerate(conversation_history, 1):
                if hasattr(msg, 'role') and hasattr(msg, 'content'):
                    role = msg.role
                    content = msg.content
                elif isinstance(msg, dict):
                    role = msg.get('role', 'unknown')
                    content = msg.get('content', '')
                else:
                    continue
                context_parts.append(f"  {i}. {role}: {content}")
        
        if customer_data:
            context_parts.append(f"Customer data: {customer_data}")

        user_prompt = "\n\n".join(context_parts)

        try:
            messages = [
                ChatMessage(role="system", content=system_prompt),
                ChatMessage(role="user", content=user_prompt)
            ]

            escalation_response = await self.chat_completion(
                messages=messages,
                temperature=0.3,  # Lower temperature for consistent decision-making
                max_tokens=300,
            )

            # Parse JSON response
            import json
            result = json.loads(escalation_response.content)

            return {
                "escalate": result.get("escalate", False),
                "reason": result.get("reason", "Gemini escalation decision"),
                "confidence": result.get("confidence", 0.8),
            }
        except json.JSONDecodeError as e:
            logger.error(
                "Failed to parse Gemini escalation decision as JSON",
                error=str(e),
                response=escalation_response.content if 'escalation_response' in locals() else "unknown",
            )
            # Fallback: conservative approach - escalate if uncertain
            return {
                "escalate": True,
                "reason": "Failed to parse decision, defaulting to escalation for safety",
                "confidence": 0.5,
            }
        except Exception as e:
            logger.error(
                "Error determining escalation with Gemini",
                error=str(e),
                message=message,
            )
            # Fallback: conservative approach - escalate if analysis fails
            return {
                "escalate": True,
                "reason": "Gemini analysis failed, defaulting to escalation for safety",
                "confidence": 0.5,
            }

    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()
