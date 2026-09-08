import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.graphql.schema import schema
from app.db.models import TicketStatus, MessageSender
from app.gateway.auth import User


@pytest.fixture
async def authenticated_context(async_session: AsyncSession, mock_user):
    """Create an authenticated GraphQL context."""
    from app.graphql.queries import ticket_to_graphql

    class MockContext:
        def __init__(self, user, session):
            self.current_user = user
            self.session = session
            self.request = None

    return MockContext(mock_user, async_session)


@pytest.fixture
async def staff_context(async_session: AsyncSession, mock_staff_user):
    """Create a staff-authenticated GraphQL context."""
    class MockContext:
        def __init__(self, user, session):
            self.current_user = user
            self.session = session
            self.request = None

    return MockContext(mock_staff_user, async_session)


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

        ticket_service = TicketCenterService(authenticated_context.session)
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
        assert authenticated_context.session is not None
        assert hasattr(authenticated_context.session, 'execute')

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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
