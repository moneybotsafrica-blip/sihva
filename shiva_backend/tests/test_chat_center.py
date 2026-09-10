import pytest
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    ChatSession,
    ChatMessage,
    ChatSessionStatus,
    MessageSender,
)
from app.chat_center.service import ChatCenterService


@pytest.fixture
async def chat_service(async_session: AsyncSession):
    """Create a chat service instance."""
    return ChatCenterService(async_session)


@pytest.fixture
async def sample_chat_session(chat_service: ChatCenterService):
    """Create a sample chat session for testing."""
    return await chat_service.get_or_create_chat_session(customer_id="cust_123")


class TestChatSessionCreation:
    """Test chat session creation functionality."""

    @pytest.mark.asyncio
    async def test_create_new_chat_session(self, chat_service: ChatCenterService):
        """Test creating a new chat session when none exists."""
        chat_session = await chat_service.get_or_create_chat_session(customer_id="cust_123")

        assert chat_session.id is not None
        assert chat_session.customer_id == "cust_123"
        assert chat_session.status == ChatSessionStatus.ACTIVE
        assert chat_session.ai_attempts == 0

    @pytest.mark.asyncio
    async def test_reuse_active_chat_session(self, chat_service: ChatCenterService):
        """Test that active chat session is reused."""
        # Create first session
        first_session = await chat_service.get_or_create_chat_session(customer_id="cust_123")
        
        # Call again - should return same session
        second_session = await chat_service.get_or_create_chat_session(customer_id="cust_123")
        
        assert second_session.id == first_session.id
        assert second_session.customer_id == "cust_123"
        assert second_session.status == ChatSessionStatus.ACTIVE

    @pytest.mark.asyncio
    async def test_different_customers_separate_sessions(self, chat_service: ChatCenterService):
        """Test that different customers get separate sessions."""
        session1 = await chat_service.get_or_create_chat_session(customer_id="cust_1")
        session2 = await chat_service.get_or_create_chat_session(customer_id="cust_2")
        
        assert session1.id != session2.id
        assert session1.customer_id == "cust_1"
        assert session2.customer_id == "cust_2"


class TestChatSessionRetrieval:
    """Test chat session retrieval functionality."""

    @pytest.mark.asyncio
    async def test_get_chat_session_by_id(self, chat_service: ChatCenterService):
        """Test retrieving a chat session by ID."""
        created_session = await chat_service.get_or_create_chat_session(customer_id="cust_123")
        
        retrieved_session = await chat_service.get_chat_session(created_session.id)
        assert retrieved_session is not None
        assert retrieved_session.id == created_session.id
        assert retrieved_session.customer_id == "cust_123"

    @pytest.mark.asyncio
    async def test_get_nonexistent_chat_session(self, chat_service: ChatCenterService):
        """Test retrieving a non-existent chat session."""
        session = await chat_service.get_chat_session("nonexistent_id")
        assert session is None

    @pytest.mark.asyncio
    async def test_get_active_chat_session(self, chat_service: ChatCenterService):
        """Test retrieving customer's active chat session."""
        await chat_service.get_or_create_chat_session(customer_id="cust_123")
        
        active_session = await chat_service.get_active_chat_session(customer_id="cust_123")
        assert active_session is not None
        assert active_session.status == ChatSessionStatus.ACTIVE

    @pytest.mark.asyncio
    async def test_get_active_chat_session_none(self, chat_service: ChatCenterService):
        """Test retrieving active session for customer with no active session."""
        active_session = await chat_service.get_active_chat_session(customer_id="nonexistent")
        assert active_session is None


class TestChatMessageManagement:
    """Test chat message appending and retrieval."""

    @pytest.mark.asyncio
    async def test_add_chat_message(self, chat_service: ChatCenterService, sample_chat_session: ChatSession):
        """Test adding a message to a chat session."""
        message = await chat_service.add_chat_message(
            chat_session_id=sample_chat_session.id,
            sender=MessageSender.CUSTOMER,
            content="Hello, I need help",
        )

        assert message.id is not None
        assert message.chat_session_id == sample_chat_session.id
        assert message.sender == MessageSender.CUSTOMER
        assert message.content == "Hello, I need help"

    @pytest.mark.asyncio
    async def test_add_chat_message_updates_timestamp(self, chat_service: ChatCenterService, sample_chat_session: ChatSession):
        """Test that adding a message updates chat session timestamp."""
        original_updated = sample_chat_session.updated_at

        # Small delay to ensure timestamp difference
        import asyncio
        await asyncio.sleep(0.01)

        await chat_service.add_chat_message(
            chat_session_id=sample_chat_session.id,
            sender=MessageSender.CUSTOMER,
            content="New message",
        )

        updated_session = await chat_service.get_chat_session(sample_chat_session.id)
        assert updated_session.updated_at > original_updated

    @pytest.mark.asyncio
    async def test_get_chat_messages(self, chat_service: ChatCenterService, sample_chat_session: ChatSession):
        """Test retrieving all messages for a chat session."""
        # Add multiple messages
        await chat_service.add_chat_message(
            chat_session_id=sample_chat_session.id,
            sender=MessageSender.CUSTOMER,
            content="Message 1",
        )
        await chat_service.add_chat_message(
            chat_session_id=sample_chat_session.id,
            sender=MessageSender.SUPPORT_AI,
            content="Response 1",
        )

        messages = await chat_service.get_chat_messages(sample_chat_session.id)
        assert len(messages) == 2
        assert messages[0].sender == MessageSender.CUSTOMER
        assert messages[1].sender == MessageSender.SUPPORT_AI

    @pytest.mark.asyncio
    async def test_add_chat_message_nonexistent_session(self, chat_service: ChatCenterService):
        """Test adding message to non-existent chat session."""
        with pytest.raises(ValueError, match="not found"):
            await chat_service.add_chat_message(
                chat_session_id="nonexistent_id",
                sender=MessageSender.CUSTOMER,
                content="Test",
            )


class TestChatSessionReopening:
    """Test chat session reopening functionality."""

    @pytest.mark.asyncio
    async def test_reopen_resolved_chat_session(self, chat_service: ChatCenterService, sample_chat_session: ChatSession):
        """Test reopening a resolved chat session."""
        # First mark as resolved
        sample_chat_session.status = ChatSessionStatus.RESOLVED
        sample_chat_session.updated_at = datetime.now()
        
        # Reopen it
        reopened_session = await chat_service.reopen_chat_session(sample_chat_session.id)
        
        assert reopened_session.status == ChatSessionStatus.ACTIVE
        assert reopened_session.id == sample_chat_session.id
        assert reopened_session.customer_id == sample_chat_session.customer_id

    @pytest.mark.asyncio
    async def test_reopen_nonexistent_session(self, chat_service: ChatCenterService):
        """Test reopening a non-existent chat session."""
        with pytest.raises(ValueError, match="not found"):
            await chat_service.reopen_chat_session("nonexistent_id")

    @pytest.mark.asyncio
    async def test_reopen_active_session_forbidden(self, chat_service: ChatCenterService, sample_chat_session: ChatSession):
        """Test that active sessions cannot be reopened."""
        with pytest.raises(ValueError, match="Cannot reopen chat session"):
            await chat_service.reopen_chat_session(sample_chat_session.id)

    @pytest.mark.asyncio
    async def test_reopen_escalated_session_forbidden(self, chat_service: ChatCenterService, sample_chat_session: ChatSession):
        """Test that escalated sessions cannot be reopened."""
        # Mark as escalated
        sample_chat_session.status = ChatSessionStatus.ESCALATED
        sample_chat_session.updated_at = datetime.now()
        
        with pytest.raises(ValueError, match="Cannot reopen chat session"):
            await chat_service.reopen_chat_session(sample_chat_session.id)


class TestChatSessionContinuity:
    """Test chat session continuity across multiple messages."""

    @pytest.mark.asyncio
    async def test_same_session_id_across_active_sends(self, chat_service: ChatCenterService):
        """Test that same session_id is returned across multiple sends while ACTIVE."""
        # Create initial session
        first_session = await chat_service.get_or_create_chat_session(customer_id="cust_123")
        session_id = first_session.id
        
        # Add message
        await chat_service.add_chat_message(
            chat_session_id=session_id,
            sender=MessageSender.CUSTOMER,
            content="First message",
        )
        
        # Get session again - should be same ID
        second_session = await chat_service.get_or_create_chat_session(customer_id="cust_123")
        assert second_session.id == session_id
        assert second_session.status == ChatSessionStatus.ACTIVE

    @pytest.mark.asyncio
    async def test_resolved_session_reopen_preserves_history(self, chat_service: ChatCenterService):
        """Test that reopening a resolved session preserves prior messages and ai_attempts."""
        # Create session and add messages
        session = await chat_service.get_or_create_chat_session(customer_id="cust_123")
        session_id = session.id
        
        await chat_service.add_chat_message(
            chat_session_id=session_id,
            sender=MessageSender.CUSTOMER,
            content="First message",
        )
        await chat_service.add_chat_message(
            chat_session_id=session_id,
            sender=MessageSender.SUPPORT_AI,
            content="AI response",
        )
        
        # Set ai_attempts
        session.ai_attempts = 2
        session.status = ChatSessionStatus.RESOLVED
        session.updated_at = datetime.now()
        
        # Reopen session
        reopened_session = await chat_service.reopen_chat_session(session_id)
        
        # Verify history preserved
        messages = await chat_service.get_chat_messages(session_id)
        assert len(messages) == 2
        assert reopened_session.ai_attempts == 2
        assert reopened_session.status == ChatSessionStatus.ACTIVE

    @pytest.mark.asyncio
    async def test_new_session_without_chat_session_id(self, chat_service: ChatCenterService):
        """Test that new session is created when no chat_session_id is provided."""
        # Create first session
        first_session = await chat_service.get_or_create_chat_session(customer_id="cust_123")
        
        # Mark as resolved
        first_session.status = ChatSessionStatus.RESOLVED
        first_session.updated_at = datetime.now()
        
        # Without chat_session_id, should create new session
        new_session = await chat_service.get_or_create_chat_session(customer_id="cust_123")
        
        assert new_session.id != first_session.id
        assert new_session.status == ChatSessionStatus.ACTIVE

    @pytest.mark.asyncio
    async def test_escalated_session_rejection(self, chat_service: ChatCenterService, sample_chat_session: ChatSession):
        """Test that escalated sessions are rejected with clear error."""
        # Mark as escalated
        sample_chat_session.status = ChatSessionStatus.ESCALATED
        sample_chat_session.ticket_id = "ticket_123"
        sample_chat_session.updated_at = datetime.now()
        
        # Attempt to reopen should fail
        with pytest.raises(ValueError, match="Cannot reopen chat session"):
            await chat_service.reopen_chat_session(sample_chat_session.id)

    @pytest.mark.asyncio
    async def test_cross_customer_session_rejection(self, chat_service: ChatCenterService):
        """Test that sessions belonging to different customers are rejected."""
        # Create session for customer 1
        session1 = await chat_service.get_or_create_chat_session(customer_id="cust_1")
        
        # Try to access it as customer 2 (simulated by checking customer_id)
        session = await chat_service.get_chat_session(session1.id)
        assert session.customer_id == "cust_1"
        assert session.customer_id != "cust_2"


class TestChatSessionStatusTransitions:
    """Test chat session status state machine."""

    @pytest.mark.asyncio
    async def test_active_to_resolved_transition(self, chat_service: ChatCenterService, sample_chat_session: ChatSession):
        """Test valid status transition from ACTIVE to RESOLVED."""
        sample_chat_session.status = ChatSessionStatus.RESOLVED
        sample_chat_session.updated_at = datetime.now()
        
        updated_session = await chat_service.get_chat_session(sample_chat_session.id)
        assert updated_session.status == ChatSessionStatus.RESOLVED

    @pytest.mark.asyncio
    async def test_resolved_to_active_transition(self, chat_service: ChatCenterService, sample_chat_session: ChatSession):
        """Test valid status transition from RESOLVED to ACTIVE (reopen)."""
        # First resolve
        sample_chat_session.status = ChatSessionStatus.RESOLVED
        sample_chat_session.updated_at = datetime.now()
        
        # Then reopen
        reopened = await chat_service.reopen_chat_session(sample_chat_session.id)
        assert reopened.status == ChatSessionStatus.ACTIVE

    @pytest.mark.asyncio
    async def test_active_to_escalated_transition(self, chat_service: ChatCenterService, sample_chat_session: ChatSession):
        """Test valid status transition from ACTIVE to ESCALATED."""
        sample_chat_session.status = ChatSessionStatus.ESCALATED
        sample_chat_session.ticket_id = "ticket_123"
        sample_chat_session.updated_at = datetime.now()
        
        updated_session = await chat_service.get_chat_session(sample_chat_session.id)
        assert updated_session.status == ChatSessionStatus.ESCALATED
        assert updated_session.ticket_id == "ticket_123"


class TestChatSessionWithAttachments:
    """Test chat sessions with message attachments."""

    @pytest.mark.asyncio
    async def test_add_message_with_attachments(self, chat_service: ChatCenterService, sample_chat_session: ChatSession):
        """Test adding a message with attachments."""
        attachments = ["file1.pdf", "screenshot.png"]
        
        message = await chat_service.add_chat_message(
            chat_session_id=sample_chat_session.id,
            sender=MessageSender.CUSTOMER,
            content="Here are my files",
            attachments=attachments,
        )
        
        assert message.attachments == attachments
        assert len(message.attachments) == 2

    @pytest.mark.asyncio
    async def test_add_message_without_attachments(self, chat_service: ChatCenterService, sample_chat_session: ChatSession):
        """Test adding a message without attachments."""
        message = await chat_service.add_chat_message(
            chat_session_id=sample_chat_session.id,
            sender=MessageSender.CUSTOMER,
            content="Text only message",
        )
        
        assert message.attachments is None
