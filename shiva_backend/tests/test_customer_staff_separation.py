"""
Tests for customer-facing vs staff-facing content separation.

Tests ensure that:
- Customers see only status messages on escalation, not AI's technical solutions
- Staff can see AI's suggested solutions for escalated tickets
- Auto-resolve path is unaffected (customers still get real answers)
- Role-based access control is enforced at the API layer
"""
import pytest
from unittest.mock import AsyncMock
from sqlalchemy.ext.asyncio import AsyncSession

from app.support_ai.service import SupportAIService
from app.clients.qdrant_client import QdrantClientInterface, SearchResult
from app.clients.groq_client import GroqClientInterface, ChatMessage, LLMResponse
from app.ticket_center.service import TicketCenterService
from app.db.models import TicketStatus, MessageSender, AISuggestedResolution, Ticket as DBTicket


@pytest.fixture
def separation_qdrant_client():
    """Mock Qdrant client for separation testing."""
    client = AsyncMock(spec=QdrantClientInterface)
    client.embed_text = AsyncMock(return_value=[0.1, 0.2, 0.3])
    client.search = AsyncMock(return_value=[])  # No KB matches
    return client


@pytest.fixture
def separation_groq_client():
    """Mock Groq client for separation testing."""
    client = AsyncMock(spec=GroqClientInterface)
    
    # Default response for escalation scenario
    client.chat_completion = AsyncMock(return_value=LLMResponse(
        content="Here's the technical solution: check your network configuration and update the timeout settings in your config file to 30 seconds.",
        confidence=0.6,
        metadata={"agent_used": "TechSupportAgent"}
    ))
    
    # Structured escalation decision
    client.should_escalate = AsyncMock(return_value={
        "escalate": True,
        "reason": "Complex technical issue requiring human investigation",
        "confidence": 0.7
    })
    
    # Mock out-of-scope analysis
    client.is_out_of_scope = AsyncMock(return_value={
        "is_out_of_scope": False,
        "reason": "In scope"
    })
    
    return client


@pytest.fixture
def separation_support_service(
    separation_qdrant_client: AsyncMock,
    separation_groq_client: AsyncMock,
):
    """Create support service for separation testing."""
    return SupportAIService(
        qdrant_client=separation_qdrant_client,
        groq_client=separation_groq_client,
        confidence_threshold=0.3,
    )


@pytest.fixture
def separation_ticket_service(async_session: AsyncSession):
    """Create ticket service for separation testing."""
    return TicketCenterService(async_session)


class TestCustomerStaffSeparation:
    """Test separation of customer-facing and staff-facing content."""
    
    @pytest.mark.asyncio
    async def test_escalation_customer_sees_status_message(
        self,
        separation_support_service: SupportAIService,
        separation_ticket_service: TicketCenterService,
        separation_groq_client: AsyncMock,
        async_session: AsyncSession,
    ):
        """
        Test that on escalation, customer sees only status message, not AI's technical solution.
        """
        # Create ticket
        ticket = await separation_ticket_service.create_ticket(
            customer_id="separation_customer",
            initial_message="My API integration is timing out during checkout process",
            path="support",
        )
        
        # Process message (will escalate due to low confidence + no KB)
        await separation_support_service.process_and_respond(
            ticket_id=ticket.id,
            customer_id="separation_customer",
            message="My API integration is timing out during checkout process",
            ticket_service=separation_ticket_service,
            is_agent_request=False,
        )
        
        # Get updated ticket
        updated_ticket = await separation_ticket_service.get_ticket(ticket.id)
        
        # Verify ticket was escalated
        assert updated_ticket.status == TicketStatus.PENDING_STAFF
        
        # Get all messages
        messages = await separation_ticket_service.get_ticket_messages(ticket.id)
        
        # Customer should see exactly 2 messages:
        # 1. Initial customer message
        # 2. AI status message (NOT the technical solution)
        assert len(messages) == 2
        
        # Verify second message is from AI
        assert messages[1].sender == MessageSender.SUPPORT_AI
        
        # Verify it's the status message, not the technical solution
        status_message = messages[1].content
        assert "escalated" in status_message.lower() or "specialist" in status_message.lower()
        assert "network configuration" not in status_message.lower()  # Not the technical solution
        assert "timeout settings" not in status_message.lower()  # Not the technical solution
        
        # Verify AI suggested resolution was stored as staff-only artifact
        assert updated_ticket.ai_suggested_resolution is not None
        assert "network configuration" in updated_ticket.ai_suggested_resolution.suggested_solution.lower()
        assert "timeout settings" in updated_ticket.ai_suggested_resolution.suggested_solution.lower()
    
    @pytest.mark.asyncio
    async def test_auto_resolve_customer_gets_real_answer(
        self,
        separation_support_service: SupportAIService,
        separation_ticket_service: TicketCenterService,
        separation_groq_client: AsyncMock,
        async_session: AsyncSession,
    ):
        """
        Test that auto-resolve path is unaffected - customer still gets real answer.
        """
        # Create ticket
        ticket = await separation_ticket_service.create_ticket(
            customer_id="auto_resolve_customer",
            initial_message="How do I reset my password?",
            path="support",
        )
        
        # Mock Groq to NOT escalate (high confidence)
        separation_groq_client.should_escalate = AsyncMock(return_value={
            "escalate": False,
            "reason": "AI can provide clear solution",
            "confidence": 0.9
        })
        
        # Mock Qdrant to return KB results
        separation_support_service.qdrant_client.search = AsyncMock(return_value=[
            SearchResult(id="kb_1", score=0.9, payload={"content": "Password reset instructions"}, content="Password reset instructions")
        ])
        
        # Process message (should auto-resolve)
        await separation_support_service.process_and_respond(
            ticket_id=ticket.id,
            customer_id="auto_resolve_customer",
            message="How do I reset my password?",
            ticket_service=separation_ticket_service,
            is_agent_request=False,
        )
        
        # Get updated ticket
        updated_ticket = await separation_ticket_service.get_ticket(ticket.id)
        
        # Verify ticket was auto-resolved
        assert updated_ticket.status == TicketStatus.RESOLVED_AUTO
        
        # Get all messages
        messages = await separation_ticket_service.get_ticket_messages(ticket.id)
        
        # Customer should see exactly 2 messages:
        # 1. Initial customer message
        # 2. AI response with actual solution
        assert len(messages) == 2
        
        # Verify second message is from AI
        assert messages[1].sender == MessageSender.SUPPORT_AI
        
        # Verify it's a real solution, not just a status message
        ai_response = messages[1].content
        assert "escalated" not in ai_response.lower()
        assert "specialist" not in ai_response.lower()
        # Should contain actual password reset instructions
        assert len(ai_response) > 50  # Real solution, not just status
        
        # Verify NO AI suggested resolution was created (only for escalation)
        assert updated_ticket.ai_suggested_resolution is None


class TestRoleBasedAccessControl:
    """Test role-based access control for AI suggested resolution."""
    
    @pytest.mark.asyncio
    async def test_customer_cannot_see_ai_suggested_resolution(
        self,
        separation_ticket_service: TicketCenterService,
        async_session: AsyncSession,
    ):
        """
        Test that customer role cannot retrieve AI suggested resolution field.
        """
        # Create ticket with AI suggested resolution
        ticket = await separation_ticket_service.create_ticket(
            customer_id="rbac_customer",
            initial_message="Complex issue",
            path="support",
        )
        
        # Create AI suggested resolution
        await separation_ticket_service.create_ai_suggested_resolution(
            ticket_id=ticket.id,
            suggested_solution="Technical diagnosis: server configuration issue",
            confidence=0.7,
            escalation_reason="Complex technical issue",
        )
        
        # Re-fetch ticket with messages loaded to avoid lazy loading issues
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload
        from app.db.models import Ticket as DBTicket
        
        result = await async_session.execute(
            select(DBTicket)
            .options(selectinload(DBTicket.messages))
            .options(selectinload(DBTicket.ai_suggested_resolution))
            .where(DBTicket.id == ticket.id)
        )
        ticket_with_resolution = result.scalar_one()
        
        # Verify AI suggested resolution exists in database
        assert ticket_with_resolution.ai_suggested_resolution is not None
        assert ticket_with_resolution.ai_suggested_resolution.suggested_solution == "Technical diagnosis: server configuration issue"
        
        # Simulate GraphQL conversion for customer role (check field is filtered out)
        from app.graphql_schema.queries import ticket_to_graphql
        graphql_ticket = ticket_to_graphql(ticket_with_resolution, user_role="customer")
        
        # Verify AI suggested resolution is None for customer
        assert graphql_ticket.ai_suggested_resolution is None
    
    @pytest.mark.asyncio
    async def test_staff_can_see_ai_suggested_resolution(
        self,
        separation_ticket_service: TicketCenterService,
        async_session: AsyncSession,
    ):
        """
        Test that staff role can retrieve AI suggested resolution field.
        """
        # Create ticket with AI suggested resolution
        ticket = await separation_ticket_service.create_ticket(
            customer_id="rbac_staff",
            initial_message="Complex issue",
            path="support",
        )
        
        # Create AI suggested resolution
        await separation_ticket_service.create_ai_suggested_resolution(
            ticket_id=ticket.id,
            suggested_solution="Technical diagnosis: server configuration issue",
            confidence=0.7,
            escalation_reason="Complex technical issue",
        )
        
        # Re-fetch ticket with messages loaded to avoid lazy loading issues
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload
        from app.db.models import Ticket as DBTicket
        
        result = await async_session.execute(
            select(DBTicket)
            .options(selectinload(DBTicket.messages))
            .options(selectinload(DBTicket.ai_suggested_resolution))
            .where(DBTicket.id == ticket.id)
        )
        ticket_with_resolution = result.scalar_one()
        
        # Simulate GraphQL conversion for staff role
        from app.graphql_schema.queries import ticket_to_graphql
        graphql_ticket = ticket_to_graphql(ticket_with_resolution, user_role="staff")
        
        # Verify AI suggested resolution is available for staff
        assert graphql_ticket.ai_suggested_resolution is not None
        assert graphql_ticket.ai_suggested_resolution.suggested_solution == "Technical diagnosis: server configuration issue"
        assert graphql_ticket.ai_suggested_resolution.confidence == 0.7
        assert graphql_ticket.ai_suggested_resolution.escalation_reason == "Complex technical issue"
    
    @pytest.mark.asyncio
    async def test_developer_can_see_ai_suggested_resolution(
        self,
        separation_ticket_service: TicketCenterService,
        async_session: AsyncSession,
    ):
        """
        Test that developer role can retrieve AI suggested resolution field.
        """
        # Create ticket with AI suggested resolution
        ticket = await separation_ticket_service.create_ticket(
            customer_id="rbac_developer",
            initial_message="Complex issue",
            path="support",
        )
        
        # Create AI suggested resolution
        await separation_ticket_service.create_ai_suggested_resolution(
            ticket_id=ticket.id,
            suggested_solution="Technical diagnosis: server configuration issue",
            confidence=0.7,
            escalation_reason="Complex technical issue",
        )
        
        # Re-fetch ticket with messages loaded to avoid lazy loading issues
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload
        from app.db.models import Ticket as DBTicket
        
        result = await async_session.execute(
            select(DBTicket)
            .options(selectinload(DBTicket.messages))
            .options(selectinload(DBTicket.ai_suggested_resolution))
            .where(DBTicket.id == ticket.id)
        )
        ticket_with_resolution = result.scalar_one()
        
        # Simulate GraphQL conversion for developer role
        from app.graphql_schema.queries import ticket_to_graphql
        graphql_ticket = ticket_to_graphql(ticket_with_resolution, user_role="developer")
        
        # Verify AI suggested resolution is available for developer
        assert graphql_ticket.ai_suggested_resolution is not None
        assert graphql_ticket.ai_suggested_resolution.suggested_solution == "Technical diagnosis: server configuration issue"
