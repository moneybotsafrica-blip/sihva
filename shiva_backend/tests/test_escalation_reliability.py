"""
Regression tests for escalation reliability.

Tests ensure that escalation decisions are reliable across different scenarios:
- Explicit human agent requests always escalate
- Kiswahili conversations where AI intends to escalate produce tickets
- Ticket escalation reasons match actual triggers
- Structured escalation decisions work correctly
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy.ext.asyncio import AsyncSession

from app.support_ai.service import SupportAIService
from app.clients.qdrant_client import QdrantClientInterface, SearchResult
from app.clients.groq_client import GroqClientInterface, ChatMessage, LLMResponse
from app.ticket_center.service import TicketCenterService
from app.db.models import TicketStatus, MessageSender


@pytest.fixture
def mock_qdrant_client():
    """Mock Qdrant client for testing."""
    client = AsyncMock(spec=QdrantClientInterface)
    client.embed_text = AsyncMock(return_value=[0.1, 0.2, 0.3])
    client.search = AsyncMock(return_value=[])
    return client


@pytest.fixture
def mock_groq_client():
    """Mock Groq client for testing."""
    client = AsyncMock(spec=GroqClientInterface)
    
    # Default response for regular chat completion
    client.chat_completion = AsyncMock(return_value=LLMResponse(
        content="I can help you with that. Here's the solution...",
        confidence=0.8,
        metadata={"agent_used": "GeneralSupportAgent"}
    ))
    
    # Default structured escalation decision (no escalation)
    client.should_escalate = AsyncMock(return_value={
        "escalate": False,
        "reason": "AI can handle this issue",
        "confidence": 0.8
    })
    
    # Mock out-of-scope analysis
    client.is_out_of_scope = AsyncMock(return_value={
        "is_out_of_scope": False,
        "reasoning": "Issue is within scope",
        "confidence": 0.8
    })
    
    return client


@pytest.fixture
async def escalation_ticket_service(async_session: AsyncSession):
    """Create a ticket service for escalation tests."""
    return TicketCenterService(async_session)


@pytest.fixture
def escalation_support_service(mock_qdrant_client, mock_groq_client):
    """Create a support AI service for escalation tests."""
    return SupportAIService(
        qdrant_client=mock_qdrant_client,
        groq_client=mock_groq_client,
        confidence_threshold=0.7
    )


class TestExplicitAgentRequestEscalation:
    """Test that explicit agent requests always escalate on first turn."""
    
    @pytest.mark.asyncio
    async def test_explicit_agent_request_escalates_first_turn(
        self,
        escalation_support_service: SupportAIService,
        escalation_ticket_service: TicketCenterService,
        async_session: AsyncSession,
    ):
        """Test that explicit agent request escalates on first turn with no prior AI attempts."""
        # Create a ticket
        ticket = await escalation_ticket_service.create_ticket(
            customer_id="test_customer_001",
            initial_message="I need help with my account",
            path="support",
        )
        
        # Process message with explicit agent request (includes problem description)
        result = await escalation_support_service.handle_customer_message(
            ticket_id=ticket.id,
            customer_id="test_customer_001",
            message="I need to speak to a human agent about my payment issue",
            ticket_service=escalation_ticket_service,
            is_agent_request=True,  # Explicit agent request
        )
        
        # Should escalate directly
        assert result["should_queue"] is True
        assert result["action"] == "queue_for_staff"
        assert result["escalation_reason"] == "explicit_agent_request"
        
        # Note: Ticket status is updated by process_and_respond, not handle_customer_message
        # The escalation decision is what we're testing here


class TestKiswahiliEscalation:
    """Test that Kiswahili conversations where AI intends to escalate produce tickets."""
    
    @pytest.mark.asyncio
    async def test_kiswahili_escalation_produces_ticket(
        self,
        escalation_support_service: SupportAIService,
        escalation_ticket_service: TicketCenterService,
        mock_groq_client: AsyncMock,
        async_session: AsyncSession,
    ):
        """Test that Kiswahili conversation where AI intends to escalate produces a ticket."""
        # Create a ticket
        ticket = await escalation_ticket_service.create_ticket(
            customer_id="test_customer_002",
            initial_message="Ninasaidia nini?",
            path="support",
        )
        
        # Mock Groq to decide escalation for Kiswahili message
        mock_groq_client.should_escalate = AsyncMock(return_value={
            "escalate": True,
            "reason": "Customer expressing frustration in Kiswahili",
            "confidence": 0.9
        })
        
        # Process mixed English/Kiswahili message with detailed problem description
        result = await escalation_support_service.handle_customer_message(
            ticket_id=ticket.id,
            customer_id="test_customer_002",
            message="My Mpesa payment is failing with error code 401 when I try to checkout. Hii haifanyi kazi, naumwa sana na hii tatizo",
            ticket_service=escalation_ticket_service,
            is_agent_request=False,
            product_context={
                "product_id": "product_123",
                "product_name": "Shiva E-Commerce",
                "enabled_modules": ["checkout", "payment"],
                "client_entitled": True,
                "relevant_knowledge_articles": []
            },
        )
        
        # Should escalate based on structured decision
        assert result["should_queue"] is True
        assert result["action"] == "queue_for_staff"
        assert "groq_ai_decision" in result["escalation_reason"]
        
        # Note: Ticket status is updated by process_and_respond, not handle_customer_message


class TestEscalationReasonAccuracy:
    """Test that ticket escalation reasons match actual triggers."""
    
    @pytest.mark.asyncio
    async def test_security_legal_issue_reason(
        self,
        escalation_support_service: SupportAIService,
        escalation_ticket_service: TicketCenterService,
        async_session: AsyncSession,
    ):
        """Test that security/legal issues get the correct escalation reason."""
        # Create a ticket
        ticket = await escalation_ticket_service.create_ticket(
            customer_id="test_customer_003",
            initial_message="My account was hacked",
            path="support",
        )
        
        # Process security issue with detailed problem description including specific details
        result = await escalation_support_service.handle_customer_message(
            ticket_id=ticket.id,
            customer_id="test_customer_003",
            message="My account was hacked and I see unauthorized charges on my credit card statement from yesterday. I was trying to access my profile page when I saw the error message about unauthorized access",
            ticket_service=escalation_ticket_service,
            is_agent_request=False,
        )
        
        # Should escalate with security reason
        assert result["should_queue"] is True
        assert result["action"] == "queue_for_staff"
        assert result["escalation_reason"] == "critical_security_legal_issue"
    
    @pytest.mark.asyncio
    async def test_multiple_failed_attempts_reason(
        self,
        escalation_support_service: SupportAIService,
        escalation_ticket_service: TicketCenterService,
        async_session: AsyncSession,
    ):
        """Test that multiple failed attempts get the correct escalation reason."""
        # Create a ticket
        ticket = await escalation_ticket_service.create_ticket(
            customer_id="test_customer_004",
            initial_message="My payment is failing",
            path="support",
        )
        
        # Add previous AI attempts (need 3+ for multiple failed attempts escalation)
        await escalation_ticket_service.append_message(
            ticket_id=ticket.id,
            sender=MessageSender.SUPPORT_AI,
            content="Try checking your payment method settings",
        )
        await escalation_ticket_service.append_message(
            ticket_id=ticket.id,
            sender=MessageSender.CUSTOMER,
            content="That didn't help, still failing",
        )
        await escalation_ticket_service.append_message(
            ticket_id=ticket.id,
            sender=MessageSender.SUPPORT_AI,
            content="Try clearing your browser cache",
        )
        await escalation_ticket_service.append_message(
            ticket_id=ticket.id,
            sender=MessageSender.CUSTOMER,
            content="Still not working, this is terrible",
        )
        await escalation_ticket_service.append_message(
            ticket_id=ticket.id,
            sender=MessageSender.SUPPORT_AI,
            content="Try using a different browser",
        )
        await escalation_ticket_service.append_message(
            ticket_id=ticket.id,
            sender=MessageSender.CUSTOMER,
            content="I tried that and it still doesn't work",
        )
        
        # Process message indicating solution failure
        result = await escalation_support_service.handle_customer_message(
            ticket_id=ticket.id,
            customer_id="test_customer_004",
            message="I tried that and it still doesn't work, this is frustrating",
            ticket_service=escalation_ticket_service,
            is_agent_request=False,
        )
        
        # Should escalate with multiple failed attempts reason
        assert result["should_queue"] is True
        assert result["action"] == "queue_for_staff"
        assert "multiple_failed_attempts" in result["escalation_reason"]


class TestStructuredEscalationDecision:
    """Test that structured escalation decisions work correctly."""
    
    @pytest.mark.asyncio
    async def test_structured_escalation_true(
        self,
        escalation_support_service: SupportAIService,
        escalation_ticket_service: TicketCenterService,
        mock_groq_client: AsyncMock,
        async_session: AsyncSession,
    ):
        """Test that structured escalation decision with escalate=True works."""
        # Create a ticket
        ticket = await escalation_ticket_service.create_ticket(
            customer_id="test_customer_005",
            initial_message="Complex issue",
            path="support",
        )
        
        # Mock Groq to decide escalation
        mock_groq_client.should_escalate = AsyncMock(return_value={
            "escalate": True,
            "reason": "Issue requires human judgment due to complexity",
            "confidence": 0.85
        })
        
        # Process message with detailed problem description
        result = await escalation_support_service.handle_customer_message(
            ticket_id=ticket.id,
            customer_id="test_customer_005",
            message="This is a complex issue that needs human review. My integration with the payment gateway is failing with a timeout error during checkout process",
            ticket_service=escalation_ticket_service,
            is_agent_request=False,
            product_context={
                "product_id": "product_456",
                "product_name": "Shiva POS",
                "enabled_modules": ["payment"],
                "client_entitled": True,
                "relevant_knowledge_articles": []
            },
        )
        
        # Should escalate based on structured decision
        assert result["should_queue"] is True
        assert result["action"] == "queue_for_staff"
        assert "groq_ai_decision" in result["escalation_reason"]
        assert "human judgment" in result["escalation_reason"]
    
    @pytest.mark.asyncio
    async def test_structured_escalation_false(
        self,
        escalation_support_service: SupportAIService,
        escalation_ticket_service: TicketCenterService,
        mock_groq_client: AsyncMock,
        async_session: AsyncSession,
    ):
        """Test that structured escalation decision with escalate=False works."""
        # Create a ticket
        ticket = await escalation_ticket_service.create_ticket(
            customer_id="test_customer_006",
            initial_message="Simple question",
            path="support",
        )
        
        # Mock Groq to decide no escalation
        mock_groq_client.should_escalate = AsyncMock(return_value={
            "escalate": False,
            "reason": "AI can provide clear solution",
            "confidence": 0.9
        })
        
        # Process message with KB context (to avoid complexity escalation)
        # Mock Qdrant to return KB results
        from app.clients.qdrant_client import SearchResult
        escalation_support_service.qdrant_client.search = AsyncMock(return_value=[
            SearchResult(id="kb_1", score=0.9, payload={"content": "Password reset instructions"}, content="Password reset instructions")
        ])
        
        result = await escalation_support_service.handle_customer_message(
            ticket_id=ticket.id,
            customer_id="test_customer_006",
            message="How do I reset my password? I have access to my email and want to reset it",
            ticket_service=escalation_ticket_service,
            is_agent_request=False,
        )
        
        # Should not escalate
        assert result["should_queue"] is False
        assert result["action"] == "auto_resolve"


class TestAIAttemptsCap:
    """Test that AI attempts cap forces escalation to prevent endless AI loops."""
    
    @pytest.fixture
    async def cap_support_service(
        self,
        mock_qdrant_client: AsyncMock,
        mock_groq_client: AsyncMock,
    ):
        """Create support service for AI attempts cap testing."""
        return SupportAIService(
            qdrant_client=mock_qdrant_client,
            groq_client=mock_groq_client,
            confidence_threshold=0.3,
        )
    
    @pytest.fixture
    async def cap_ticket_service(self, async_session: AsyncSession):
        """Create ticket service for AI attempts cap testing."""
        return TicketCenterService(async_session)
    
    @pytest.mark.asyncio
    async def test_ai_attempts_cap_forces_escalation(
        self,
        cap_support_service: SupportAIService,
        cap_ticket_service: TicketCenterService,
        mock_groq_client: AsyncMock,
        async_session: AsyncSession,
    ):
        """Test that reaching AI attempts cap forces escalation regardless of confidence."""
        # Create a ticket
        ticket = await cap_ticket_service.create_ticket(
            customer_id="test_customer_cap",
            initial_message="Test issue",
            path="support",
        )
        
        # Increment AI attempts to reach the cap (default is 5)
        for _ in range(5):
            await cap_ticket_service.increment_ai_attempts(ticket.id)
        
        # Mock Groq to say NO escalation (high confidence)
        mock_groq_client.should_escalate = AsyncMock(return_value={
            "escalate": False,
            "reason": "AI can handle this issue",
            "confidence": 0.95
        })
        
        # Mock Qdrant to return KB results (to avoid complexity escalation)
        from app.clients.qdrant_client import SearchResult
        cap_support_service.qdrant_client.search = AsyncMock(return_value=[
            SearchResult(id="kb_1", score=0.9, payload={"content": "Solution"}, content="Solution content")
        ])
        
        result = await cap_support_service.handle_customer_message(
            ticket_id=ticket.id,
            customer_id="test_customer_cap",
            message="Another follow-up question",
            ticket_service=cap_ticket_service,
            is_agent_request=False,
        )
        
        # Should escalate due to cap, despite Groq saying no
        assert result["should_queue"] is True
        assert result["action"] == "queue_for_staff"
        assert "ai_attempts_cap_reached" in result["escalation_reason"]
    
    @pytest.mark.asyncio
    async def test_ai_attempts_below_cap_no_forced_escalation(
        self,
        cap_support_service: SupportAIService,
        cap_ticket_service: TicketCenterService,
        mock_groq_client: AsyncMock,
        async_session: AsyncSession,
    ):
        """Test that below cap, escalation decision respects Groq's decision."""
        # Create a ticket
        ticket = await cap_ticket_service.create_ticket(
            customer_id="test_customer_cap2",
            initial_message="Test issue",
            path="support",
        )
        
        # Increment AI attempts but stay below cap (3 out of 5)
        for _ in range(3):
            await cap_ticket_service.increment_ai_attempts(ticket.id)
        
        # Mock Groq to say NO escalation
        mock_groq_client.should_escalate = AsyncMock(return_value={
            "escalate": False,
            "reason": "AI can handle this issue",
            "confidence": 0.9
        })
        
        # Mock Qdrant to return KB results
        from app.clients.qdrant_client import SearchResult
        cap_support_service.qdrant_client.search = AsyncMock(return_value=[
            SearchResult(id="kb_1", score=0.9, payload={"content": "Solution"}, content="Solution content")
        ])
        
        result = await cap_support_service.handle_customer_message(
            ticket_id=ticket.id,
            customer_id="test_customer_cap2",
            message="Follow-up question",
            ticket_service=cap_ticket_service,
            is_agent_request=False,
        )
        
        # Should NOT escalate (below cap, Groq said no)
        assert result["should_queue"] is False
        assert result["action"] == "auto_resolve"
    
    @pytest.mark.asyncio
    async def test_structured_escalation_fallback_to_phrase_matching(
        self,
        escalation_support_service: SupportAIService,
        escalation_ticket_service: TicketCenterService,
        mock_groq_client: AsyncMock,
        async_session: AsyncSession,
    ):
        """Test that structured escalation falls back to phrase-matching on error."""
        # Create a ticket
        ticket = await escalation_ticket_service.create_ticket(
            customer_id="test_customer_007",
            initial_message="Test issue",
            path="support",
        )
        
        # Mock Groq to raise error on structured decision
        mock_groq_client.should_escalate = AsyncMock(side_effect=Exception("Groq API error"))
        
        # Mock regular chat completion to include escalation phrase
        mock_groq_client.chat_completion = AsyncMock(return_value=LLMResponse(
            content="I'll create a ticket for this issue",
            confidence=0.7,
            metadata={}
        ))
        
        # Process message with problem description
        result = await escalation_support_service.handle_customer_message(
            ticket_id=ticket.id,
            customer_id="test_customer_007",
            message="This needs to be escalated. My payment integration is failing with timeout errors",
            ticket_service=escalation_ticket_service,
            is_agent_request=False,
            product_context={
                "product_id": "product_789",
                "product_name": "Shiva E-Commerce",
                "enabled_modules": ["payment"],
                "client_entitled": True,
                "relevant_knowledge_articles": []
            },
        )
        
        # Should still escalate using fallback phrase-matching
        assert result["should_queue"] is True
        assert result["action"] == "queue_for_staff"
        assert "fallback_phrase_matching" in result["escalation_reason"]


class TestExplicitTicketRequest:
    """Test that explicit ticket requests are detected and escalated correctly."""
    
    @pytest.mark.asyncio
    async def test_direct_ticket_request_escalates(
        self,
        escalation_support_service: SupportAIService,
        escalation_ticket_service: TicketCenterService,
        mock_groq_client: AsyncMock,
        async_session: AsyncSession,
    ):
        """Test that direct ticket request (e.g., 'raise a ticket') escalates immediately."""
        # Create a ticket
        ticket = await escalation_ticket_service.create_ticket(
            customer_id="test_customer_ticket_001",
            initial_message="Issue with checkout",
            path="support",
        )
        
        # Process message with direct ticket request
        result = await escalation_support_service.handle_customer_message(
            ticket_id=ticket.id,
            customer_id="test_customer_ticket_001",
            message="this still isn't working, please raise a ticket",
            ticket_service=escalation_ticket_service,
            is_agent_request=False,
        )
        
        # Should escalate immediately
        assert result["should_queue"] is True
        assert result["action"] == "queue_for_staff"
        assert result["escalation_reason"] == "explicit_ticket_request"
        assert "ticket" in result["response"].lower()
    
    @pytest.mark.asyncio
    async def test_informational_ticket_question_does_not_escalate(
        self,
        escalation_support_service: SupportAIService,
        escalation_ticket_service: TicketCenterService,
        mock_groq_client: AsyncMock,
        async_session: AsyncSession,
    ):
        """Test that informational ticket question (e.g., 'how do I raise a ticket?') does NOT escalate."""
        # Create a ticket
        ticket = await escalation_ticket_service.create_ticket(
            customer_id="test_customer_ticket_002",
            initial_message="Question about tickets",
            path="support",
        )
        
        # Process message with informational question
        result = await escalation_support_service.handle_customer_message(
            ticket_id=ticket.id,
            customer_id="test_customer_ticket_002",
            message="how do I raise a ticket?",
            ticket_service=escalation_ticket_service,
            is_agent_request=False,
        )
        
        # Should NOT escalate - it's an informational question
        assert result["should_queue"] is False
        assert result["action"] != "queue_for_staff"
    
    @pytest.mark.asyncio
    async def test_various_ticket_request_phrases_escalate(
        self,
        escalation_support_service: SupportAIService,
        escalation_ticket_service: TicketCenterService,
        mock_groq_client: AsyncMock,
        async_session: AsyncSession,
    ):
        """Test that various ticket request phrases all escalate correctly."""
        ticket_request_phrases = [
            "please open a ticket",
            "can you create a ticket for me",
            "I need a ticket created",
            "file a ticket for this",
            "log a ticket please",
            "escalate this to a ticket",
        ]
        
        for i, phrase in enumerate(ticket_request_phrases):
            # Create a ticket for each test
            ticket = await escalation_ticket_service.create_ticket(
                customer_id=f"test_customer_ticket_00{i+3}",
                initial_message="Issue",
                path="support",
            )
            
            # Process message with ticket request phrase
            result = await escalation_support_service.handle_customer_message(
                ticket_id=ticket.id,
                customer_id=f"test_customer_ticket_00{i+3}",
                message=f"this problem persists, {phrase}",
                ticket_service=escalation_ticket_service,
                is_agent_request=False,
            )
            
            # Should escalate for all phrases
            assert result["should_queue"] is True, f"Failed for phrase: {phrase}"
            assert result["action"] == "queue_for_staff"
            assert result["escalation_reason"] == "explicit_ticket_request"



if __name__ == "__main__":
    pytest.main([__file__, "-v"])