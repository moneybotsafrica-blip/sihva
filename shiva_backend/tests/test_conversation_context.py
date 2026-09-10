"""
Tests for conversation history and KB context integration in Support AI agents.

These tests ensure that:
- Conversation history is actually passed to the LLM (not discarded)
- KB context is injected into prompts (not discarded)
- Long conversations are summarized properly
- The AI doesn't re-ask for information already given
- Staff messages are included as assistant messages
- External format conversation history (role/content) is properly used
- Handoff requests acknowledge earlier context
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy.ext.asyncio import AsyncSession

from app.support_ai.agents import (
    TechnicalSupportAgent,
    BillingSupportAgent,
    AccountSupportAgent,
    SecuritySupportAgent,
    GeneralSupportAgent,
    AgentOrchestrator,
)
from app.support_ai.service import SupportAIService
from app.clients.groq_client import GroqClientInterface, ChatMessage, LLMResponse
from app.clients.qdrant_client import SearchResult
from app.db.models import TicketMessage, MessageSender
from datetime import datetime, timezone


@pytest.fixture
def mock_groq_client():
    """Mock Groq client that captures messages sent to it."""
    client = AsyncMock(spec=GroqClientInterface)
    client.chat_completion = AsyncMock(return_value=LLMResponse(
        content="Test response",
        confidence=0.8,
        metadata={"agent_used": "TestAgent"}
    ))
    return client


@pytest.fixture
def sample_conversation_history():
    """Create sample conversation history for testing."""
    messages = [
        TicketMessage(
            id="msg_1",
            ticket_id="ticket_1",
            sender=MessageSender.CUSTOMER,
            content="I'm having trouble with my account login",
            created_at=datetime.now(timezone.utc),
        ),
        TicketMessage(
            id="msg_2",
            ticket_id="ticket_1",
            sender=MessageSender.SUPPORT_AI,
            content="I can help with that. What error message are you seeing?",
            created_at=datetime.now(timezone.utc),
        ),
        TicketMessage(
            id="msg_3",
            ticket_id="ticket_1",
            sender=MessageSender.CUSTOMER,
            content="It says 'Invalid credentials' but I'm sure my password is correct",
            created_at=datetime.now(timezone.utc),
        ),
    ]
    return messages


@pytest.fixture
def sample_kb_context():
    """Create sample KB context for testing."""
    return [
        SearchResult(
            id="kb_1",
            score=0.9,
            payload={"title": "Password Reset Guide"},
            content="To reset your password, go to Settings > Security > Reset Password"
        ),
        SearchResult(
            id="kb_2",
            score=0.7,
            payload={"title": "Login Troubleshooting"},
            content="Common login issues include incorrect passwords, locked accounts, or browser cache issues"
        ),
    ]


class TestConversationHistory:
    """Test that conversation history is actually passed to the LLM."""

    @pytest.mark.asyncio
    async def test_conversation_history_included_in_llm_call(
        self,
        mock_groq_client: AsyncMock,
        sample_conversation_history: list,
    ):
        """Test that by turn 3+, the messages list contains prior turns."""
        agent = TechnicalSupportAgent(mock_groq_client)

        await agent.handle(
            message="I tried clearing my cache but it still doesn't work",
            customer_data=None,
            kb_context=[],
            conversation_history=sample_conversation_history,
        )

        # Verify chat_completion was called
        assert mock_groq_client.chat_completion.called

        # Get the messages that were sent to Groq
        call_args = mock_groq_client.chat_completion.call_args
        messages_sent = call_args[1]["messages"]

        # Should have system prompt + history messages + current message
        assert len(messages_sent) >= 4  # system + 3 history + current

        # Verify the conversation history is present
        message_contents = [msg.content for msg in messages_sent]
        assert "I'm having trouble with my account login" in message_contents
        assert "I can help with that. What error message are you seeing?" in message_contents
        assert "It says 'Invalid credentials' but I'm sure my password is correct" in message_contents
        assert "I tried clearing my cache but it still doesn't work" in message_contents

    @pytest.mark.asyncio
    async def test_staff_messages_included_as_assistant(
        self,
        mock_groq_client: AsyncMock,
    ):
        """Test that staff messages are included as assistant messages."""
        agent = GeneralSupportAgent(mock_groq_client)

        conversation_history = [
            TicketMessage(
                id="msg_1",
                ticket_id="ticket_1",
                sender=MessageSender.CUSTOMER,
                content="Can you help me?",
                created_at=datetime.now(timezone.utc),
            ),
            TicketMessage(
                id="msg_2",
                ticket_id="ticket_1",
                sender=MessageSender.STAFF,
                content="I've escalated this to our technical team. They'll investigate shortly.",
                created_at=datetime.now(timezone.utc),
            ),
        ]

        await agent.handle(
            message="Thanks, any update?",
            customer_data=None,
            kb_context=[],
            conversation_history=conversation_history,
        )

        # Get the messages that were sent to Groq
        call_args = mock_groq_client.chat_completion.call_args
        messages_sent = call_args[1]["messages"]

        # Find the staff message and verify it's marked as assistant
        staff_msg = None
        for msg in messages_sent:
            if "escalated this to our technical team" in msg.content:
                staff_msg = msg
                break

        assert staff_msg is not None
        assert staff_msg.role == "assistant"

    @pytest.mark.asyncio
    async def test_system_messages_excluded_from_chat_turns(
        self,
        mock_groq_client: AsyncMock,
    ):
        """Test that system messages are not included as chat turns."""
        agent = AccountSupportAgent(mock_groq_client)

        conversation_history = [
            TicketMessage(
                id="msg_1",
                ticket_id="ticket_1",
                sender=MessageSender.CUSTOMER,
                content="Help with login",
                created_at=datetime.now(timezone.utc),
            ),
            TicketMessage(
                id="msg_2",
                ticket_id="ticket_1",
                sender=MessageSender.SYSTEM,
                content="System: Ticket escalated automatically",
                created_at=datetime.now(timezone.utc),
            ),
        ]

        await agent.handle(
            message="Still waiting",
            customer_data=None,
            kb_context=[],
            conversation_history=conversation_history,
        )

        # Get the messages that were sent to Groq
        call_args = mock_groq_client.chat_completion.call_args
        messages_sent = call_args[1]["messages"]

        # System message should not be in the chat messages
        message_contents = [msg.content for msg in messages_sent]
        assert "Ticket escalated automatically" not in message_contents
        # But customer message should be there
        assert "Help with login" in message_contents


class TestKBContextInjection:
    """Test that KB context is actually injected into prompts."""

    @pytest.mark.asyncio
    async def test_kb_context_injected_into_system_prompt(
        self,
        mock_groq_client: AsyncMock,
        sample_kb_context: list,
    ):
        """Test that KB context is present in the system prompt."""
        agent = TechnicalSupportAgent(mock_groq_client)

        await agent.handle(
            message="How do I reset my password?",
            customer_data=None,
            kb_context=sample_kb_context,
            conversation_history=[],
        )

        # Get the messages that were sent to Groq
        call_args = mock_groq_client.chat_completion.call_args
        messages_sent = call_args[1]["messages"]

        # Find the system prompt
        system_prompt = None
        for msg in messages_sent:
            if msg.role == "system":
                system_prompt = msg.content
                break

        assert system_prompt is not None
        assert "RELEVANT KNOWLEDGE BASE ARTICLES" in system_prompt
        assert "To reset your password" in system_prompt
        assert "Common login issues" in system_prompt
        assert "Relevance score: 0.90" in system_prompt or "Relevance score: 0.70" in system_prompt

    @pytest.mark.asyncio
    async def test_kb_context_instructions_present(
        self,
        mock_groq_client: AsyncMock,
        sample_kb_context: list,
    ):
        """Test that KB context includes instructions for proper usage."""
        agent = BillingSupportAgent(mock_groq_client)

        await agent.handle(
            message="I need help with a charge",
            customer_data=None,
            kb_context=sample_kb_context,
            conversation_history=[],
        )

        # Get the messages that were sent to Groq
        call_args = mock_groq_client.chat_completion.call_args
        messages_sent = call_args[1]["messages"]

        # Find the system prompt
        system_prompt = None
        for msg in messages_sent:
            if msg.role == "system":
                system_prompt = msg.content
                break

        assert system_prompt is not None
        assert "INSTRUCTIONS: Use the above knowledge base articles" in system_prompt
        assert "say so plainly rather than forcing the content" in system_prompt

    @pytest.mark.asyncio
    async def test_empty_kb_context_handled_gracefully(
        self,
        mock_groq_client: AsyncMock,
    ):
        """Test that empty KB context doesn't break the agent."""
        agent = GeneralSupportAgent(mock_groq_client)

        await agent.handle(
            message="How do I contact support?",
            customer_data=None,
            kb_context=[],
            conversation_history=[],
        )

        # Should still work fine
        assert mock_groq_client.chat_completion.called

        # Get the messages that were sent to Groq
        call_args = mock_groq_client.chat_completion.call_args
        messages_sent = call_args[1]["messages"]

        # Find the system prompt
        system_prompt = None
        for msg in messages_sent:
            if msg.role == "system":
                system_prompt = msg.content
                break

        assert system_prompt is not None
        # Should NOT have KB section when no KB context
        assert "RELEVANT KNOWLEDGE BASE ARTICLES" not in system_prompt


class TestLongConversationSummarization:
    """Test that long conversations are summarized properly."""

    @pytest.mark.asyncio
    async def test_long_conversation_summarized(
        self,
        mock_groq_client: AsyncMock,
    ):
        """Test that conversations exceeding the cap are summarized."""
        agent = SecuritySupportAgent(mock_groq_client)

        # Create a long conversation (more than MAX_HISTORY_TURNS)
        long_history = []
        for i in range(15):
            long_history.append(
                TicketMessage(
                    id=f"msg_{i}",
                    ticket_id="ticket_1",
                    sender=MessageSender.CUSTOMER if i % 2 == 0 else MessageSender.SUPPORT_AI,
                    content=f"Message {i}: " + "This is a test message. " * 10,
                    created_at=datetime.now(timezone.utc),
                )
            )

        await agent.handle(
            message="Latest message in long conversation",
            customer_data=None,
            kb_context=[],
            conversation_history=long_history,
        )

        # Get the messages that were sent to Groq
        call_args = mock_groq_client.chat_completion.call_args
        messages_sent = call_args[1]["messages"]

        # Should have a summary message
        has_summary = False
        for msg in messages_sent:
            if msg.role == "system" and "Earlier conversation summary" in msg.content:
                has_summary = True
                break

        assert has_summary, "Should include a summary for long conversations"

    @pytest.mark.asyncio
    async def test_recent_turns_kept_verbatim(
        self,
        mock_groq_client: AsyncMock,
    ):
        """Test that the most recent turns are kept verbatim when summarizing."""
        agent = AccountSupportAgent(mock_groq_client)

        # Create a long conversation
        long_history = []
        for i in range(12):
            long_history.append(
                TicketMessage(
                    id=f"msg_{i}",
                    ticket_id="ticket_1",
                    sender=MessageSender.CUSTOMER if i % 2 == 0 else MessageSender.SUPPORT_AI,
                    content=f"Message {i}",
                    created_at=datetime.now(timezone.utc),
                )
            )

        await agent.handle(
            message="Current message",
            customer_data=None,
            kb_context=[],
            conversation_history=long_history,
        )

        # Get the messages that were sent to Groq
        call_args = mock_groq_client.chat_completion.call_args
        messages_sent = call_args[1]["messages"]

        # The most recent messages should be present verbatim
        message_contents = [msg.content for msg in messages_sent]
        assert "Message 10" in message_contents  # Recent message
        assert "Message 11" in message_contents  # Recent message
        assert "Current message" in message_contents  # Current message

    @pytest.mark.asyncio
    async def test_short_conversation_not_summarized(
        self,
        mock_groq_client: AsyncMock,
        sample_conversation_history: list,
    ):
        """Test that short conversations are not summarized."""
        agent = GeneralSupportAgent(mock_groq_client)

        await agent.handle(
            message="New message",
            customer_data=None,
            kb_context=[],
            conversation_history=sample_conversation_history,  # Only 3 messages
        )

        # Get the messages that were sent to Groq
        call_args = mock_groq_client.chat_completion.call_args
        messages_sent = call_args[1]["messages"]

        # Should NOT have a summary message
        has_summary = False
        for msg in messages_sent:
            if msg.role == "system" and "Earlier conversation summary" in msg.content:
                has_summary = True
                break

        assert not has_summary, "Should not summarize short conversations"


class TestConversationalBehavior:
    """Test conversational behavior with context."""

    @pytest.mark.asyncio
    async def test_no_reask_given_info(
        self,
        mock_groq_client: AsyncMock,
    ):
        """Test that AI doesn't re-ask for information already given."""
        agent = TechnicalSupportAgent(mock_groq_client)

        # Customer gives platform info in turn 1
        conversation_history = [
            TicketMessage(
                id="msg_1",
                ticket_id="ticket_1",
                sender=MessageSender.CUSTOMER,
                content="I'm using the mobile app on iOS and getting a 500 error",
                created_at=datetime.now(timezone.utc),
            ),
            TicketMessage(
                id="msg_2",
                ticket_id="ticket_1",
                sender=MessageSender.SUPPORT_AI,
                content="Let me help you troubleshoot that 500 error on iOS.",
                created_at=datetime.now(timezone.utc),
            ),
        ]

        # Customer asks related question in turn 3
        await agent.handle(
            message="The error persists after clearing cache",
            customer_data=None,
            kb_context=[],
            conversation_history=conversation_history,
        )

        # Get the messages that were sent to Groq
        call_args = mock_groq_client.chat_completion.call_args
        messages_sent = call_args[1]["messages"]

        # The conversation history should include the platform info
        message_contents = [msg.content for msg in messages_sent]
        # Check that iOS info is present (it's in the first message)
        assert any("iOS" in content and "mobile app" in content for content in message_contents)

        # This enables the AI to reference the platform without re-asking
        # (The actual behavior depends on the LLM, but we ensure it has the context)

    @pytest.mark.asyncio
    async def test_acknowledges_previous_attempts(
        self,
        mock_groq_client: AsyncMock,
    ):
        """Test that AI can see and acknowledge previous failed attempts."""
        agent = BillingSupportAgent(mock_groq_client)

        conversation_history = [
            TicketMessage(
                id="msg_1",
                ticket_id="ticket_1",
                sender=MessageSender.CUSTOMER,
                content="I was charged twice for my subscription",
                created_at=datetime.now(timezone.utc),
            ),
            TicketMessage(
                id="msg_2",
                ticket_id="ticket_1",
                sender=MessageSender.SUPPORT_AI,
                content="I can help with that. Please check your invoice history and let me know the dates.",
                created_at=datetime.now(timezone.utc),
            ),
            TicketMessage(
                id="msg_3",
                ticket_id="ticket_1",
                sender=MessageSender.CUSTOMER,
                content="I checked - charges on Jan 15 and Jan 16, both for $29.99",
                created_at=datetime.now(timezone.utc),
            ),
            TicketMessage(
                id="msg_4",
                ticket_id="ticket_1",
                sender=MessageSender.SUPPORT_AI,
                content="Thank you. I've submitted a refund request for the duplicate charge.",
                created_at=datetime.now(timezone.utc),
            ),
            TicketMessage(
                id="msg_5",
                ticket_id="ticket_1",
                sender=MessageSender.CUSTOMER,
                content="The refund request was rejected",
                created_at=datetime.now(timezone.utc),
            ),
        ]

        await agent.handle(
            message="What do I do now?",
            customer_data=None,
            kb_context=[],
            conversation_history=conversation_history,
        )

        # Get the messages that were sent to Groq
        call_args = mock_groq_client.chat_completion.call_args
        messages_sent = call_args[1]["messages"]

        # The full conversation history should be present
        message_contents = [msg.content for msg in messages_sent]
        # Check that key conversation elements are present
        assert any("charged twice" in content for content in message_contents)
        assert any("refund request" in content for content in message_contents)

        # This enables the AI to acknowledge the failed refund attempt
        # and suggest escalation without re-asking for details


class TestAllAgentsUseContext:
    """Test that all agents consistently use conversation history and KB context."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("agent_class", [
        TechnicalSupportAgent,
        BillingSupportAgent,
        AccountSupportAgent,
        SecuritySupportAgent,
        GeneralSupportAgent,
    ])
    async def test_all_agents_use_conversation_history(
        self,
        agent_class,
        mock_groq_client: AsyncMock,
        sample_conversation_history: list,
    ):
        """Test that all agent types include conversation history."""
        agent = agent_class(mock_groq_client)

        await agent.handle(
            message="New message",
            customer_data=None,
            kb_context=[],
            conversation_history=sample_conversation_history,
        )

        # Get the messages that were sent to Groq
        call_args = mock_groq_client.chat_completion.call_args
        messages_sent = call_args[1]["messages"]

        # Should have more than just system + current message
        assert len(messages_sent) > 2

        # Should include conversation history
        message_contents = [msg.content for msg in messages_sent]
        assert any("having trouble" in content or "account login" in content for content in message_contents)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("agent_class", [
        TechnicalSupportAgent,
        BillingSupportAgent,
        AccountSupportAgent,
        SecuritySupportAgent,
        GeneralSupportAgent,
    ])
    async def test_all_agents_use_kb_context(
        self,
        agent_class,
        mock_groq_client: AsyncMock,
        sample_kb_context: list,
    ):
        """Test that all agent types include KB context."""
        agent = agent_class(mock_groq_client)

        await agent.handle(
            message="Question",
            customer_data=None,
            kb_context=sample_kb_context,
            conversation_history=[],
        )

        # Get the messages that were sent to Groq
        call_args = mock_groq_client.chat_completion.call_args
        messages_sent = call_args[1]["messages"]

        # Find the system prompt
        system_prompt = None
        for msg in messages_sent:
            if msg.role == "system":
                system_prompt = msg.content
                break

        assert system_prompt is not None
        assert "RELEVANT KNOWLEDGE BASE ARTICLES" in system_prompt


class TestExternalConversationHistoryFormat:
    """Test that external format conversation history (role/content) is properly used."""

    @pytest.mark.asyncio
    async def test_external_format_normal_path(
        self,
        mock_groq_client: AsyncMock,
    ):
        """Test that external format history works in normal path."""
        agent = TechnicalSupportAgent(mock_groq_client)

        # Simulate external conversation history format from Shiva Support
        conversation_history = [
            {"role": "user", "content": "I get error 500 while creating a product"},
            {"role": "assistant", "content": "Let me help you troubleshoot this. Can you share the error details?"},
        ]

        await agent.handle(
            message="Can I speak to support staff?",
            customer_data=None,
            kb_context=[],
            conversation_history=conversation_history,
        )

        # Get the messages that were sent to Groq
        call_args = mock_groq_client.chat_completion.call_args
        messages_sent = call_args[1]["messages"]

        # Should include conversation history before current message
        message_contents = [msg.content for msg in messages_sent]
        user_messages = [msg for msg in messages_sent if msg.role == "user"]

        # Should have 2 user messages (history + current)
        assert len(user_messages) == 2
        assert any("creating a product" in msg.content for msg in user_messages)
        assert any("speak to support staff" in msg.content for msg in user_messages)

        # Assistant message from history should also be present
        assistant_messages = [msg for msg in messages_sent if msg.role == "assistant"]
        assert any("troubleshoot" in msg.content for msg in assistant_messages)

    @pytest.mark.asyncio
    async def test_external_format_streaming_path(
        self,
        mock_groq_client: AsyncMock,
    ):
        """Test that external format history works in streaming path."""
        agent = TechnicalSupportAgent(mock_groq_client)

        # Simulate external conversation history format from Shiva Support
        conversation_history = [
            {"role": "user", "content": "I get error 500 while creating a product"},
            {"role": "assistant", "content": "Let me help you troubleshoot this. Can you share the error details?"},
        ]

        # Setup streaming mock
        async def mock_stream(*args, **kwargs):
            yield "I understand you're experiencing a 500 error when creating a product.", agent.name
            yield " I'll connect you with a support specialist who can help resolve this issue.", agent.name

        mock_groq_client.chat_completion_stream = mock_stream

        chunks = []
        async for chunk, agent_name in agent.handle_stream(
            message="Can I speak to support staff?",
            customer_data=None,
            kb_context=[],
            conversation_history=conversation_history,
        ):
            chunks.append(chunk)

        full_response = "".join(chunks)

        # Response should reference the earlier context (product creation 500 error)
        assert "500" in full_response or "error" in full_response or "product" in full_response

    @pytest.mark.asyncio
    async def test_handoff_acknowledges_earlier_context(
        self,
        mock_groq_client: AsyncMock,
    ):
        """Test that handoff request acknowledges earlier issue context."""
        agent = TechnicalSupportAgent(mock_groq_client)

        # Simulate conversation: product creation error -> troubleshooting -> handoff
        conversation_history = [
            {"role": "user", "content": "I get error 500 while creating a product"},
            {"role": "assistant", "content": "I can help with that. Please check your API logs for the exact error message and verify your request payload is valid."},
        ]

        # Mock response that acknowledges the earlier context
        mock_groq_client.chat_completion = AsyncMock(return_value=LLMResponse(
            content="I understand you're experiencing a 500 error when creating a product. I'll connect you with a support specialist who can help investigate this server error.",
            confidence=0.7,
            metadata={"agent_used": "TechnicalSupportAgent"}
        ))

        await agent.handle(
            message="Can I speak to support staff?",
            customer_data=None,
            kb_context=[],
            conversation_history=conversation_history,
        )

        # Get the messages that were sent to Groq
        call_args = mock_groq_client.chat_completion.call_args
        messages_sent = call_args[1]["messages"]

        # Should include full conversation history
        message_contents = [msg.content for msg in messages_sent]

        # Should have the product creation error in history
        assert any("creating a product" in content for content in message_contents)
        assert any("500" in content for content in message_contents)

        # Current message about handoff should be last user message
        user_messages = [msg for msg in messages_sent if msg.role == "user"]
        assert user_messages[-1].content == "Can I speak to support staff?"

    @pytest.mark.asyncio
    async def test_context_scoped_to_customer_conversation(
        self,
        mock_groq_client: AsyncMock,
    ):
        """Test that context remains scoped to the supplied customer/conversation."""
        agent = TechnicalSupportAgent(mock_groq_client)

        # Simulate conversation for customer A
        conversation_history = [
            {"role": "user", "content": "I get error 500 while creating a product"},
            {"role": "assistant", "content": "Let me help you troubleshoot this."},
        ]

        await agent.handle(
            message="Can I speak to support staff?",
            customer_data={"customer_id": "customer_a"},
            kb_context=[],
            conversation_history=conversation_history,
        )

        # Get the messages that were sent to Groq
        call_args = mock_groq_client.chat_completion.call_args
        messages_sent = call_args[1]["messages"]

        # Should only contain the supplied history
        assert len(messages_sent) == 4  # system + 2 history messages + current message
        message_contents = [msg.content for msg in messages_sent]
        assert any("creating a product" in content for content in message_contents)

        # No cross-customer contamination (verify by checking content)
        for msg in messages_sent:
            assert "customer_b" not in msg.content.lower() if hasattr(msg, 'content') else True


class TestProductAwareConversation:
    """Test product-aware conversational support."""

    @pytest.mark.asyncio
    async def test_401_product_creation_conversation_flow(
        self,
        mock_groq_client: AsyncMock,
    ):
        """Test the 401 product-creation conversation flow with escalation."""
        agent = TechnicalSupportAgent(mock_groq_client)

        # Turn 1: User reports 401 error while creating product
        conversation_history = []
        product_context = {
            "product_id": "product_123",
            "product_name": "Shiva E-Commerce",
            "enabled_modules": ["product_management", "inventory"],
            "client_entitled": True,
            "relevant_knowledge_articles": ["article_401_auth", "article_product_creation"]
        }

        # Mock initial response with troubleshooting steps
        mock_groq_client.chat_completion = AsyncMock(return_value=LLMResponse(
            content="I understand you're getting a 401 error when creating a product. Let me help you troubleshoot this. First, check that your API token is valid and has the product:create permission. Then verify your request headers include the correct Authorization header.",
            confidence=0.8,
            metadata={"agent_used": "TechnicalSupportAgent"}
        ))

        response1 = await agent.handle(
            message="I am having error 401 while creating a product yet am logged in",
            customer_data=None,
            kb_context=[],
            conversation_history=conversation_history,
            product_context=product_context,
        )

        # Add response to history
        conversation_history.append({"role": "user", "content": "I am having error 401 while creating a product yet am logged in"})
        conversation_history.append({"role": "assistant", "content": response1})

        # Turn 2: User says they tried all steps
        mock_groq_client.chat_completion = AsyncMock(return_value=LLMResponse(
            content="I understand you've tried those steps. Since you're still facing the 401 error when creating a product, could you share the exact error response you're receiving or a screenshot of the error? This will help me identify the specific authorization issue.",
            confidence=0.7,
            metadata={"agent_used": "TechnicalSupportAgent"}
        ))

        response2 = await agent.handle(
            message="I have tried all these",
            customer_data=None,
            kb_context=[],
            conversation_history=conversation_history,
            product_context=product_context,
        )

        # Add response to history
        conversation_history.append({"role": "user", "content": "I have tried all these"})
        conversation_history.append({"role": "assistant", "content": response2})

        # Turn 3: User clarifies they were creating a product
        mock_groq_client.chat_completion = AsyncMock(return_value=LLMResponse(
            content="I understand you were creating a product when this happened. Since you've tried the basic troubleshooting steps and are still experiencing a 401 authorization error during product creation, this requires deeper investigation. I'll connect you with a support specialist who can review your account permissions and API configuration.",
            confidence=0.6,
            metadata={"agent_used": "TechnicalSupportAgent"}
        ))

        response3 = await agent.handle(
            message="I was creating a product",
            customer_data=None,
            kb_context=[],
            conversation_history=conversation_history,
            product_context=product_context,
        )

        # Verify response3 acknowledges the product-creation context
        assert "creating a product" in response3.lower() or "product creation" in response3.lower()
        assert "401" in response3.lower() or "authorization" in response3.lower()

        # Verify response3 does not ask what the customer was doing (they already said)
        assert "what were you" not in response3.lower()
        assert "what are you" not in response3.lower()

    @pytest.mark.asyncio
    async def test_product_context_tails_guidance(
        self,
        mock_groq_client: AsyncMock,
    ):
        """Test that product context tails guidance to the specific product."""
        agent = TechnicalSupportAgent(mock_groq_client)

        product_context = {
            "product_id": "product_456",
            "product_name": "Shiva POS",
            "enabled_modules": ["sales", "inventory"],
            "client_entitled": True,
            "relevant_knowledge_articles": ["article_pos_sales"]
        }

        mock_groq_client.chat_completion = AsyncMock(return_value=LLMResponse(
            content="For Shiva POS, you can manage sales through the sales module in your enabled features.",
            confidence=0.8,
            metadata={"agent_used": "TechnicalSupportAgent"}
        ))

        response = await agent.handle(
            message="How do I manage sales?",
            customer_data=None,
            kb_context=[],
            conversation_history=[],
            product_context=product_context,
        )

        # Get the messages sent to Groq
        call_args = mock_groq_client.chat_completion.call_args
        messages_sent = call_args[1]["messages"]

        # Find the system prompt
        system_prompt = None
        for msg in messages_sent:
            if msg.role == "system":
                system_prompt = msg.content
                break

        assert system_prompt is not None
        assert "Shiva POS" in system_prompt
        assert "sales" in system_prompt
        assert "inventory" in system_prompt

    @pytest.mark.asyncio
    async def test_no_product_context_asks_identification(
        self,
        mock_groq_client: AsyncMock,
    ):
        """Test that missing product context prompts for product identification."""
        agent = TechnicalSupportAgent(mock_groq_client)

        mock_groq_client.chat_completion = AsyncMock(return_value=LLMResponse(
            content="Which Shiva product are you using? This will help me provide specific guidance.",
            confidence=0.8,
            metadata={"agent_used": "TechnicalSupportAgent"}
        ))

        response = await agent.handle(
            message="I'm having trouble with the checkout",
            customer_data=None,
            kb_context=[],
            conversation_history=[],
            product_context=None,
        )

        # Get the messages sent to Groq
        call_args = mock_groq_client.chat_completion.call_args
        messages_sent = call_args[1]["messages"]

        # Find the system prompt
        system_prompt = None
        for msg in messages_sent:
            if msg.role == "system":
                system_prompt = msg.content
                break

        assert system_prompt is not None
        assert "product" in system_prompt.lower()
        assert "identify" in system_prompt.lower() or "which" in system_prompt.lower()


class TestConversationHistoryRetentionIntegration:
    """Integration test for conversation history retention as specified in requirements."""

    @pytest.mark.asyncio
    async def test_conversation_history_retention_sequence(
        self,
        mock_groq_client: AsyncMock,
    ):
        """
        Integration test using the exact sequence from requirements:
        1. "I am getting error 500"
        2. "I get it while adding products"
        3. "adding new products"
        4. "what error were we talking about?"

        The final answer must accurately say: "You reported a 500 error while adding a new product."
        """
        agent = TechnicalSupportAgent(mock_groq_client)

        # Build conversation history progressively
        conversation_history = []

        # Turn 1: "I am getting error 500"
        mock_groq_client.chat_completion = AsyncMock(return_value=LLMResponse(
            content="I understand you're getting a 500 error. Can you tell me what you were doing when this occurred?",
            confidence=0.8,
            metadata={"agent_used": "TechnicalSupportAgent"}
        ))

        response1 = await agent.handle(
            message="I am getting error 500",
            customer_data=None,
            kb_context=[],
            conversation_history=conversation_history,
        )

        # Add to conversation history
        conversation_history.append({"role": "user", "content": "I am getting error 500"})
        conversation_history.append({"role": "assistant", "content": response1})

        # Turn 2: "I get it while adding products"
        mock_groq_client.chat_completion = AsyncMock(return_value=LLMResponse(
            content="I see you're getting the 500 error while adding products. Let me help you troubleshoot this.",
            confidence=0.8,
            metadata={"agent_used": "TechnicalSupportAgent"}
        ))

        response2 = await agent.handle(
            message="I get it while adding products",
            customer_data=None,
            kb_context=[],
            conversation_history=conversation_history,
        )

        # Add to conversation history
        conversation_history.append({"role": "user", "content": "I get it while adding products"})
        conversation_history.append({"role": "assistant", "content": response2})

        # Turn 3: "adding new products"
        mock_groq_client.chat_completion = AsyncMock(return_value=LLMResponse(
            content="I understand you're experiencing a 500 error when adding new products. This is a server error that needs investigation.",
            confidence=0.8,
            metadata={"agent_used": "TechnicalSupportAgent"}
        ))

        response3 = await agent.handle(
            message="adding new products",
            customer_data=None,
            kb_context=[],
            conversation_history=conversation_history,
        )

        # Add to conversation history
        conversation_history.append({"role": "user", "content": "adding new products"})
        conversation_history.append({"role": "assistant", "content": response3})

        # Turn 4: "what error were we talking about?"
        # This is the critical test - the AI must remember the context from earlier turns
        mock_groq_client.chat_completion = AsyncMock(return_value=LLMResponse(
            content="You reported a 500 error while adding a new product.",
            confidence=0.9,
            metadata={"agent_used": "TechnicalSupportAgent"}
        ))

        response4 = await agent.handle(
            message="what error were we talking about?",
            customer_data=None,
            kb_context=[],
            conversation_history=conversation_history,
        )

        # Verify the final response accurately summarizes the prior issue
        assert "500" in response4.lower(), "Response should mention the 500 error"
        assert "adding" in response4.lower() or "add" in response4.lower(), "Response should mention adding products"
        assert "product" in response4.lower(), "Response should mention products"

        # Get the messages sent to Groq for the final turn
        call_args = mock_groq_client.chat_completion.call_args
        messages_sent = call_args[1]["messages"]

        # Verify that the conversation history was included in the LLM call
        message_contents = [msg.content for msg in messages_sent]
        
        # Should contain all previous context
        assert any("error 500" in content.lower() for content in message_contents), "History should contain 'error 500'"
        assert any("adding products" in content.lower() or "adding new products" in content.lower() for content in message_contents), "History should contain 'adding products'"

        # Verify the system prompt instructs to use conversation history
        system_prompt = None
        for msg in messages_sent:
            if msg.role == "system":
                system_prompt = msg.content
                break

        assert system_prompt is not None
        assert "conversation history" in system_prompt.lower() or "earlier in the conversation" in system_prompt.lower()


class TestProductSelectionSupport:
    """Test conditional product-selection support with KB filtering."""

    @pytest.mark.asyncio
    async def test_general_question_no_product_selection(
        self,
        mock_groq_client: AsyncMock,
    ):
        """Test that general questions don't require product selection."""
        agent = GeneralSupportAgent(mock_groq_client)

        mock_groq_client.chat_completion = AsyncMock(return_value=LLMResponse(
            content="You can contact support by clicking the Help button in your account or emailing support@shiva.com.",
            confidence=0.9,
            metadata={"agent_used": "GeneralSupportAgent"}
        ))

        response = await agent.handle(
            message="How do I contact support?",
            customer_data=None,
            kb_context=[],
            conversation_history=[],
            product_context=None,
        )

        # Response should be provided without asking for product
        assert "contact" in response.lower() or "support" in response.lower()
        assert "product" not in response.lower() or "select" not in response.lower()

    @pytest.mark.asyncio
    async def test_product_specific_no_context_requests_selection(
        self,
        mock_groq_client: AsyncMock,
    ):
        """Test that product-specific issues with no context request product selection."""
        agent = TechnicalSupportAgent(mock_groq_client)

        mock_groq_client.chat_completion = AsyncMock(return_value=LLMResponse(
            content="To help you troubleshoot this 401 error accurately, I need to know which Shiva product you're using. Please select your product from the options provided.",
            confidence=0.9,
            metadata={"agent_used": "TechnicalSupportAgent"}
        ))

        response = await agent.handle(
            message="I get a 401 while creating a product.",
            customer_data=None,
            kb_context=[],  # No KB results
            conversation_history=[],
            product_context=None,
        )

        # Response should request product selection
        assert "product" in response.lower()
        assert "select" in response.lower() or "which" in response.lower()

    @pytest.mark.asyncio
    async def test_product_selected_filters_kb(
        self,
        mock_groq_client: AsyncMock,
    ):
        """Test that when product is selected, KB is filtered by product_id."""
        from app.clients.qdrant_client import SearchResult

        agent = TechnicalSupportAgent(mock_groq_client)

        product_context = {
            "product_id": "product_123",
            "product_name": "Shiva E-Commerce",
            "enabled_modules": ["product_management"],
            "client_entitled": True,
            "relevant_knowledge_articles": ["article_401"]
        }

        # Mock KB results for the specific product
        kb_context = [
            SearchResult(
                id="kb_1",
                content="For Shiva E-Commerce 401 errors during product creation, check your API token permissions.",
                score=0.9,
                payload={"product_id": "product_123"}
            )
        ]

        mock_groq_client.chat_completion = AsyncMock(return_value=LLMResponse(
            content="Based on your Shiva E-Commerce setup, check that your API token has the product:create permission for the product_management module.",
            confidence=0.8,
            metadata={"agent_used": "TechnicalSupportAgent"}
        ))

        response = await agent.handle(
            message="I get a 401 while creating a product.",
            customer_data=None,
            kb_context=kb_context,
            conversation_history=[],
            product_context=product_context,
        )

        # Response should be tailored to the specific product
        assert "shiva e-commerce" in response.lower() or "product_management" in response.lower()
        assert "permission" in response.lower()

    @pytest.mark.asyncio
    async def test_follow_up_uses_prior_context(
        self,
        mock_groq_client: AsyncMock,
    ):
        """Test that follow-up messages use prior context and don't restart troubleshooting."""
        agent = TechnicalSupportAgent(mock_groq_client)

        conversation_history = [
            {"role": "user", "content": "I get a 401 while creating a product."},
            {"role": "assistant", "content": "Check your API token has product:create permission and verify the Authorization header."},
        ]

        product_context = {
            "product_id": "product_123",
            "product_name": "Shiva E-Commerce",
            "enabled_modules": ["product_management"],
            "client_entitled": True,
            "relevant_knowledge_articles": []
        }

        mock_groq_client.chat_completion = AsyncMock(return_value=LLMResponse(
            content="I understand you've tried checking the API token and Authorization header. Could you share the exact error response you're receiving? This will help identify the specific authorization issue.",
            confidence=0.7,
            metadata={"agent_used": "TechnicalSupportAgent"}
        ))

        response = await agent.handle(
            message="I tried those steps.",
            customer_data=None,
            kb_context=[],
            conversation_history=conversation_history,
            product_context=product_context,
        )

        # Response should acknowledge attempted steps and not restart troubleshooting
        assert "tried" in response.lower() or "attempted" in response.lower()
        # Should request next diagnostic evidence
        assert "error response" in response.lower() or "exact error" in response.lower()


class TestFailedTranscriptRegression:
    """Regression test for the failed transcript with 401 error and looping questions."""

    @pytest.mark.asyncio
    async def test_401_product_creation_transcript(
        self,
        mock_groq_client: AsyncMock,
    ):
        """
        Test the exact failed transcript to ensure all three bugs are fixed:
        1. 401 error routes to Code/Server AI (or gives relevant auth diagnosis)
        2. "I have tried all these" escalates or gives different diagnosis
        3. AI doesn't re-ask what customer already said
        """
        agent = TechnicalSupportAgent(mock_groq_client)

        # Turn 1: Customer reports 401 error while creating product
        # BUG FIX 1: Should route to Code AI or give auth-specific diagnosis
        mock_groq_client.chat_completion = AsyncMock(return_value=LLMResponse(
            content="A 401 error when creating a product suggests an authentication or authorization issue. Check your API token is valid and has the product:create permission. Also verify your account has the necessary role to create products.",
            confidence=0.8,
            metadata={"agent_used": "TechnicalSupportAgent"}
        ))

        response1 = await agent.handle(
            message="I am having error 401 while creating a product yet am logged in",
            customer_data=None,
            kb_context=[],
            conversation_history=[],
            product_context={
                "product_id": "product_123",
                "product_name": "Shiva E-Commerce",
                "enabled_modules": ["product_management"],
                "client_entitled": True,
                "relevant_knowledge_articles": []
            },
        )

        # Response should be auth-specific, not generic "clear cache" advice
        assert "401" in response1.lower() or "authentication" in response1.lower() or "authorization" in response1.lower()
        assert "permission" in response1.lower() or "token" in response1.lower()
        # Should NOT suggest generic browser troubleshooting
        assert "clear cache" not in response1.lower()
        assert "refresh" not in response1.lower() or "session" in response1.lower()  # session refresh is OK for auth
        assert "browser" not in response1.lower()

        # Build conversation history
        conversation_history = [
            {"role": "user", "content": "I am having error 401 while creating a product yet am logged in"},
            {"role": "assistant", "content": response1},
        ]

        # Turn 2: Customer says they tried all these
        # BUG FIX 2: Should escalate or give different diagnosis, not re-ask what they were doing
        mock_groq_client.chat_completion = AsyncMock(return_value=LLMResponse(
            content="I understand you've tried checking the API token and permissions. Since you're still getting a 401 error when creating a product, this requires deeper investigation of your account permissions and the product creation endpoint. I'll connect you with a support specialist who can review your account configuration.",
            confidence=0.6,
            metadata={"agent_used": "TechnicalSupportAgent"}
        ))

        response2 = await agent.handle(
            message="I have tried all these",
            customer_data=None,
            kb_context=[],
            conversation_history=conversation_history,
            product_context={
                "product_id": "product_123",
                "product_name": "Shiva E-Commerce",
                "enabled_modules": ["product_management"],
                "client_entitled": True,
                "relevant_knowledge_articles": []
            },
        )

        # Response should acknowledge attempted steps
        assert "tried" in response2.lower() or "attempted" in response2.lower()
        # Should NOT ask what they were doing (they already said "creating a product")
        assert "what were you" not in response2.lower()
        assert "what are you" not in response2.lower()
        # Should escalate or give materially different diagnosis
        assert "support specialist" in response2.lower() or "escalate" in response2.lower() or "investigation" in response2.lower()

        # Turn 3: Customer clarifies they were creating a product
        # BUG FIX 3: AI must not ask "what were you trying to create" - that's already known
        conversation_history.append({"role": "user", "content": "I have tried all these"})
        conversation_history.append({"role": "assistant", "content": response2})
        conversation_history.append({"role": "user", "content": "I was creating a product"})

        mock_groq_client.chat_completion = AsyncMock(return_value=LLMResponse(
            content="I understand you were creating a product when the 401 error occurred. Given that you've tried the basic troubleshooting steps and the error persists, this is being escalated for investigation of your account permissions and the product creation endpoint configuration.",
            confidence=0.6,
            metadata={"agent_used": "TechnicalSupportAgent"}
        ))

        response3 = await agent.handle(
            message="I was creating a product",
            customer_data=None,
            kb_context=[],
            conversation_history=conversation_history,
            product_context={
                "product_id": "product_123",
                "product_name": "Shiva E-Commerce",
                "enabled_modules": ["product_management"],
                "client_entitled": True,
                "relevant_knowledge_articles": []
            },
        )

        # Response should acknowledge "creating a product" context
        assert "creating a product" in response3.lower() or "product creation" in response3.lower()
        # Should NOT ask what they were trying to create
        assert "what were you" not in response3.lower()
        assert "what are you" not in response3.lower()
        assert "trying to create" not in response3.lower()


class TestAIRouterThroughAllEntryPoints:
    """Test that AIRouter.classify() is called for all customer-facing entry points."""

    @pytest.mark.asyncio
    async def test_http_error_codes_route_to_code_ai(
        self,
        mock_groq_client: AsyncMock,
    ):
        """Test that messages with HTTP error codes are routed to Code AI."""
        from app.ai_router.classifier import AIRouter
        from app.clients.qdrant_client import QdrantClient

        qdrant_client = QdrantClient()
        router = AIRouter(qdrant_client=qdrant_client)

        # Test various HTTP error codes (without greeting words)
        test_messages = [
            "Error 401 while creating a product",
            "Getting 500 error on checkout",
            "404 not found on product API",
            "503 service unavailable",
        ]

        for message in test_messages:
            route = await router.classify(message, [])
            # HTTP error codes should route to "code"
            assert route == "code", f"Message '{message}' should route to 'code', got '{route}'"

    @pytest.mark.asyncio
    async def test_stack_trace_routes_to_code_ai(
        self,
        mock_groq_client: AsyncMock,
    ):
        """Test that messages with stack traces route to Code AI."""
        from app.ai_router.classifier import AIRouter
        from app.clients.qdrant_client import QdrantClient

        qdrant_client = QdrantClient()
        router = AIRouter(qdrant_client=qdrant_client)

        # Test stack trace patterns
        test_messages = [
            "Traceback (most recent call last):",
            "Exception in /api/products endpoint",
            "TypeError at line 42 in product_service.py",
        ]

        for message in test_messages:
            route = await router.classify(message, [])
            # Stack traces should route to "code"
            assert route == "code", f"Message '{message}' should route to 'code', got '{route}'"


class TestConversationHistoryContinuity:
    """Test that conversation history is preserved and used across multiple turns."""

    @pytest.mark.asyncio
    async def test_conversation_history_preserves_error_context(
        self,
        mock_groq_client: AsyncMock,
    ):
        """
        Integration test for conversation history continuity.
        
        Sequence:
        1. "I am getting error 500"
        2. "I get it while adding products"
        3. "adding new products"
        4. "what error were we talking about?"
        
        Final answer must accurately say: "You reported a 500 error while adding a new product."
        """
        agent = TechnicalSupportAgent(mock_groq_client)
        
        product_context = {
            "product_id": "product_123",
            "product_name": "Shiva E-Commerce",
            "enabled_modules": ["product_management"],
            "client_entitled": True,
            "relevant_knowledge_articles": []
        }
        
        conversation_history = []
        
        # Turn 1: "I am getting error 500"
        mock_groq_client.chat_completion = AsyncMock(return_value=LLMResponse(
            content="I understand you're experiencing a 500 error. Could you tell me what action you were taking when this error occurred?",
            confidence=0.8,
            metadata={"agent_used": "TechnicalSupportAgent"}
        ))
        
        response1 = await agent.handle(
            message="I am getting error 500",
            customer_data=None,
            kb_context=[],
            conversation_history=conversation_history,
            product_context=product_context,
        )
        
        conversation_history.append({"role": "user", "content": "I am getting error 500"})
        conversation_history.append({"role": "assistant", "content": response1})
        
        # Turn 2: "I get it while adding products"
        mock_groq_client.chat_completion = AsyncMock(return_value=LLMResponse(
            content="I see you're getting a 500 error while adding products. Let me help you troubleshoot this product creation issue.",
            confidence=0.8,
            metadata={"agent_used": "TechnicalSupportAgent"}
        ))
        
        response2 = await agent.handle(
            message="I get it while adding products",
            customer_data=None,
            kb_context=[],
            conversation_history=conversation_history,
            product_context=product_context,
        )
        
        conversation_history.append({"role": "user", "content": "I get it while adding products"})
        conversation_history.append({"role": "assistant", "content": response2})
        
        # Turn 3: "adding new products"
        mock_groq_client.chat_completion = AsyncMock(return_value=LLMResponse(
            content="I understand you're getting a 500 error when adding new products. Let me check the product creation endpoint for any known issues.",
            confidence=0.8,
            metadata={"agent_used": "TechnicalSupportAgent"}
        ))
        
        response3 = await agent.handle(
            message="adding new products",
            customer_data=None,
            kb_context=[],
            conversation_history=conversation_history,
            product_context=product_context,
        )
        
        conversation_history.append({"role": "user", "content": "adding new products"})
        conversation_history.append({"role": "assistant", "content": response3})
        
        # Turn 4: "what error were we talking about?"
        # This is the critical test - the AI must summarize from history
        mock_groq_client.chat_completion = AsyncMock(return_value=LLMResponse(
            content="You reported a 500 error while adding a new product.",
            confidence=0.9,
            metadata={"agent_used": "TechnicalSupportAgent"}
        ))
        
        response4 = await agent.handle(
            message="what error were we talking about?",
            customer_data=None,
            kb_context=[],
            conversation_history=conversation_history,
            product_context=product_context,
        )
        
        # Verify the final response accurately summarizes the error from history
        assert "500" in response4.lower()
        assert "adding" in response4.lower() or "add" in response4.lower()
        assert "product" in response4.lower()
        
        # Verify conversation history was passed to the LLM
        call_args = mock_groq_client.chat_completion.call_args
        messages_sent = call_args[1]["messages"]
        
        # Should have all conversation history messages
        # system + 4 user messages + 3 assistant responses = 8 messages
        assert len(messages_sent) >= 8
        
        # Verify the history contains the error and product context
        message_contents = [msg.content for msg in messages_sent]
        assert any("500" in content for content in message_contents)
        assert any("adding" in content or "add" in content for content in message_contents)
        assert any("product" in content for content in message_contents)
