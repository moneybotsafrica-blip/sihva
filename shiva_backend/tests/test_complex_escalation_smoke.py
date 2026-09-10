"""
Smoke tests for complex issue detection and ticket escalation.

This test suite verifies:
1. Complex issues are properly detected
2. Tickets are created with valid IDs
3. Escalation logic works correctly
4. Multiple escalation scenarios function as expected
"""
import pytest
from unittest.mock import AsyncMock
from sqlalchemy.ext.asyncio import AsyncSession

from app.support_ai.service import SupportAIService
from app.clients.qdrant_client import QdrantClientInterface, SearchResult
from app.clients.groq_client import GroqClientInterface, ChatMessage, LLMResponse
from app.ticket_center.service import TicketCenterService
from app.db.models import TicketStatus, MessageSender, TicketPath


@pytest.fixture
def smoke_qdrant_client():
    """Mock Qdrant client for smoke testing."""
    client = AsyncMock(spec=QdrantClientInterface)
    client.embed_text = AsyncMock(return_value=[0.1, 0.2, 0.3])
    client.search = AsyncMock(return_value=[])  # No KB matches to trigger escalation
    return client


@pytest.fixture
def smoke_groq_client():
    """Mock Groq client for smoke testing."""
    client = AsyncMock(spec=GroqClientInterface)
    
    # Default response for regular chat completion
    client.chat_completion = AsyncMock(return_value=LLMResponse(
        content="I can help you with that. Here's the solution...",
        confidence=0.8,
        metadata={"agent_used": "GeneralSupportAgent"}
    ))
    
    # Default structured escalation decision (escalate for complex issues)
    client.should_escalate = AsyncMock(return_value={
        "escalate": True,
        "reason": "Complex issue requiring human intervention",
        "confidence": 0.85
    })
    
    # Mock out-of-scope analysis
    client.is_out_of_scope = AsyncMock(return_value={
        "is_out_of_scope": False,
        "reasoning": "Issue is within scope",
        "confidence": 0.8
    })
    
    return client


@pytest.fixture
def smoke_support_service(smoke_qdrant_client, smoke_groq_client):
    """Create support service for smoke testing."""
    return SupportAIService(
        qdrant_client=smoke_qdrant_client,
        groq_client=smoke_groq_client,
        confidence_threshold=0.7
    )


@pytest.fixture
async def smoke_ticket_service(async_session: AsyncSession):
    """Create ticket service for smoke testing."""
    return TicketCenterService(async_session)


class TestComplexIssueDetection:
    """Test complex issue detection and escalation."""
    
    @pytest.mark.asyncio
    async def test_complex_technical_issue_detection(
        self,
        smoke_support_service: SupportAIService,
        smoke_ticket_service: TicketCenterService,
        async_session: AsyncSession,
    ):
        """Test that complex technical issues are detected and escalated."""
        # Create a ticket
        ticket = await smoke_ticket_service.create_ticket(
            customer_id="smoke_customer_001",
            initial_message="I need help with a complex technical issue",
            path=TicketPath.SUPPORT,
        )
        
        # Verify ticket was created with valid ID
        assert ticket.id is not None
        assert len(ticket.id) > 0
        assert ticket.status == TicketStatus.OPEN
        
        # Process complex technical issue
        result = await smoke_support_service.handle_customer_message(
            ticket_id=ticket.id,
            customer_id="smoke_customer_001",
            message="My API integration is failing with timeout errors during the checkout process. I've tried multiple approaches but none work. The error occurs specifically when processing payments through the custom webhook integration",
            ticket_service=smoke_ticket_service,
            is_agent_request=False,
            product_context={
                "product_id": "product_123",
                "product_name": "Shiva E-Commerce",
                "enabled_modules": ["checkout", "payment", "api"],
                "client_entitled": True,
                "relevant_knowledge_articles": []
            },
        )
        
        # Should detect complexity and escalate
        assert result["should_queue"] is True
        assert result["action"] == "queue_for_staff"
        assert "escalation_reason" in result
        
    @pytest.mark.asyncio
    async def test_security_issue_detection(
        self,
        smoke_support_service: SupportAIService,
        smoke_ticket_service: TicketCenterService,
        async_session: AsyncSession,
    ):
        """Test that security issues are detected and escalated."""
        # Create a ticket
        ticket = await smoke_ticket_service.create_ticket(
            customer_id="smoke_customer_002",
            initial_message="Security issue",
            path=TicketPath.SUPPORT,
        )
        
        # Verify ticket creation
        assert ticket.id is not None
        assert ticket.status == TicketStatus.OPEN
        
        # Process security issue
        result = await smoke_support_service.handle_customer_message(
            ticket_id=ticket.id,
            customer_id="smoke_customer_002",
            message="My account was hacked and I see unauthorized transactions. I need immediate investigation into this security breach",
            ticket_service=smoke_ticket_service,
            is_agent_request=False,
        )
        
        # Should escalate for security issues
        assert result["should_queue"] is True
        assert result["action"] == "queue_for_staff"


class TestTicketCreationAndIDGeneration:
    """Test ticket creation and ID generation."""
    
    @pytest.mark.asyncio
    async def test_ticket_creation_with_valid_id(
        self,
        smoke_ticket_service: TicketCenterService,
        async_session: AsyncSession,
    ):
        """Test that tickets are created with valid unique IDs."""
        # Create multiple tickets
        ticket1 = await smoke_ticket_service.create_ticket(
            customer_id="smoke_customer_003",
            initial_message="First ticket",
            path=TicketPath.SUPPORT,
        )
        
        ticket2 = await smoke_ticket_service.create_ticket(
            customer_id="smoke_customer_004",
            initial_message="Second ticket",
            path=TicketPath.SUPPORT,
        )
        
        # Verify both tickets have valid IDs
        assert ticket1.id is not None
        assert ticket2.id is not None
        assert len(ticket1.id) > 0
        assert len(ticket2.id) > 0
        
        # Verify IDs are unique
        assert ticket1.id != ticket2.id
        
        # Verify initial status
        assert ticket1.status == TicketStatus.OPEN
        assert ticket2.status == TicketStatus.OPEN
        
    @pytest.mark.asyncio
    async def test_ticket_with_title_generation(
        self,
        smoke_ticket_service: TicketCenterService,
        async_session: AsyncSession,
    ):
        """Test ticket creation with AI-generated title."""
        # Create ticket with title
        ticket = await smoke_ticket_service.create_ticket(
            customer_id="smoke_customer_005",
            initial_message="Payment API timeout during checkout",
            path=TicketPath.SUPPORT,
            title="Payment API timeout error",
        )
        
        # Verify ticket creation with title
        assert ticket.id is not None
        assert ticket.title == "Payment API timeout error"
        assert ticket.status == TicketStatus.OPEN


class TestEscalationScenarios:
    """Test multiple escalation scenarios."""
    
    @pytest.mark.asyncio
    async def test_explicit_agent_request_escalation(
        self,
        smoke_support_service: SupportAIService,
        smoke_ticket_service: TicketCenterService,
        async_session: AsyncSession,
    ):
        """Test explicit agent request escalation."""
        # Create ticket
        ticket = await smoke_ticket_service.create_ticket(
            customer_id="smoke_customer_006",
            initial_message="I need to speak to a human",
            path=TicketPath.SUPPORT,
        )
        
        # Process explicit agent request
        result = await smoke_support_service.handle_customer_message(
            ticket_id=ticket.id,
            customer_id="smoke_customer_006",
            message="I need to speak to a human agent about my complex billing issue",
            ticket_service=smoke_ticket_service,
            is_agent_request=True,  # Explicit request
        )
        
        # Should escalate immediately
        assert result["should_queue"] is True
        assert result["action"] == "queue_for_staff"
        assert result["escalation_reason"] == "explicit_agent_request"
        
    @pytest.mark.asyncio
    async def test_direct_ticket_request_escalation(
        self,
        smoke_support_service: SupportAIService,
        smoke_ticket_service: TicketCenterService,
        async_session: AsyncSession,
    ):
        """Test direct ticket request escalation."""
        # Create ticket
        ticket = await smoke_ticket_service.create_ticket(
            customer_id="smoke_customer_007",
            initial_message="Please create a ticket",
            path=TicketPath.SUPPORT,
        )
        
        # Process direct ticket request
        result = await smoke_support_service.handle_customer_message(
            ticket_id=ticket.id,
            customer_id="smoke_customer_007",
            message="Please create a ticket for my payment integration issue that needs investigation",
            ticket_service=smoke_ticket_service,
            is_agent_request=False,
        )
        
        # Should escalate for direct ticket request
        assert result["should_queue"] is True
        assert result["action"] == "queue_for_staff"
        assert result["escalation_reason"] == "explicit_ticket_request"
        
    @pytest.mark.asyncio
    async def test_failed_ai_solution_escalation(
        self,
        smoke_support_service: SupportAIService,
        smoke_ticket_service: TicketCenterService,
        async_session: AsyncSession,
    ):
        """Test escalation when AI solution fails."""
        # Create ticket
        ticket = await smoke_ticket_service.create_ticket(
            customer_id="smoke_customer_008",
            initial_message="Password reset not working",
            path=TicketPath.SUPPORT,
        )
        
        # Add previous AI attempts
        await smoke_ticket_service.append_message(
            ticket_id=ticket.id,
            sender=MessageSender.SUPPORT_AI,
            content="Try resetting your password through settings",
        )
        await smoke_ticket_service.append_message(
            ticket_id=ticket.id,
            sender=MessageSender.CUSTOMER,
            content="That didn't work",
        )
        await smoke_ticket_service.append_message(
            ticket_id=ticket.id,
            sender=MessageSender.SUPPORT_AI,
            content="Try the forgot password link",
        )
        await smoke_ticket_service.append_message(
            ticket_id=ticket.id,
            sender=MessageSender.CUSTOMER,
            content="Still not working",
        )
        
        # Process message indicating continued failure
        result = await smoke_support_service.handle_customer_message(
            ticket_id=ticket.id,
            customer_id="smoke_customer_008",
            message="I tried all the suggestions and it still doesn't work. This is really frustrating",
            ticket_service=smoke_ticket_service,
            is_agent_request=False,
        )
        
        # Should escalate due to multiple failed attempts
        assert result["should_queue"] is True
        assert result["action"] == "queue_for_staff"


class TestProcessAndRespondIntegration:
    """Test the full process_and_respond integration."""
    
    @pytest.mark.asyncio
    async def test_full_escalation_workflow(
        self,
        smoke_support_service: SupportAIService,
        smoke_ticket_service: TicketCenterService,
        smoke_groq_client: AsyncMock,
        async_session: AsyncSession,
    ):
        """Test the complete escalation workflow from message to ticket status update."""
        # Create ticket
        ticket = await smoke_ticket_service.create_ticket(
            customer_id="smoke_customer_009",
            initial_message="Complex integration issue",
            path=TicketPath.SUPPORT,
        )
        
        initial_status = ticket.status
        assert initial_status == TicketStatus.OPEN
        
        # Process complex issue that should escalate
        await smoke_support_service.process_and_respond(
            ticket_id=ticket.id,
            customer_id="smoke_customer_009",
            message="My custom API integration is failing with timeout errors during payment processing. I've tried multiple configurations but none resolve the issue",
            ticket_service=smoke_ticket_service,
            is_agent_request=False,
            product_context={
                "product_id": "product_456",
                "product_name": "Shiva POS",
                "enabled_modules": ["payment", "api"],
                "client_entitled": True,
                "relevant_knowledge_articles": []
            },
        )
        
        # Verify ticket status was updated to PENDING_STAFF
        updated_ticket = await smoke_ticket_service.get_ticket(ticket.id)
        assert updated_ticket.status == TicketStatus.PENDING_STAFF
        
        # Verify chat summary was created
        assert updated_ticket.chat_summary is not None
        assert len(updated_ticket.chat_summary) > 0
        
        # Verify ticket ID remains consistent
        assert updated_ticket.id == ticket.id


class TestAIAttemptsCap:
    """Test AI attempts cap functionality."""
    
    @pytest.mark.asyncio
    async def test_ai_attempts_cap_enforcement(
        self,
        smoke_support_service: SupportAIService,
        smoke_ticket_service: TicketCenterService,
        smoke_groq_client: AsyncMock,
        async_session: AsyncSession,
    ):
        """Test that AI attempts cap forces escalation."""
        # Create ticket
        ticket = await smoke_ticket_service.create_ticket(
            customer_id="smoke_customer_010",
            initial_message="Test issue",
            path=TicketPath.SUPPORT,
        )
        
        # Increment AI attempts to reach cap (default is 5)
        for _ in range(5):
            await smoke_ticket_service.increment_ai_attempts(ticket.id)
        
        # Mock Groq to say NO escalation (but cap should override)
        smoke_groq_client.should_escalate = AsyncMock(return_value={
            "escalate": False,
            "reason": "AI can handle this",
            "confidence": 0.95
        })
        
        # Process message
        result = await smoke_support_service.handle_customer_message(
            ticket_id=ticket.id,
            customer_id="smoke_customer_010",
            message="Another follow-up question",
            ticket_service=smoke_ticket_service,
            is_agent_request=False,
        )
        
        # Should escalate due to cap despite Groq saying no
        assert result["should_queue"] is True
        assert result["action"] == "queue_for_staff"
        assert "ai_attempts_cap_reached" in result["escalation_reason"]


class TestTicketMessageHandling:
    """Test ticket message handling during escalation."""
    
    @pytest.mark.asyncio
    async def test_message_appended_during_escalation(
        self,
        smoke_support_service: SupportAIService,
        smoke_ticket_service: TicketCenterService,
        async_session: AsyncSession,
    ):
        """Test that messages are properly appended during escalation."""
        # Create ticket
        ticket = await smoke_ticket_service.create_ticket(
            customer_id="smoke_customer_011",
            initial_message="Initial issue",
            path=TicketPath.SUPPORT,
        )
        
        # Get initial message count
        initial_messages = await smoke_ticket_service.get_ticket_messages(ticket.id)
        initial_count = len(initial_messages)
        
        # Process message that triggers escalation
        await smoke_support_service.process_and_respond(
            ticket_id=ticket.id,
            customer_id="smoke_customer_011",
            message="I need to speak to a human agent about this complex issue",
            ticket_service=smoke_ticket_service,
            is_agent_request=True,
        )
        
        # Verify message was appended
        final_messages = await smoke_ticket_service.get_ticket_messages(ticket.id)
        final_count = len(final_messages)
        
        # Should have one more message (the AI response)
        assert final_count == initial_count + 1
        
        # Verify the last message is from SUPPORT_AI
        last_message = final_messages[-1]
        assert last_message.sender == MessageSender.SUPPORT_AI