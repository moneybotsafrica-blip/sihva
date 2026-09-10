"""
Multi-Agent Support System
Specialized AI agents for different types of customer support issues.
"""
from typing import Optional, Dict, Any, List, AsyncIterator, Tuple
from abc import ABC, abstractmethod
import structlog

from app.clients.groq_client import GroqClient, ChatMessage, LLMResponse
from app.clients.qdrant_client import SearchResult
from app.config import settings
from app.common.prompts import LANGUAGE_POLICY, HONESTY_CALIBRATION, VERIFICATION_PROMPT
from app.db.models import MessageSender

logger = structlog.get_logger(__name__)


class SupportAgent(ABC):
    """Base class for specialized support agents."""

    def __init__(self, groq_client: GroqClient, name: str, specialization: str):
        self.groq_client = groq_client
        self.name = name
        self.specialization = specialization

    def _convert_message_to_chat_message(self, db_message) -> Optional[ChatMessage]:
        """
        Convert a database TicketMessage to a ChatMessage for the LLM.
        Returns None for system messages (they're handled separately).
        """
        if db_message.sender == MessageSender.CUSTOMER:
            return ChatMessage(role="user", content=db_message.content)
        elif db_message.sender == MessageSender.SUPPORT_AI:
            return ChatMessage(role="assistant", content=db_message.content)
        elif db_message.sender == MessageSender.STAFF:
            # Include staff messages as assistant so AI doesn't contradict human staff
            return ChatMessage(role="assistant", content=db_message.content)
        elif db_message.sender == MessageSender.CODE_AI:
            return ChatMessage(role="assistant", content=db_message.content)
        elif db_message.sender == MessageSender.SYSTEM:
            # System messages are handled separately, not as chat turns
            return None
        return None

    def _build_conversation_messages(
        self,
        conversation_history: List,
        current_message: str,
    ) -> List[ChatMessage]:
        """
        Build the conversation messages list including history.
        Implements history cap with summarization for long conversations.
        Handles both ChatMessage format (from Shiva Support) and database objects.
        """
        messages = []

        # Convert history to chat messages
        history_messages = []
        for msg in conversation_history:
            # Check if already ChatMessage format (from Shiva Support) or dict format
            if (hasattr(msg, 'role') and hasattr(msg, 'content')) or (isinstance(msg, dict) and 'role' in msg and 'content' in msg):
                # Already in ChatMessage format or dict format from Shiva Support
                role = msg.role if hasattr(msg, 'role') else msg.get('role')
                content = msg.content if hasattr(msg, 'content') else msg.get('content')
                if role in ["user", "assistant"]:
                    if hasattr(msg, 'role'):
                        history_messages.append(msg)
                    else:
                        # Convert dict to ChatMessage
                        history_messages.append(ChatMessage(role=role, content=content))
                # Skip system messages in history (they're handled separately)
            else:
                # Database object format - convert it
                chat_msg = self._convert_message_to_chat_message(msg)
                if chat_msg:
                    history_messages.append(chat_msg)

        # Apply history cap/summarization
        if len(history_messages) > settings.max_history_turns:
            # Keep the most recent turns verbatim
            recent_messages = history_messages[-settings.keep_recent_turns:]
            older_messages = history_messages[:-settings.keep_recent_turns]

            # Create a summary of older messages
            summary_parts = []
            for msg in older_messages:
                role = "Customer" if msg.role == "user" else "Support"
                # Truncate very long messages for summary
                content = msg.content[:200] + "..." if len(msg.content) > 200 else msg.content
                summary_parts.append(f"{role}: {content}")

            summary = f"[Earlier conversation summary: {' | '.join(summary_parts)}]"
            messages.append(ChatMessage(role="system", content=summary))

            # Add recent messages verbatim
            messages.extend(recent_messages)
        else:
            # Include all history if under the cap
            messages.extend(history_messages)

        # Add current message
        messages.append(ChatMessage(role="user", content=current_message))

        return messages

    def _inject_kb_context(self, system_prompt: str, kb_context: List[SearchResult]) -> str:
        """
        Inject knowledge base context into the system prompt.
        """
        if not kb_context:
            return system_prompt

        kb_section = "\n\nRELEVANT KNOWLEDGE BASE ARTICLES:\n"
        for i, result in enumerate(kb_context, 1):
            kb_section += f"\n{i}. {result.content}\n"
            if result.score:
                kb_section += f"   (Relevance score: {result.score:.2f})\n"

        kb_section += "\nINSTRUCTIONS: Use the above knowledge base articles to inform your response when relevant. "
        kb_section += "If the articles don't actually address the customer's specific issue, say so plainly rather than "
        kb_section += "forcing the content onto their situation. Always ground your answer in factual information from the KB when available.\n"

        return system_prompt + kb_section

    @abstractmethod
    async def can_handle(self, message: str, customer_data: Optional[Dict[str, Any]]) -> float:
        """
        Determine if this agent can handle the issue.
        Returns confidence score (0.0 to 1.0).
        """
        pass

    @abstractmethod
    async def handle(
        self,
        message: str,
        customer_data: Optional[Dict[str, Any]],
        kb_context: List[SearchResult],
        conversation_history: List,
        product_context: Optional[Dict[str, Any]] = None,
        client: Optional[GroqClient] = None,
    ) -> str:
        """Handle the issue and return a response."""
        pass

    async def handle_stream(
        self,
        message: str,
        customer_data: Optional[Dict[str, Any]],
        kb_context: List[SearchResult],
        conversation_history: List,
        product_context: Optional[Dict[str, Any]] = None,
        client: Optional[GroqClient] = None,
    ) -> AsyncIterator[str]:
        """
        Handle the issue and stream the response.
        Default implementation falls back to non-streaming handle().
        Override in subclasses for true streaming.
        """
        # Default: fall back to non-streaming and yield the full response
        response = await self.handle(message, customer_data, kb_context, conversation_history, product_context, client)
        yield response
    
    def get_system_prompt(self) -> str:
        """Get the system prompt for this agent."""
        return f"""You are {self.name}, a specialized {self.specialization} support agent for Shiva Softwares.

Your expertise: {self.specialization}

Shiva Softwares is a software platform providing various services and solutions. Customers can access features, manage their accounts, and get support for any issues they encounter.

Your role is to provide helpful, conversational support for issues in your area of expertise.
Format your responses in ChatGPT style - natural, friendly, and solution-oriented.

CONVERSATIONAL CONTINUITY:
- You have access to the full conversation history. Read it carefully before responding.
- Never ask for information the customer already provided earlier in the conversation.
- Build on what was already tried: if a previous suggestion didn't work, acknowledge it and try a different approach.
- If the customer's issue evolves across turns, reflect the fullest understanding of the problem, not just the latest message.
- Reference earlier parts of the conversation naturally (e.g., "Since you mentioned you're on iOS...", "Given that step A didn't work...").
- Don't start every response as if it's the first message - continue the conversation naturally.

SIMPLE TASK HANDLING:
- Handle simple, routine tasks directly without escalation
- Provide immediate solutions for common issues you can resolve
- Only suggest escalation for complex or critical issues that require human intervention
- Be proactive in solving problems rather than just providing information
- Give customers actionable steps they can take immediately

CRITICAL FORMATTING RULES (Plain Text Chat Widget):
- NEVER use markdown headers (#, ##, ###) - these don't render in plain text chat
- NEVER use markdown tables with | characters - they break chat readability
- NEVER use horizontal rules (---, ***) - they don't render properly
- NEVER use multiple heavy bold section labels as pseudo-headers
- Prefer short paragraphs (1-3 sentences) over any structured layout
- Use bullets only for genuine short lists of alternatives (max ~4 items, plain - or •, no nested bullets)
- Use numbered steps only for something the customer must literally do in order, max ~5 steps
- Phrase steps conversationally ("First, try...", "Then you can...") not as formal procedures
- No code blocks / curl examples unless the customer is clearly a developer asking about the API directly
- Aim for a reply a person would be comfortable reading on a phone in a chat bubble - a few sentences, not a document
- Keep responses concise and conversational - like texting with a helpful friend

TICKET SUBMISSION HONESTY:
|- NEVER describe steps for the customer to self-submit a ticket via the website (e.g., "find the Help link," "click Raise a Ticket," "fill in this form") unless those exact steps are present in the retrieved knowledge base context
|- If the customer wants a ticket raised and no such KB-grounded flow exists, say you will get a human agent looped in / escalate the conversation directly - do not invent a UI flow you have no evidence exists
|- Be honest about what options are actually available based on the knowledge base
|- If the customer explicitly asks to raise/open/create a ticket, acknowledge that and escalate to staff rather than providing fake self-service instructions

{HONESTY_CALIBRATION}

{VERIFICATION_PROMPT}

{LANGUAGE_POLICY}
"""


class TechnicalSupportAgent(SupportAgent):
    """Specialized agent for technical issues."""
    
    def __init__(self, groq_client: GroqClient):
        super().__init__(groq_client, "Tech Support Agent", "technical support")
    
    async def can_handle(self, message: str, customer_data: Optional[Dict[str, Any]]) -> float:
        """Check if this is a technical issue."""
        technical_keywords = [
            "error", "bug", "crash", "slow", "performance", "api", "integration",
            "configuration", "setup", "install", "deploy", "server", "database",
            "network", "connection", "timeout", "404", "500", "502", "503",
            "technical", "system", "platform", "code", "script", "automation"
        ]
        message_lower = message.lower()
        matches = sum(1 for keyword in technical_keywords if keyword in message_lower)
        return min(0.9, matches * 0.15)  # Cap at 0.9 confidence
    
    async def handle(
        self,
        message: str,
        customer_data: Optional[Dict[str, Any]],
        kb_context: List[SearchResult],
        conversation_history: List,
        product_context: Optional[Dict[str, Any]] = None,
        client: Optional[GroqClient] = None,
    ) -> str:
        """Handle technical issues with specialized guidance."""
        # Use provided client or fall back to default
        groq_client = client or self.groq_client
        
        system_prompt = self.get_system_prompt()

        # Add product-specific guidance if product_context is provided
        if product_context:
            product_name = product_context.get("product_name", "the product")
            enabled_modules = product_context.get("enabled_modules", [])
            relevant_articles = product_context.get("relevant_knowledge_articles", [])
            
            system_prompt += f"""
PRODUCT-AWARE GUIDANCE:
- The customer is using: {product_name}
- Enabled modules: {', '.join(enabled_modules) if enabled_modules else 'None specified'}
- Tailor your guidance only to this product and its enabled modules
- Do not suggest features or modules that are not enabled
- Reference relevant knowledge articles: {', '.join(relevant_articles[:3]) if relevant_articles else 'None'}
"""
        else:
            system_prompt += """
PRODUCT IDENTIFICATION:
- If the issue is product-specific and no product context is provided, ask one concise question to identify the affected product
- For general questions, answer generally without assuming a specific product
"""

        # Add technical-specific guidance
        system_prompt += """
TECHNICAL SUPPORT GUIDELINES:
- Focus on debugging, troubleshooting, and technical solutions
- Provide error-specific guidance when error codes are mentioned
- Include technical details but explain them simply
- Offer step-by-step technical solutions when appropriate
- Consider the customer's technical level based on their application
- Mention relevant documentation or resources when available

SIMPLE TECHNICAL TASKS (handle directly):
- Basic configuration questions
- Simple error troubleshooting (404, 500, timeouts)
- API integration basics
- Common feature usage questions
- Setup and installation guidance
- Performance optimization tips

COMPLEX TASKS (consider escalation):
- Server configuration changes
- Custom development work
- Advanced debugging
- Integration with third-party systems
- Platform bugs requiring fixes

CONVERSATIONAL CONTINUITY:
- Treat conversation_history as authoritative
- Never ask again for information already stated by the customer
- Do not repeat troubleshooting steps that the customer says they already tried
- If customer says "I have tried all these" or similar, acknowledge the attempted steps and request only the next useful diagnostic evidence
- Do not ask what the customer was doing if they already stated it
- Retain context from earlier messages in the conversation

ESCALATION CRITERIA:
- For repeated authentication/401/500 failures after basic troubleshooting, recommend handoff
- Return structured escalation metadata when recommending escalation
"""

        # Detect if customer says they tried the suggested steps
        tried_steps_indicators = [
            "i have tried", "i tried", "already tried", "didn't work", "not working",
            "still getting", "still have", "still facing", "none of these worked",
            "all of these", "tried all", "tried everything"
        ]
        customer_tried_steps = any(indicator in message.lower() for indicator in tried_steps_indicators)

        # Detect repeated authentication/401/500 errors in conversation history
        has_repeated_auth_errors = False
        if conversation_history:
            error_count = 0
            for msg in conversation_history:
                msg_content = msg.content if hasattr(msg, 'content') else msg.get('content', '')
                msg_lower = msg_content.lower()
                if any(code in msg_lower for code in ['401', 'unauthorized', 'authentication', '500', 'server error']):
                    error_count += 1
            if error_count >= 2:  # Multiple mentions of auth/server errors
                has_repeated_auth_errors = True

        # If customer tried steps and has repeated auth errors, recommend escalation
        if customer_tried_steps and has_repeated_auth_errors:
            system_prompt += """
IMMEDIATE ESCALATION RECOMMENDED:
- The customer has tried the suggested troubleshooting steps and still faces repeated authentication/server errors
- This requires human investigation - recommend handoff to support staff
- Acknowledge the issue severity and the steps already attempted
- Do not ask what the customer was doing if they already stated it
"""

        # Inject KB context into system prompt
        system_prompt = self._inject_kb_context(system_prompt, kb_context)

        # Build messages with conversation history
        messages = [ChatMessage(role="system", content=system_prompt)]
        conversation_messages = self._build_conversation_messages(conversation_history, message)
        messages.extend(conversation_messages)

        response = await groq_client.chat_completion(
            messages=messages,
            max_tokens=1500,
            # Tier B: Keep default reasoning_effort (medium) for quality troubleshooting
        )
        return response.content

    async def handle_stream(
        self,
        message: str,
        customer_data: Optional[Dict[str, Any]],
        kb_context: List[SearchResult],
        conversation_history: List,
        product_context: Optional[Dict[str, Any]] = None,
        client: Optional[GroqClient] = None,
    ) -> AsyncIterator[str]:
        """Handle technical issues with streaming response."""
        # Use provided client or fall back to default
        groq_client = client or self.groq_client
        
        system_prompt = self.get_system_prompt()

        # Add product-specific guidance if product_context is provided
        if product_context:
            product_name = product_context.get("product_name", "the product")
            enabled_modules = product_context.get("enabled_modules", [])
            relevant_articles = product_context.get("relevant_knowledge_articles", [])
            
            system_prompt += f"""
PRODUCT-AWARE GUIDANCE:
- The customer is using: {product_name}
- Enabled modules: {', '.join(enabled_modules) if enabled_modules else 'None specified'}
- Tailor your guidance only to this product and its enabled modules
- Do not suggest features or modules that are not enabled
- Reference relevant knowledge articles: {', '.join(relevant_articles[:3]) if relevant_articles else 'None'}
"""
        else:
            system_prompt += """
PRODUCT IDENTIFICATION:
- If the issue is product-specific and no product context is provided, ask one concise question to identify the affected product
- For general questions, answer generally without assuming a specific product
"""

        # Add technical-specific guidance
        system_prompt += """
TECHNICAL SUPPORT GUIDELINES:
- Focus on debugging, troubleshooting, and technical solutions
- Provide error-specific guidance when error codes are mentioned
- Include technical details but explain them simply
- Offer step-by-step technical solutions when appropriate
- Consider the customer's technical level based on their application
- Mention relevant documentation or resources when available

SIMPLE TECHNICAL TASKS (handle directly):
- Basic configuration questions
- Simple error troubleshooting (404, 500, timeouts)
- API integration basics
- Common feature usage questions
- Setup and installation guidance
- Performance optimization tips

COMPLEX TASKS (consider escalation):
- Server configuration changes
- Custom development work
- Advanced debugging
- Integration with third-party systems
- Platform bugs requiring fixes

CONVERSATIONAL CONTINUITY:
- Treat conversation_history as authoritative
- Never ask again for information already stated by the customer
- Do not repeat troubleshooting steps that the customer says they already tried
- If customer says "I have tried all these" or similar, acknowledge the attempted steps and request only the next useful diagnostic evidence
- Do not ask what the customer was doing if they already stated it
- Retain context from earlier messages in the conversation

ESCALATION CRITERIA:
- For repeated authentication/401/500 failures after basic troubleshooting, recommend handoff
- Return structured escalation metadata when recommending escalation
"""

        # Detect if customer says they tried the suggested steps
        tried_steps_indicators = [
            "i have tried", "i tried", "already tried", "didn't work", "not working",
            "still getting", "still have", "still facing", "none of these worked",
            "all of these", "tried all", "tried everything"
        ]
        customer_tried_steps = any(indicator in message.lower() for indicator in tried_steps_indicators)

        # Detect repeated authentication/401/500 errors in conversation history
        has_repeated_auth_errors = False
        if conversation_history:
            error_count = 0
            for msg in conversation_history:
                msg_content = msg.content if hasattr(msg, 'content') else msg.get('content', '')
                msg_lower = msg_content.lower()
                if any(code in msg_lower for code in ['401', 'unauthorized', 'authentication', '500', 'server error']):
                    error_count += 1
            if error_count >= 2:  # Multiple mentions of auth/server errors
                has_repeated_auth_errors = True

        # If customer tried steps and has repeated auth errors, recommend escalation
        if customer_tried_steps and has_repeated_auth_errors:
            system_prompt += """
IMMEDIATE ESCALATION RECOMMENDED:
- The customer has tried the suggested troubleshooting steps and still faces repeated authentication/server errors
- This requires human investigation - recommend handoff to support staff
- Acknowledge the issue severity and the steps already attempted
- Do not ask what the customer was doing if they already stated it
"""

        # Inject KB context into system prompt
        system_prompt = self._inject_kb_context(system_prompt, kb_context)

        # Build messages with conversation history
        messages = [ChatMessage(role="system", content=system_prompt)]
        conversation_messages = self._build_conversation_messages(conversation_history, message)
        messages.extend(conversation_messages)

        # Stream the response
        async for chunk in groq_client.chat_completion_stream(
            messages=messages,
            max_tokens=1500,
            # Tier B: Keep default reasoning_effort (medium) for quality troubleshooting
        ):
            yield chunk


class BillingSupportAgent(SupportAgent):
    """Specialized agent for billing and payment issues."""
    
    def __init__(self, groq_client: GroqClient):
        super().__init__(groq_client, "Billing Support Agent", "billing and payments")
    
    async def can_handle(self, message: str, customer_data: Optional[Dict[str, Any]]) -> float:
        """Check if this is a billing issue."""
        billing_keywords = [
            "billing", "invoice", "payment", "charge", "refund", "credit",
            "subscription", "plan", "upgrade", "downgrade", "cancel",
            "price", "cost", "fee", "transaction", "receipt", "statement"
        ]
        message_lower = message.lower()
        matches = sum(1 for keyword in billing_keywords if keyword in message_lower)
        return min(0.9, matches * 0.2)  # Higher weight for billing
    
    async def handle(
        self,
        message: str,
        customer_data: Optional[Dict[str, Any]],
        kb_context: List[SearchResult],
        conversation_history: List,
        product_context: Optional[Dict[str, Any]] = None,
        client: Optional[GroqClient] = None,
    ) -> str:
        """Handle billing issues with financial guidance."""
        # Use provided client or fall back to default
        groq_client = client or self.groq_client
        
        system_prompt = self.get_system_prompt()

        # Add product-specific guidance if product_context is provided
        if product_context:
            product_name = product_context.get("product_name", "the product")
            enabled_modules = product_context.get("enabled_modules", [])
            
            system_prompt += f"""
PRODUCT-AWARE GUIDANCE:
- The customer is using: {product_name}
- Enabled modules: {', '.join(enabled_modules) if enabled_modules else 'None specified'}
- Tailor billing guidance to this product and its enabled modules
"""

        # Add billing-specific guidance
        system_prompt += """
BILLING SUPPORT GUIDELINES:
- Focus on payment processing, invoices, and subscription management
- Provide clear explanations of charges and billing cycles
- Guide customers through payment troubleshooting
- Be empathetic about financial concerns
- Explain refund policies when applicable
- Connect with customer data for accurate billing information
- Never make promises about refunds or credits beyond policy

SIMPLE BILLING TASKS (handle directly):
- Understanding charges and invoices
- Subscription plan questions
- Payment method updates
- Billing cycle explanations
- Discount eligibility questions
- Basic payment troubleshooting

COMPLEX BILLING TASKS (consider escalation):
- Refund requests (refer to policy, don't promise)
- Disputed charges
- Account credits
- Payment failures requiring investigation
- Complex billing disputes
"""

        # Add customer billing context if available
        if customer_data:
            plan = customer_data.get("plan", "unknown")
            system_prompt += f"\nCustomer plan: {plan}"

        # Inject KB context into system prompt
        system_prompt = self._inject_kb_context(system_prompt, kb_context)

        # Build messages with conversation history
        messages = [ChatMessage(role="system", content=system_prompt)]
        conversation_messages = self._build_conversation_messages(conversation_history, message)
        messages.extend(conversation_messages)

        response = await groq_client.chat_completion(
            messages=messages,
            max_tokens=1500,
            # Tier B: Keep default reasoning_effort (medium) for quality troubleshooting
        )
        return response.content

    async def handle_stream(
        self,
        message: str,
        customer_data: Optional[Dict[str, Any]],
        kb_context: List[SearchResult],
        conversation_history: List,
        product_context: Optional[Dict[str, Any]] = None,
        client: Optional[GroqClient] = None,
    ) -> AsyncIterator[str]:
        """Handle billing issues with streaming response."""
        # Use provided client or fall back to default
        groq_client = client or self.groq_client
        
        system_prompt = self.get_system_prompt()

        # Add product-specific guidance if product_context is provided
        if product_context:
            product_name = product_context.get("product_name", "the product")
            enabled_modules = product_context.get("enabled_modules", [])
            
            system_prompt += f"""
PRODUCT-AWARE GUIDANCE:
- The customer is using: {product_name}
- Enabled modules: {', '.join(enabled_modules) if enabled_modules else 'None specified'}
- Tailor billing guidance to this product and its enabled modules
"""

        # Add billing-specific guidance
        system_prompt += """
BILLING SUPPORT GUIDELINES:
- Focus on payment processing, invoices, and subscription management
- Provide clear explanations of charges and billing cycles
- Guide customers through payment troubleshooting
- Be empathetic about financial concerns
- Explain refund policies when applicable
- Connect with customer data for accurate billing information
- Never make promises about refunds or credits beyond policy

SIMPLE BILLING TASKS (handle directly):
- Understanding charges and invoices
- Subscription plan questions
- Payment method updates
- Billing cycle explanations
- Discount eligibility questions
- Basic payment troubleshooting

COMPLEX BILLING TASKS (consider escalation):
- Refund requests (refer to policy, don't promise)
- Disputed charges
- Account credits
- Payment failures requiring investigation
- Complex billing disputes
"""

        # Add customer billing context if available
        if customer_data:
            plan = customer_data.get("plan", "unknown")
            system_prompt += f"\nCustomer plan: {plan}"

        # Inject KB context into system prompt
        system_prompt = self._inject_kb_context(system_prompt, kb_context)

        # Build messages with conversation history
        messages = [ChatMessage(role="system", content=system_prompt)]
        conversation_messages = self._build_conversation_messages(conversation_history, message)
        messages.extend(conversation_messages)

        # Stream the response
        async for chunk in groq_client.chat_completion_stream(
            messages=messages,
            max_tokens=1500,
            # Tier B: Keep default reasoning_effort (medium) for quality troubleshooting
        ):
            yield chunk


class AccountSupportAgent(SupportAgent):
    """Specialized agent for account management issues."""
    
    def __init__(self, groq_client: GroqClient):
        super().__init__(groq_client, "Account Support Agent", "account management")
    
    async def can_handle(self, message: str, customer_data: Optional[Dict[str, Any]]) -> float:
        """Check if this is an account issue."""
        account_keywords = [
            "account", "login", "password", "reset", "profile", "settings",
            "user", "authentication", "access", "permission", "role",
            "locked", "suspended", "disabled", "email", "username"
        ]
        message_lower = message.lower()
        matches = sum(1 for keyword in account_keywords if keyword in message_lower)
        return min(0.9, matches * 0.15)
    
    async def handle(
        self,
        message: str,
        customer_data: Optional[Dict[str, Any]],
        kb_context: List[SearchResult],
        conversation_history: List,
        product_context: Optional[Dict[str, Any]] = None,
        client: Optional[GroqClient] = None,
    ) -> str:
        """Handle account issues with account-specific guidance."""
        # Use provided client or fall back to default
        groq_client = client or self.groq_client
        
        system_prompt = self.get_system_prompt()

        # Add product-specific guidance if product_context is provided
        if product_context:
            product_name = product_context.get("product_name", "the product")
            enabled_modules = product_context.get("enabled_modules", [])
            
            system_prompt += f"""
PRODUCT-AWARE GUIDANCE:
- The customer is using: {product_name}
- Enabled modules: {', '.join(enabled_modules) if enabled_modules else 'None specified'}
- Tailor account guidance to this product and its enabled modules
"""

        # Add account-specific guidance
        system_prompt += """
ACCOUNT SUPPORT GUIDELINES:
- Focus on account access, authentication, and profile management
- Provide step-by-step guidance for password resets and account recovery
- Guide customers through account settings and configuration
- Be sensitive to account security concerns
- Verify customer identity when appropriate (within system capabilities)
- Explain account features and limitations clearly

SIMPLE ACCOUNT TASKS (handle directly):
- Password reset guidance
- Login troubleshooting
- Profile updates
- Account settings navigation
- Feature access questions
- Basic account recovery

COMPLEX ACCOUNT TASKS (consider escalation):
- Account lockout requiring admin action
- Identity verification issues
- Account merging
- Complex permission changes
- Account security incidents
"""

        # Add customer account context if available
        if customer_data:
            name = customer_data.get("name", "customer")
            email = customer_data.get("email", "not provided")
            system_prompt += f"\nCustomer: {name} ({email})"

        # Inject KB context into system prompt
        system_prompt = self._inject_kb_context(system_prompt, kb_context)

        # Build messages with conversation history
        messages = [ChatMessage(role="system", content=system_prompt)]
        conversation_messages = self._build_conversation_messages(conversation_history, message)
        messages.extend(conversation_messages)

        response = await groq_client.chat_completion(
            messages=messages,
            max_tokens=1500,
            # Tier B: Keep default reasoning_effort (medium) for quality troubleshooting
        )
        return response.content

    async def handle_stream(
        self,
        message: str,
        customer_data: Optional[Dict[str, Any]],
        kb_context: List[SearchResult],
        conversation_history: List,
        product_context: Optional[Dict[str, Any]] = None,
        client: Optional[GroqClient] = None,
    ) -> AsyncIterator[str]:
        """Handle account issues with streaming response."""
        # Use provided client or fall back to default
        groq_client = client or self.groq_client
        
        system_prompt = self.get_system_prompt()

        # Add product-specific guidance if product_context is provided
        if product_context:
            product_name = product_context.get("product_name", "the product")
            enabled_modules = product_context.get("enabled_modules", [])
            
            system_prompt += f"""
PRODUCT-AWARE GUIDANCE:
- The customer is using: {product_name}
- Enabled modules: {', '.join(enabled_modules) if enabled_modules else 'None specified'}
- Tailor account guidance to this product and its enabled modules
"""

        # Add account-specific guidance
        system_prompt += """
ACCOUNT SUPPORT GUIDELINES:
- Focus on account access, authentication, and profile management
- Provide step-by-step guidance for password resets and account recovery
- Guide customers through account settings and configuration
- Be sensitive to account security concerns
- Verify customer identity when appropriate (within system capabilities)
- Explain account features and limitations clearly

SIMPLE ACCOUNT TASKS (handle directly):
- Password reset guidance
- Login troubleshooting
- Profile updates
- Account settings navigation
- Feature access questions
- Basic account recovery

COMPLEX ACCOUNT TASKS (consider escalation):
- Account lockout requiring admin action
- Identity verification issues
- Account merging
- Complex permission changes
- Account security incidents
"""

        # Add customer account context if available
        if customer_data:
            name = customer_data.get("name", "customer")
            email = customer_data.get("email", "not provided")
            system_prompt += f"\nCustomer: {name} ({email})"

        # Inject KB context into system prompt
        system_prompt = self._inject_kb_context(system_prompt, kb_context)

        # Build messages with conversation history
        messages = [ChatMessage(role="system", content=system_prompt)]
        conversation_messages = self._build_conversation_messages(conversation_history, message)
        messages.extend(conversation_messages)

        # Stream the response
        async for chunk in groq_client.chat_completion_stream(
            messages=messages,
            max_tokens=1500,
            # Tier B: Keep default reasoning_effort (medium) for quality troubleshooting
        ):
            yield chunk


class SecuritySupportAgent(SupportAgent):
    """Specialized agent for security issues."""
    
    def __init__(self, groq_client: GroqClient):
        super().__init__(groq_client, "Security Support Agent", "security and privacy")
    
    async def can_handle(self, message: str, customer_data: Optional[Dict[str, Any]]) -> float:
        """Check if this is a security issue."""
        security_keywords = [
            "security", "hack", "breach", "compromise", "attack", "malware",
            "phishing", "suspicious", "unauthorized", "data loss", "privacy",
            "vulnerability", "exploit", "stolen", "compromised", "credential"
        ]
        message_lower = message.lower()
        matches = sum(1 for keyword in security_keywords if keyword in message_lower)
        return min(0.95, matches * 0.25)  # Higher weight for security
    
    async def handle(
        self,
        message: str,
        customer_data: Optional[Dict[str, Any]],
        kb_context: List[SearchResult],
        conversation_history: List,
        product_context: Optional[Dict[str, Any]] = None,
        client: Optional[GroqClient] = None,
    ) -> str:
        """Handle security issues with security-focused guidance."""
        # Use provided client or fall back to default
        groq_client = client or self.groq_client
        
        system_prompt = self.get_system_prompt()

        # Add product-specific guidance if product_context is provided
        if product_context:
            product_name = product_context.get("product_name", "the product")
            enabled_modules = product_context.get("enabled_modules", [])
            
            system_prompt += f"""
PRODUCT-AWARE GUIDANCE:
- The customer is using: {product_name}
- Enabled modules: {', '.join(enabled_modules) if enabled_modules else 'None specified'}
- Tailor security guidance to this product and its enabled modules
"""

        # Add security-specific guidance
        system_prompt += """
SECURITY SUPPORT GUIDELINES:
- Take security issues seriously and respond urgently
- Provide immediate guidance for compromised accounts
- Explain security best practices clearly
- Guide customers through security verification processes
- Be thorough but also act quickly for security incidents
- Escalate serious security issues immediately
- Never ask for sensitive information unnecessarily
- When security incidents are detected, recommend ticket creation for investigation
"""

        # Inject KB context into system prompt
        system_prompt = self._inject_kb_context(system_prompt, kb_context)

        # Build messages with conversation history
        messages = [ChatMessage(role="system", content=system_prompt)]
        conversation_messages = self._build_conversation_messages(conversation_history, message)
        messages.extend(conversation_messages)

        response = await groq_client.chat_completion(
            messages=messages,
            max_tokens=1500,
            # Tier B: Keep default reasoning_effort (medium) for quality troubleshooting
        )
        return response.content

    async def handle_stream(
        self,
        message: str,
        customer_data: Optional[Dict[str, Any]],
        kb_context: List[SearchResult],
        conversation_history: List,
        product_context: Optional[Dict[str, Any]] = None,
        client: Optional[GroqClient] = None,
    ) -> AsyncIterator[str]:
        """Handle security issues with streaming response."""
        # Use provided client or fall back to default
        groq_client = client or self.groq_client
        
        system_prompt = self.get_system_prompt()

        # Add product-specific guidance if product_context is provided
        if product_context:
            product_name = product_context.get("product_name", "the product")
            enabled_modules = product_context.get("enabled_modules", [])
            
            system_prompt += f"""
PRODUCT-AWARE GUIDANCE:
- The customer is using: {product_name}
- Enabled modules: {', '.join(enabled_modules) if enabled_modules else 'None specified'}
- Tailor security guidance to this product and its enabled modules
"""

        # Add security-specific guidance
        system_prompt += """
SECURITY SUPPORT GUIDELINES:
- Take security issues seriously and respond urgently
- Provide immediate guidance for compromised accounts
- Explain security best practices clearly
- Guide customers through security verification processes
- Be thorough but also act quickly for security incidents
- Escalate serious security issues immediately
- Never ask for sensitive information unnecessarily
- When security incidents are detected, recommend ticket creation for investigation
"""

        # Inject KB context into system prompt
        system_prompt = self._inject_kb_context(system_prompt, kb_context)

        # Build messages with conversation history
        messages = [ChatMessage(role="system", content=system_prompt)]
        conversation_messages = self._build_conversation_messages(conversation_history, message)
        messages.extend(conversation_messages)

        # Stream the response
        async for chunk in groq_client.chat_completion_stream(
            messages=messages,
            max_tokens=1500,
            # Tier B: Keep default reasoning_effort (medium) for quality troubleshooting
        ):
            yield chunk


class GeneralSupportAgent(SupportAgent):
    """General purpose support agent for other issues."""
    
    def __init__(self, groq_client: GroqClient):
        super().__init__(groq_client, "General Support Agent", "general support")
    
    async def can_handle(self, message: str, customer_data: Optional[Dict[str, Any]]) -> float:
        """This agent can handle anything, but with lower priority."""
        return 0.3  # Base confidence for general support
    
    async def handle(
        self,
        message: str,
        customer_data: Optional[Dict[str, Any]],
        kb_context: List[SearchResult],
        conversation_history: List,
        product_context: Optional[Dict[str, Any]] = None,
        client: Optional[GroqClient] = None,
    ) -> str:
        """Handle general issues with broad support."""
        # Use provided client or fall back to default
        groq_client = client or self.groq_client
        
        system_prompt = self.get_system_prompt()

        # Add product-specific guidance if product_context is provided
        if product_context:
            product_name = product_context.get("product_name", "the product")
            enabled_modules = product_context.get("enabled_modules", [])
            
            system_prompt += f"""
PRODUCT-AWARE GUIDANCE:
- The customer is using: {product_name}
- Enabled modules: {', '.join(enabled_modules) if enabled_modules else 'None specified'}
- Tailor general guidance to this product and its enabled modules
"""

        # Add general support guidance
        system_prompt += """
GENERAL SUPPORT GUIDELINES:
- Provide helpful support for any Shiva-related questions
- Use knowledge base and general knowledge to assist
- Escalate to specialized agents or staff when needed
- Be friendly and helpful across all topics
- If you can't fully resolve, acknowledge and suggest next steps

SIMPLE GENERAL TASKS (handle directly):
- Feature questions and how-to guides
- Platform navigation help
- Basic troubleshooting tips
- Product information requests
- FAQ-type questions
- General guidance and advice

COMPLEX GENERAL TASKS (consider escalation):
- Complex feature combinations
- Platform bugs requiring fixes
- Advanced custom configurations
- Multi-step workflows requiring investigation
"""

        # Inject KB context into system prompt
        system_prompt = self._inject_kb_context(system_prompt, kb_context)

        # Build messages with conversation history
        messages = [ChatMessage(role="system", content=system_prompt)]
        conversation_messages = self._build_conversation_messages(conversation_history, message)
        messages.extend(conversation_messages)

        response = await groq_client.chat_completion(
            messages=messages,
            max_tokens=1500,
            # Tier B: Keep default reasoning_effort (medium) for quality troubleshooting
        )
        return response.content

    async def handle_stream(
        self,
        message: str,
        customer_data: Optional[Dict[str, Any]],
        kb_context: List[SearchResult],
        conversation_history: List,
        product_context: Optional[Dict[str, Any]] = None,
    ) -> AsyncIterator[str]:
        """Handle general issues with streaming response."""
        system_prompt = self.get_system_prompt()

        # Add product-specific guidance if product_context is provided
        if product_context:
            product_name = product_context.get("product_name", "the product")
            enabled_modules = product_context.get("enabled_modules", [])
            
            system_prompt += f"""
PRODUCT-AWARE GUIDANCE:
- The customer is using: {product_name}
- Enabled modules: {', '.join(enabled_modules) if enabled_modules else 'None specified'}
- Tailor general guidance to this product and its enabled modules
"""

        # Add general support guidance
        system_prompt += """
GENERAL SUPPORT GUIDELINES:
- Provide helpful support for any Shiva-related questions
- Use knowledge base and general knowledge to assist
- Escalate to specialized agents or staff when needed
- Be friendly and helpful across all topics
- If you can't fully resolve, acknowledge and suggest next steps

SIMPLE GENERAL TASKS (handle directly):
- Feature questions and how-to guides
- Platform navigation help
- Basic troubleshooting tips
- Product information requests
- FAQ-type questions
- General guidance and advice

COMPLEX GENERAL TASKS (consider escalation):
- Complex feature combinations
- Platform bugs requiring fixes
- Advanced custom configurations
- Multi-step workflows requiring investigation
"""

        # Inject KB context into system prompt
        system_prompt = self._inject_kb_context(system_prompt, kb_context)

        # Build messages with conversation history
        messages = [ChatMessage(role="system", content=system_prompt)]
        conversation_messages = self._build_conversation_messages(conversation_history, message)
        messages.extend(conversation_messages)

        response = await groq_client.chat_completion(
            messages=messages,
            max_tokens=1500,
            # Tier B: Keep default reasoning_effort (medium) for quality troubleshooting
        )
        return response.content

    async def handle_stream(
        self,
        message: str,
        customer_data: Optional[Dict[str, Any]],
        kb_context: List[SearchResult],
        conversation_history: List,
        product_context: Optional[Dict[str, Any]] = None,
        client: Optional[GroqClient] = None,
    ) -> AsyncIterator[str]:
        """Handle general issues with streaming response."""
        # Use provided client or fall back to default
        groq_client = client or self.groq_client
        
        system_prompt = self.get_system_prompt()

        # Add product-specific guidance if product_context is provided
        if product_context:
            product_name = product_context.get("product_name", "the product")
            enabled_modules = product_context.get("enabled_modules", [])
            
            system_prompt += f"""
PRODUCT-AWARE GUIDANCE:
|- The customer is using: {product_name}
|- Enabled modules: {', '.join(enabled_modules) if enabled_modules else 'None specified'}
|- Tailor general guidance to this product and its enabled modules
"""

        # Add general support guidance
        system_prompt += """
GENERAL SUPPORT GUIDELINES:
|- Provide helpful support for any Shiva-related questions
|- Use knowledge base and general knowledge to assist
|- Escalate to specialized agents or staff when needed
|- Be friendly and helpful across all topics
|- If you can't fully resolve, acknowledge and suggest next steps

CONVERSATIONAL CONTINUITY:
|- Treat conversation_history as authoritative
|- Never ask again for information already stated by the customer
|- Do not repeat suggestions that the customer says they already tried
|- If customer says "I have tried all these" or similar, acknowledge the attempted steps and request only the next useful information
|- Do not ask what the customer was doing if they already stated it
|- Retain context from earlier messages in the conversation

SIMPLE GENERAL TASKS (handle directly):
|- Feature questions and how-to guides
|- Platform navigation help
|- Basic troubleshooting tips
|- Product information requests
|- FAQ-type questions
|- General guidance and advice

COMPLEX GENERAL TASKS (consider escalation):
|- Complex feature combinations
|- Platform bugs requiring fixes
|- Advanced custom configurations
|- Multi-step workflows requiring investigation
"""

        # Inject KB context into system prompt
        system_prompt = self._inject_kb_context(system_prompt, kb_context)

        # Build messages with conversation history
        messages = [ChatMessage(role="system", content=system_prompt)]
        conversation_messages = self._build_conversation_messages(conversation_history, message)
        messages.extend(conversation_messages)

        # Stream the response
        async for chunk in groq_client.chat_completion_stream(
            messages=messages,
            max_tokens=1500,
            # Tier B: Keep default reasoning_effort (medium) for quality troubleshooting
        ):
            yield chunk


class AgentOrchestrator:
    """Orchestrates multiple AI agents to handle customer support issues."""
    
    def __init__(self, groq_client: GroqClient):
        self.groq_client = groq_client
        self.agents = [
            SecuritySupportAgent(groq_client),
            BillingSupportAgent(groq_client),
            TechnicalSupportAgent(groq_client),
            AccountSupportAgent(groq_client),
            GeneralSupportAgent(groq_client),
        ]
    
    def is_simple_task(self, message: str) -> bool:
        """Detect if this is a simple task that can be handled without escalation."""
        simple_task_indicators = [
            "how to", "how do i", "what is", "where is", "can i",
            "help with", "need help with", "explain", "tell me about",
            "guide", "show me", "demo", "example", "tutorial"
        ]
        
        # Complex task indicators that should NOT be considered simple
        complex_task_indicators = [
            "crash", "crashing", "failing", "failed", "broken", "not working",
            "down", "outage", "unauthorized", "hack", "breach", "compromise",
            "urgent", "emergency", "critical", "severe", "serious",
            "memory leak", "production", "server error", "database",
            "security", "incident", "attack", "malware", "virus"
        ]
        
        message_lower = message.lower()
        
        # If contains complex indicators, it's NOT simple
        if any(indicator in message_lower for indicator in complex_task_indicators):
            return False
        
        # Very short messages (under 8 words) with simple structure tend to be simple
        if len(message.split()) < 8:
            # But check they don't contain complex indicators
            if not any(indicator in message_lower for indicator in complex_task_indicators):
                return True
        
        # Contains simple task structures
        if any(indicator in message_lower for indicator in simple_task_indicators):
            # Only consider simple if not also complex
            if not any(indicator in message_lower for indicator in complex_task_indicators):
                return True
        
        return False
    
    async def select_best_agent(
        self,
        message: str,
        customer_data: Optional[Dict[str, Any]],
    ) -> SupportAgent:
        """Select the best agent for the given issue."""
        agent_scores = []
        
        for agent in self.agents:
            score = await agent.can_handle(message, customer_data)
            agent_scores.append((agent, score))
        
        # Sort by score (highest first)
        agent_scores.sort(key=lambda x: x[1], reverse=True)
        
        best_agent, best_score = agent_scores[0]
        
        logger.info(
            "Agent selection",
            selected_agent=best_agent.name,
            confidence=best_score,
            is_simple_task=self.is_simple_task(message),
            all_scores=[(agent.name, score) for agent, score in agent_scores],
        )
        
        return best_agent
    
    async def handle_with_agent(
        self,
        message: str,
        customer_data: Optional[Dict[str, Any]],
        kb_context: List[SearchResult],
        conversation_history: List,
        product_context: Optional[Dict[str, Any]] = None,
        client: Optional[GroqClient] = None,
    ) -> Tuple[str, str]:
        """Handle the issue using the best agent. Returns (response, agent_name)."""
        best_agent = await self.select_best_agent(message, customer_data)

        is_simple = self.is_simple_task(message)

        logger.info(
            "Delegating to specialized agent",
            agent=best_agent.name,
            specialization=best_agent.specialization,
            is_simple_task=is_simple,
        )

        response = await best_agent.handle(
            message=message,
            customer_data=customer_data,
            kb_context=kb_context,
            conversation_history=conversation_history,
            product_context=product_context,
            client=client,
        )

        # Handle both string response (old format) and dict response (new format)
        if isinstance(response, dict):
            # New format with metadata
            return response.get("response", ""), response.get("agent_name", best_agent.name)
        else:
            # Old format - just string response
            return response, best_agent.name

    async def handle_with_agent_stream(
        self,
        message: str,
        customer_data: Optional[Dict[str, Any]],
        kb_context: List[SearchResult],
        conversation_history: List,
        product_context: Optional[Dict[str, Any]] = None,
        client: Optional[GroqClient] = None,
    ) -> AsyncIterator[Tuple[str, str]]:
        """
        Handle the issue using the best agent with streaming.
        Yields (chunk, agent_name) tuples.
        """
        best_agent = await self.select_best_agent(message, customer_data)

        is_simple = self.is_simple_task(message)

        logger.info(
            "Delegating to specialized agent (streaming)",
            agent=best_agent.name,
            specialization=best_agent.specialization,
            is_simple_task=is_simple,
        )

        # Stream the response, yielding agent_name only on first chunk
        first_chunk = True
        async for chunk in best_agent.handle_stream(
            message=message,
            customer_data=customer_data,
            kb_context=kb_context,
            conversation_history=conversation_history,
            product_context=product_context,
            client=client,
        ):
            if first_chunk:
                yield chunk, best_agent.name
                first_chunk = False
            else:
                yield chunk, ""  # Empty agent_name after first chunk
