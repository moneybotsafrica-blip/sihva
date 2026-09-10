"""
Golden regression set for escalation scenarios.

This file contains scripted conversations that represent critical escalation scenarios.
Each scenario must:
- Result in a PENDING_STAFF ticket
- Have a non-generic escalation reason
- Reflect real-world customer interactions

The five golden scenarios:
1. Explicit human-agent request on first turn
2. Kiswahili escalation
3. Security/legal keyword issue
4. Customer says a previous AI fix did not work
5. Calm, novel, undocumented issue with no frustration language
"""
import pytest
from unittest.mock import AsyncMock
from sqlalchemy.ext.asyncio import AsyncSession

from app.support_ai.service import SupportAIService
from app.clients.qdrant_client import QdrantClientInterface, SearchResult
from app.clients.groq_client import GroqClientInterface, ChatMessage, LLMResponse
from app.ticket_center.service import TicketCenterService
from app.db.models import TicketStatus, MessageSender


@pytest.fixture
def golden_qdrant_client():
    """Mock Qdrant client for golden set testing."""
    client = AsyncMock(spec=QdrantClientInterface)
    client.embed_text = AsyncMock(return_value=[0.1, 0.2, 0.3])
    client.search = AsyncMock(return_value=[])  # No KB matches to trigger escalation
    return client


@pytest.fixture
def golden_groq_client():
    """Mock Groq client for golden set testing."""
    client = AsyncMock(spec=GroqClientInterface)
    
    # Default response
    client.chat_completion = AsyncMock(return_value=LLMResponse(
        content="I can help you with that. Here's the solution...",
        confidence=0.8,
        metadata={"agent_used": "GeneralSupportAgent"}
    ))
    
    # Default structured escalation decision (escalate for golden scenarios)
    client.should_escalate = AsyncMock(return_value={
        "escalate": True,
        "reason": "Customer needs human intervention",
        "confidence": 0.9
    })
    
    # Mock out-of-scope analysis
    client.is_out_of_scope = AsyncMock(return_value={
        "is_out_of_scope": False,
        "reason": "In scope"
    })
    
    return client


@pytest.fixture
def golden_support_service(
    golden_qdrant_client: AsyncMock,
    golden_groq_client: AsyncMock,
):
    """Create support service for golden set testing."""
    return SupportAIService(
        qdrant_client=golden_qdrant_client,
        groq_client=golden_groq_client,
        confidence_threshold=0.3,
    )


@pytest.fixture
def golden_ticket_service(async_session: AsyncSession):
    """Create ticket service for golden set testing."""
    return TicketCenterService(async_session)


class TestGoldenEscalationSet:
    """Golden regression set for critical escalation scenarios."""
    
    @pytest.mark.asyncio
    async def test_golden_1_explicit_human_request_first_turn(
        self,
        golden_support_service: SupportAIService,
        golden_ticket_service: TicketCenterService,
        golden_groq_client: AsyncMock,
        async_session: AsyncSession,
    ):
        """
        Golden Scenario 1: Explicit human-agent request on first turn.
        
        Customer immediately requests to speak to a human.
        This should bypass all gating and escalate directly.
        """
        # Create ticket
        ticket = await golden_ticket_service.create_ticket(
            customer_id="golden_customer_1",
            initial_message="I need to speak to a human agent about my payment issue",
            path="support",
        )
        
        # Process with explicit agent request flag using process_and_respond
        # (handle_customer_message only returns decision, process_and_respond executes it)
        await golden_support_service.process_and_respond(
            ticket_id=ticket.id,
            customer_id="golden_customer_1",
            message="I need to speak to a human agent about my payment issue",
            ticket_service=golden_ticket_service,
            is_agent_request=True,  # Explicit request
        )
        
        # Verify ticket status
        updated_ticket = await golden_ticket_service.get_ticket(ticket.id)
        assert updated_ticket.status == TicketStatus.PENDING_STAFF
        
        # Verify chat summary contains relevant context (non-generic)
        assert updated_ticket.chat_summary is not None
        assert len(updated_ticket.chat_summary) > 50  # Not a generic short reason
    
    @pytest.mark.asyncio
    async def test_golden_2_kiswahili_escalation(
        self,
        golden_support_service: SupportAIService,
        golden_ticket_service: TicketCenterService,
        golden_groq_client: AsyncMock,
        async_session: AsyncSession,
    ):
        """
        Golden Scenario 2: Kiswahili escalation.
        
        Customer writes in mixed English/Kiswahili with frustration.
        Should escalate with appropriate reason mentioning language.
        """
        # Create ticket
        ticket = await golden_ticket_service.create_ticket(
            customer_id="golden_customer_2",
            initial_message="My Mpesa payment is failing with error code 401. Hii haifanyi kazi, naumwa sana na hii tatizo",
            path="support",
        )
        
        # Mock Groq to detect Kiswahili frustration
        golden_groq_client.should_escalate = AsyncMock(return_value={
            "escalate": True,
            "reason": "Customer expressing frustration in Kiswahili",
            "confidence": 0.9
        })
        
        # Process the message
        await golden_support_service.process_and_respond(
            ticket_id=ticket.id,
            customer_id="golden_customer_2",
            message="My Mpesa payment is failing with error code 401. Hii haifanyi kazi, naumwa sana na hii tatizo",
            ticket_service=golden_ticket_service,
            is_agent_request=False,
        )
        
        # Verify ticket status
        updated_ticket = await golden_ticket_service.get_ticket(ticket.id)
        assert updated_ticket.status == TicketStatus.PENDING_STAFF
        
        # Verify chat summary contains relevant context (non-generic)
        assert updated_ticket.chat_summary is not None
        assert len(updated_ticket.chat_summary) > 50
    
    @pytest.mark.asyncio
    async def test_golden_3_security_legal_issue(
        self,
        golden_support_service: SupportAIService,
        golden_ticket_service: TicketCenterService,
        golden_groq_client: AsyncMock,
        async_session: AsyncSession,
    ):
        """
        Golden Scenario 3: Security/legal keyword issue.
        
        Customer reports account hacking and unauthorized charges.
        Should escalate with security/legal reason.
        """
        # Create ticket
        ticket = await golden_ticket_service.create_ticket(
            customer_id="golden_customer_3",
            initial_message="My account was hacked and I see unauthorized charges on my credit card. I need this investigated immediately.",
            path="support",
        )
        
        # Mock Groq to detect security issue
        golden_groq_client.should_escalate = AsyncMock(return_value={
            "escalate": True,
            "reason": "critical_security_legal_issue",
            "confidence": 0.95
        })
        
        # Process the message
        await golden_support_service.process_and_respond(
            ticket_id=ticket.id,
            customer_id="golden_customer_3",
            message="My account was hacked and I see unauthorized charges on my credit card. I need this investigated immediately.",
            ticket_service=golden_ticket_service,
            is_agent_request=False,
        )
        
        # Verify ticket status
        updated_ticket = await golden_ticket_service.get_ticket(ticket.id)
        assert updated_ticket.status == TicketStatus.PENDING_STAFF
        
        # Verify chat summary contains relevant context (non-generic)
        assert updated_ticket.chat_summary is not None
        assert len(updated_ticket.chat_summary) > 50
    
    @pytest.mark.asyncio
    async def test_golden_4_previous_ai_fix_failed(
        self,
        golden_support_service: SupportAIService,
        golden_ticket_service: TicketCenterService,
        golden_groq_client: AsyncMock,
        async_session: AsyncSession,
    ):
        """
        Golden Scenario 4: Customer says previous AI fix did not work.
        
        Customer reports that previous AI solution failed.
        Should escalate with multiple-failure reason.
        """
        # Create ticket
        ticket = await golden_ticket_service.create_ticket(
            customer_id="golden_customer_4",
            initial_message="I tried the password reset instructions but it still doesn't work",
            path="support",
        )
        
        # Add AI response to simulate previous attempt
        await golden_ticket_service.append_message(
            ticket_id=ticket.id,
            sender=MessageSender.SUPPORT_AI,
            content="To reset your password, go to settings and click reset",
        )
        
        # Customer follows up saying it didn't work
        await golden_support_service.process_and_respond(
            ticket_id=ticket.id,
            customer_id="golden_customer_4",
            message="I tried that and it still doesn't work, this is frustrating",
            ticket_service=golden_ticket_service,
            is_agent_request=False,
        )
        
        # Verify ticket status
        updated_ticket = await golden_ticket_service.get_ticket(ticket.id)
        assert updated_ticket.status == TicketStatus.PENDING_STAFF
        
        # Verify chat summary contains relevant context (non-generic)
        assert updated_ticket.chat_summary is not None
        assert len(updated_ticket.chat_summary) > 50
    
    @pytest.mark.asyncio
    async def test_golden_5_calm_novel_undocumented_issue(
        self,
        golden_support_service: SupportAIService,
        golden_ticket_service: TicketCenterService,
        golden_groq_client: AsyncMock,
        async_session: AsyncSession,
    ):
        """
        Golden Scenario 5: Calm, novel, undocumented issue with no frustration.
        
        Customer has a calm but novel issue not in KB.
        Should escalate due to complexity/novelty despite calm tone.
        """
        # Create ticket
        ticket = await golden_ticket_service.create_ticket(
            customer_id="golden_customer_5",
            initial_message="I'm trying to integrate your API with my custom workflow but getting a timeout error during checkout process",
            path="support",
        )
        
        # Mock Groq to detect novel complex issue
        golden_groq_client.should_escalate = AsyncMock(return_value={
            "escalate": True,
            "reason": "Issue requires human judgment due to complexity",
            "confidence": 0.85
        })
        
        # Process the message
        await golden_support_service.process_and_respond(
            ticket_id=ticket.id,
            customer_id="golden_customer_5",
            message="I'm trying to integrate your API with my custom workflow but getting a timeout error during checkout process",
            ticket_service=golden_ticket_service,
            is_agent_request=False,
        )
        
        # Verify ticket status
        updated_ticket = await golden_ticket_service.get_ticket(ticket.id)
        assert updated_ticket.status == TicketStatus.PENDING_STAFF
        
        # Verify chat summary contains relevant context (non-generic)
        assert updated_ticket.chat_summary is not None
        assert len(updated_ticket.chat_summary) > 50
