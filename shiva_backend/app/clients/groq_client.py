from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List, AsyncIterator
from dataclasses import dataclass
import httpx
import structlog
import json

from app.config import settings

logger = structlog.get_logger(__name__)


@dataclass
class ChatMessage:
    """Chat message for LLM interactions."""

    role: str  # "system", "user", "assistant"
    content: str


@dataclass
class LLMResponse:
    """Response from LLM."""

    content: str
    confidence: float
    metadata: Optional[Dict[str, Any]] = None


class GroqClientInterface(ABC):
    """Abstract interface for Groq LLM client."""

    @abstractmethod
    async def chat_completion(
        self,
        messages: List[ChatMessage],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        reasoning_effort: Optional[str] = None,
    ) -> LLMResponse:
        """Generate chat completion using Groq LLM."""
        pass

    @abstractmethod
    async def chat_completion_stream(
        self,
        messages: List[ChatMessage],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        reasoning_effort: Optional[str] = None,
    ) -> AsyncIterator[str]:
        """Generate streaming chat completion using Groq LLM."""
        pass

    @abstractmethod
    async def should_escalate(
        self,
        message: str,
        response: str,
        kb_context: str,
        conversation_history: List,
        customer_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Determine if conversation should be escalated to human agent."""
        pass


class GroqClient(GroqClientInterface):
    """Real implementation of Groq client."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
    ):
        self.api_key = api_key or settings.groq_api_key
        self.model = model or settings.groq_model
        self.client = httpx.AsyncClient(
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=30.0,  # Reduced from 60.0 for faster responses
        )

    async def chat_completion(
        self,
        messages: List[ChatMessage],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        reasoning_effort: Optional[str] = None,
    ) -> LLMResponse:
        """Generate chat completion using Groq API."""
        model = model or self.model

        try:
            response = await self._chat_completion_with_retry(
                messages=messages,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                reasoning_effort=reasoning_effort,
            )
            return response
        except httpx.HTTPStatusError as e:
            logger.error(
                "Groq API request failed",
                status_code=e.response.status_code,
                error=str(e),
            )
            raise
        except Exception as e:
            logger.error(
                "Error calling Groq API",
                error=str(e),
            )
            raise

    async def _chat_completion_with_retry(
        self,
        messages: List[ChatMessage],
        model: str,
        temperature: float,
        max_tokens: Optional[int],
        reasoning_effort: Optional[str],
        retry_count: int = 0,
    ) -> LLMResponse:
        """Internal method with retry logic for truncation."""
        try:
            payload = {
                "model": model,
                "messages": [{"role": msg.role, "content": msg.content} for msg in messages],
                "temperature": temperature,
            }

            if max_tokens:
                payload["max_tokens"] = max_tokens

            # Add reasoning_effort for reasoning models
            reasoning_models = ["openai/gpt-oss-20b", "openai/gpt-oss-120b"]
            if model in reasoning_models and reasoning_effort:
                payload["reasoning_effort"] = reasoning_effort

            response = await self.client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                json=payload,
                timeout=20.0,
            )
            response.raise_for_status()
            data = response.json()

            content = data["choices"][0]["message"]["content"]
            finish_reason = data["choices"][0].get("finish_reason")

            # Log warning and retry if truncated
            if finish_reason == "length":
                logger.warning(
                    "Groq response truncated by max_tokens",
                    model=model,
                    max_tokens=max_tokens,
                    reasoning_effort=reasoning_effort,
                    finish_reason=finish_reason,
                    response_length=len(content),
                )
                
                # Retry once with doubled max_tokens (capped at 2000)
                if retry_count == 0 and max_tokens:
                    new_max_tokens = min(max_tokens * 2, 2000)
                    logger.info(
                        "Retrying with doubled max_tokens",
                        original_max_tokens=max_tokens,
                        new_max_tokens=new_max_tokens,
                    )
                    return await self._chat_completion_with_retry(
                        messages=messages,
                        model=model,
                        temperature=temperature,
                        max_tokens=new_max_tokens,
                        reasoning_effort=reasoning_effort,
                        retry_count=retry_count + 1,
                    )

            # Extract confidence
            confidence = 0.8
            if content and len(content) > 50:
                confidence = min(0.9, confidence + 0.1)
            if content and "i don't know" in content.lower() or "not sure" in content.lower():
                confidence = max(0.3, confidence - 0.3)

            return LLMResponse(
                content=content,
                confidence=confidence,
                metadata={"model": model, "usage": data.get("usage"), "finish_reason": finish_reason},
            )

        except httpx.HTTPStatusError as e:
            logger.error(
                "Groq API request failed",
                status_code=e.response.status_code,
                error=str(e),
            )
            raise
        except Exception as e:
            logger.error(
                "Error calling Groq API",
                error=str(e),
            )
            raise

    async def chat_completion_stream(
        self,
        messages: List[ChatMessage],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        reasoning_effort: Optional[str] = None,
    ) -> AsyncIterator[str]:
        """Generate streaming chat completion using Groq API."""
        model = model or self.model

        try:
            payload = {
                "model": model,
                "messages": [{"role": msg.role, "content": msg.content} for msg in messages],
                "temperature": temperature,
                "stream": True,
            }

            if max_tokens:
                payload["max_tokens"] = max_tokens

            # Add reasoning_effort for reasoning models
            reasoning_models = ["openai/gpt-oss-20b", "openai/gpt-oss-120b"]
            if model in reasoning_models and reasoning_effort:
                payload["reasoning_effort"] = reasoning_effort

            async with self.client.stream(
                "POST",
                "https://api.groq.com/openai/v1/chat/completions",
                json=payload,
                timeout=60.0,
            ) as response:
                response.raise_for_status()
                
                finish_reason = None
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        data_str = line[6:]
                        
                        if data_str == "[DONE]":
                            break
                        
                        try:
                            data = json.loads(data_str)
                            if "choices" in data and len(data["choices"]) > 0:
                                finish_reason = data["choices"][0].get("finish_reason")
                                
                                delta = data["choices"][0].get("delta", {})
                                content = delta.get("content", "")
                                if content:
                                    yield content
                        except json.JSONDecodeError:
                            continue
                
                # Log warning if stream was truncated
                if finish_reason == "length":
                    logger.warning(
                        "Groq streaming response truncated by max_tokens",
                        model=model,
                        max_tokens=max_tokens,
                        reasoning_effort=reasoning_effort,
                        finish_reason=finish_reason,
                    )
                            
        except httpx.HTTPStatusError as e:
            logger.error(
                "Groq API streaming request failed",
                status_code=e.response.status_code,
                error=str(e),
            )
            raise
        except Exception as e:
            logger.error(
                "Error calling Groq API streaming",
                error=str(e),
            )
            raise

    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()

    async def is_out_of_scope(
        self,
        message: str,
        kb_context: str,
        customer_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Ask Groq to determine if a question is out-of-scope based on KB context.
        
        Returns:
            Dict with keys:
            - is_out_of_scope: bool
            - reasoning: str
            - confidence: float
        """
        system_prompt = """You are a support AI for Shiva Software. Your task is to determine if a customer's question is within the scope of Shiva support services.

Consider the question out-of-scope if it is about:
- General knowledge unrelated to Shiva products/services (politics, weather, sports scores, entertainment, cooking, travel, etc.)
- External websites, services, or companies not related to Shiva
- Personal advice not related to their Shiva Softwares account or service usage

Consider the question in-scope if it relates to:
- Shiva Softwares products, services, platforms, or features
- Customer's Shiva Softwares account, billing, payments, or subscriptions
- Technical issues with Shiva Softwares software
- How to use Shiva Softwares tools or features
- Shiva Softwares support processes (tickets, escalation, etc.)

You have access to knowledge base context about Shiva Softwares. Use this to determine if the question relates to Shiva Softwares.

Respond in JSON format:
{
    "is_out_of_scope": true/false,
    "reasoning": "brief explanation",
    "confidence": 0.0-1.0
}"""

        user_message = f"""Customer question: {message}

Knowledge base context:
{kb_context if kb_context else "No relevant KB context found"}

Customer data:
{customer_data if customer_data else "No customer data provided"}

Is this question within the scope of Shiva Softwares support?"""

        try:
            messages = [
                ChatMessage(role="system", content=system_prompt),
                ChatMessage(role="user", content=user_message),
            ]

            response = await self.chat_completion(
                messages=messages,
                temperature=0.3,  # Lower temperature for more consistent classification
                max_tokens=200,
                reasoning_effort="low",
            )

            # Parse JSON response
            import json
            result = json.loads(response.content)

            return {
                "is_out_of_scope": result.get("is_out_of_scope", False),
                "reasoning": result.get("reasoning", ""),
                "confidence": result.get("confidence", 0.8),
            }
        except Exception as e:
            logger.error(
                "Error determining out-of-scope with Groq",
                error=str(e),
                message=message,
            )
            # Fallback: conservative approach - assume in-scope if analysis fails
            return {
                "is_out_of_scope": False,
                "reasoning": "Analysis failed, defaulting to in-scope",
                "confidence": 0.5,
            }

    async def should_escalate(
        self,
        message: str,
        response: str,
        kb_context: str,
        conversation_history: List,
        customer_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Ask Groq to determine if the conversation should be escalated to a human agent.

        This replaces fragile phrase-matching with structured LLM decision-making,
        making escalation detection work across all languages including Kiswahili.

        Returns:
            Dict with keys:
            - escalate: bool (whether to escalate to human)
            - reason: str (specific reason for escalation decision)
            - confidence: float (0.0-1.0 confidence in the decision)
        """
        system_prompt = """You are a support AI escalation decision system. Your task is to determine if a customer conversation should be escalated to a human agent.

Consider escalating if:
- The AI's solution doesn't address the customer's specific situation
- The customer indicates previous solutions didn't work
- The issue involves security, legal matters, or complex investigations
- The customer is expressing frustration or strong dissatisfaction
- The issue is highly complex and requires human judgment
- The customer explicitly requests to speak to a human
- Multiple AI attempts have failed to resolve the issue

Do NOT escalate if:
- The AI provided a clear, actionable solution that addresses the customer's question
- The customer is asking for clarification or additional information
- The issue is straightforward and within the AI's capabilities
- The customer is satisfied with the AI's assistance

HONESTY IN DECISIONS:
- Be conservative about escalation - escalate when genuinely uncertain or when human judgment is needed
- Don't rely on AI phrases like "I'll create a ticket" - those are language patterns, not actual actions
- Consider whether the customer truly needs human intervention vs whether AI can continue helping
- If in doubt, err on the side of escalation to ensure customers get the help they need

Respond in JSON format:
{
    "escalate": true/false,
    "reason": "specific reason for the decision",
    "confidence": 0.0-1.0
}"""

        # Build conversation summary from history
        history_summary = ""
        if conversation_history:
            recent_messages = conversation_history[-5:] if len(conversation_history) > 5 else conversation_history
            history_summary = "\n".join([
                f"{msg.sender}: {msg.content}" 
                for msg in recent_messages
            ])

        user_message = f"""Customer message: {message}

AI response: {response}

Knowledge base context: {kb_context if kb_context else "No relevant KB context found"}

Conversation history:
{history_summary if history_summary else "No previous conversation"}

Customer data: {customer_data if customer_data else "No customer data provided"}

Should this conversation be escalated to a human agent?"""

        try:
            messages = [
                ChatMessage(role="system", content=system_prompt),
                ChatMessage(role="user", content=user_message),
            ]

            response = await self.chat_completion(
                messages=messages,
                temperature=0.3,  # Lower temperature for consistent decisions
                max_tokens=200,
                reasoning_effort="low",
            )

            # Parse JSON response
            result = json.loads(response.content)

            return {
                "escalate": result.get("escalate", False),
                "reason": result.get("reason", ""),
                "confidence": result.get("confidence", 0.8),
            }
        except Exception as e:
            logger.error(
                "Error determining escalation with Groq",
                error=str(e),
                message=message,
            )
            # Fallback: conservative approach - don't escalate if analysis fails
            return {
                "escalate": False,
                "reason": "Analysis failed, defaulting to no escalation",
                "confidence": 0.5,
            }

    async def generate_ticket_title(
        self,
        message: str,
        customer_data: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Generate a concise, descriptive title for a ticket based on the customer's message.

        Args:
            message: The customer's message or issue description
            customer_data: Optional customer information for context

        Returns:
            A concise title (3-8 words) that summarizes the issue
        """
        system_prompt = """You are a support conversation title generator. Your task is to create short, specific titles for support conversations.

Rules:
- Title must be 3-8 words
- Be specific to the client's issue, product, or request
- Do not use generic titles such as "New conversation", "Support request", or "Help needed"
- Do not include quotation marks, emojis, markdown, or ending punctuation
- Use sentence case (capitalize first word only)
- Do not expose sensitive information (passwords, API keys, personal data)
- Focus on the main problem or action

Examples:
Client: "My M-Pesa payment callback is failing"
Title: "M-Pesa callback failure"

Client: "How do I create a new user?"
Title: "Creating a new user"

Client: "The dashboard is slow after login"
Title: "Slow dashboard after login"

Client: "I can't access my account"
Title: "Unable to access account"

Client: "Payment gateway setup issues"
Title: "Payment gateway setup issues"

Respond with ONLY the title, no additional text or explanation."""

        user_message = f"""Client message: {message}

Customer data: {customer_data if customer_data else "Not provided"}

Generate a conversation title:"""

        try:
            messages = [
                ChatMessage(role="system", content=system_prompt),
                ChatMessage(role="user", content=user_message),
            ]

            response = await self.chat_completion(
                messages=messages,
                temperature=0.3,  # Lower temperature for consistent titles
                max_tokens=50,
                reasoning_effort="low",
            )

            # Clean up the response - extract just the title
            title = response.content.strip()

            # Remove any quotes if present
            title = title.strip('"\'').strip()

            # Remove any ending punctuation
            title = title.rstrip('.,!?;:')

            # Ensure sentence case (capitalize first word only)
            if title:
                title = title[0].upper() + title[1:].lower()

            # Ensure it's not too long
            if len(title) > 100:
                title = title[:97] + "..."

            # Check word count and adjust if needed
            words = title.split()
            if len(words) < 3:
                # If too short, add context words
                if "issue" not in title.lower():
                    title = f"{title} issue"
                words = title.split()
            elif len(words) > 8:
                # If too long, truncate to 8 words
                title = ' '.join(words[:8])

            # Fallback if title is empty or too generic
            generic_titles = ["new conversation", "support request", "help needed", "customer support", "support ticket"]
            if not title or any(generic in title.lower() for generic in generic_titles):
                title = "Support conversation"

            logger.info(
                "Generated conversation title",
                title=title,
                word_count=len(title.split()),
                original_message_length=len(message),
            )

            return title

        except Exception as e:
            logger.error(
                "Failed to generate conversation title",
                error=str(e),
                message=message,
            )
            # Fallback to a generic title
            return "Support conversation"
