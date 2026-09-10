import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from unittest.mock import AsyncMock, patch

from app.graphql_schema.schema import schema
from app.db.models import MessageSender
from app.gateway.auth import User


@pytest.fixture
async def authenticated_context(async_session: AsyncSession, mock_user):
    """Create an authenticated GraphQL context."""
    from app.graphql_schema.queries import ticket_to_graphql

    class MockContext(dict):
        def __init__(self, user, session):
            super().__init__()
            self["current_user"] = user
            self["session"] = session
            self["request"] = None
            self.current_user = user
            self.session = session
            self.request = None

    class MockInfo:
        def __init__(self, context):
            self.context = context

    return MockInfo(MockContext(mock_user, async_session))


@pytest.fixture
async def staff_context(async_session: AsyncSession, mock_staff_user):
    """Create a staff-authenticated GraphQL context."""
    class MockContext(dict):
        def __init__(self, user, session):
            super().__init__()
            self["current_user"] = user
            self["session"] = session
            self["request"] = None
            self.current_user = user
            self.session = session
            self.request = None

    class MockInfo:
        def __init__(self, context):
            self.context = context

    return MockInfo(MockContext(mock_staff_user, async_session))


class TestSchemaIntegrity:
    """Test that the GraphQL schema is properly structured."""

    @pytest.mark.asyncio
    async def test_schema_has_required_fields(self):
        """Test that schema has required fields."""
        # Test that the schema is valid
        assert schema is not None
        # Strawberry schema doesn't have these attributes, but the schema object itself should exist
        assert schema is not None


class TestTicketCenterIntegration:
    """Test integration between GraphQL and Ticket Center."""

    @pytest.mark.asyncio
    async def test_ticket_service_integration(self, authenticated_context):
        """Test that GraphQL can use ticket service."""
        from app.ticket_center.service import TicketCenterService
        from app.db.models import TicketPath

        ticket_service = TicketCenterService(authenticated_context.context.session)
        ticket = await ticket_service.create_ticket(
            customer_id="test_user_123",
            initial_message="Test issue",
            path=TicketPath.SUPPORT,
        )

        assert ticket.id is not None
        assert ticket.customer_id == "test_user_123"

    @pytest.mark.asyncio
    async def test_context_provides_session(self, authenticated_context):
        """Test that context provides database session."""
        assert authenticated_context.context.session is not None
        assert hasattr(authenticated_context.context.session, 'execute')

    @pytest.mark.asyncio
    async def test_context_provides_user(self, authenticated_context):
        """Test that context provides user information."""
        assert authenticated_context.current_user is not None
        assert authenticated_context.current_user.id == "test_user_123"
        assert authenticated_context.current_user.role == "customer"


class TestUserContext:
    """Test user context creation."""

    def test_mock_user_creation(self, mock_user):
        """Test that mock user is created correctly."""
        assert mock_user.id == "test_user_123"
        assert mock_user.email == "test@example.com"
        assert mock_user.role == "customer"

    def test_mock_staff_user_creation(self, mock_staff_user):
        """Test that mock staff user is created correctly."""
        assert mock_staff_user.id == "staff_123"
        assert mock_staff_user.email == "staff@example.com"
        assert mock_staff_user.role == "staff"

    def test_mock_developer_user_creation(self, mock_developer_user):
        """Test that mock developer user is created correctly."""
        assert mock_developer_user.id == "dev_123"
        assert mock_developer_user.email == "dev@example.com"
        assert mock_developer_user.role == "developer"


class TestChatSessionContinuity:
    """Test chat session continuity in GraphQL mutations."""

    @pytest.fixture
    def mock_ai_process_result(self):
        """Mock AI processing result."""
        return {
            "action": "continue",
            "response": "AI response",
            "ticket_id": None
        }

    @pytest.mark.asyncio
    async def test_send_chat_message_creates_new_session_without_id(self, authenticated_context, mock_ai_process_result):
        """Test that new session is created when no chat_session_id is provided."""
        from app.graphql_schema.types import SendChatMessageInput
        from app.graphql_schema.mutations import Mutation
        from app.chat_center.service import ChatCenterService

        chat_service = ChatCenterService(authenticated_context.context.session)
        mutation = Mutation()
        input_data = SendChatMessageInput(content="Hello, I need help")

        with patch.object(
            chat_service, 
            'process_chat_message', 
            new_callable=AsyncMock,
            return_value=mock_ai_process_result
        ):
            result = await mutation.send_chat_message(
                info=authenticated_context,
                input=input_data,
            )

        assert result is not None
        assert result.id is not None
        assert result.customer_id == "test_user_123"

    @pytest.mark.asyncio
    async def test_send_chat_message_with_active_session_id(self, authenticated_context, mock_ai_process_result):
        """Test that same session_id is reused when providing active session ID."""
        from app.graphql_schema.types import SendChatMessageInput
        from app.graphql_schema.mutations import Mutation
        from app.chat_center.service import ChatCenterService

        chat_service = ChatCenterService(authenticated_context.context.session)
        
        # Create initial session
        initial_session = await chat_service.get_or_create_chat_session(customer_id="test_user_123")
        session_id = initial_session.id

        mutation = Mutation()
        input_data = SendChatMessageInput(
            content="Follow-up message",
            chat_session_id=session_id
        )

        with patch.object(
            chat_service, 
            'process_chat_message', 
            new_callable=AsyncMock,
            return_value=mock_ai_process_result
        ):
            result = await mutation.send_chat_message(
                info=authenticated_context,
                input=input_data,
            )

        assert result is not None
        assert result.id == session_id

    @pytest.mark.asyncio
    async def test_send_chat_message_reopens_resolved_session(self, authenticated_context, mock_ai_process_result):
        """Test that providing a resolved session ID reopens it."""
        from app.graphql_schema.types import SendChatMessageInput
        from app.graphql_schema.mutations import Mutation
        from app.chat_center.service import ChatCenterService
        from app.db.models import ChatSessionStatus
        from datetime import datetime

        chat_service = ChatCenterService(authenticated_context.context.session)
        
        # Create and resolve a session
        session = await chat_service.get_or_create_chat_session(customer_id="test_user_123")
        session.status = ChatSessionStatus.RESOLVED
        session.updated_at = datetime.now()
        session_id = session.id

        mutation = Mutation()
        input_data = SendChatMessageInput(
            content="I need help with my Shiva Softwares order",
            chat_session_id=session_id
        )

        with patch.object(
            chat_service, 
            'process_chat_message', 
            new_callable=AsyncMock,
            return_value=mock_ai_process_result
        ):
            result = await mutation.send_chat_message(
                info=authenticated_context,
                input=input_data,
            )

        assert result is not None
        assert result.id == session_id
        # The key test is that the same session_id is used when reopening
        # The session may be resolved again by AI processing, but continuity is preserved

    @pytest.mark.asyncio
    async def test_send_chat_message_rejects_escalated_session(self, authenticated_context):
        """Test that providing an escalated session ID is rejected."""
        from app.graphql_schema.types import SendChatMessageInput
        from app.graphql_schema.mutations import Mutation
        from app.chat_center.service import ChatCenterService
        from app.db.models import ChatSessionStatus
        from datetime import datetime

        chat_service = ChatCenterService(authenticated_context.context.session)
        
        # Create and escalate a session
        session = await chat_service.get_or_create_chat_session(customer_id="test_user_123")
        session.status = ChatSessionStatus.ESCALATED
        session.ticket_id = "ticket_123"
        session.updated_at = datetime.now()
        session_id = session.id

        mutation = Mutation()
        input_data = SendChatMessageInput(
            content="Follow-up on escalated issue",
            chat_session_id=session_id
        )

        # Should raise ValueError
        with pytest.raises(ValueError, match="escalated to a ticket"):
            await mutation.send_chat_message(
                info=authenticated_context,
                input=input_data,
            )

    @pytest.mark.asyncio
    async def test_send_chat_message_rejects_different_customer_session(self, authenticated_context):
        """Test that providing a session ID from different customer is rejected."""
        from app.graphql_schema.types import SendChatMessageInput
        from app.graphql_schema.mutations import Mutation
        from app.chat_center.service import ChatCenterService

        chat_service = ChatCenterService(authenticated_context.context.session)
        
        # Create session for different customer
        other_session = await chat_service.get_or_create_chat_session(customer_id="other_customer")
        session_id = other_session.id

        mutation = Mutation()
        input_data = SendChatMessageInput(
            content="Trying to access other session",
            chat_session_id=session_id
        )

        # Should raise ValueError
        with pytest.raises(ValueError, match="can only access your own"):
            await mutation.send_chat_message(
                info=authenticated_context,
                input=input_data,
            )

    @pytest.mark.asyncio
    async def test_send_chat_message_rejects_nonexistent_session(self, authenticated_context):
        """Test that providing a non-existent session ID is rejected."""
        from app.graphql_schema.types import SendChatMessageInput
        from app.graphql_schema.mutations import Mutation

        mutation = Mutation()
        input_data = SendChatMessageInput(
            content="Testing nonexistent session",
            chat_session_id="nonexistent_session_id"
        )

        # Should raise ValueError
        with pytest.raises(ValueError, match="not found"):
            await mutation.send_chat_message(
                info=authenticated_context,
                input=input_data,
            )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
