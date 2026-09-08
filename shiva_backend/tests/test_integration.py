"""
Integration tests for the complete request flow.

Tests the entire flow from customer message through AI routing to ticket creation and resolution.
"""
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.ticket_center.service import TicketCenterService
from app.ai_router.classifier import AIRouter
from app.support_ai.service import SupportAIService
from app.code_ai.service import CodeAIService
from app.clients.qdrant_client import MockQdrantClient, SearchResult
from app.clients.groq_client import MockGroqClient, LLMResponse, ChatMessage
from app.clients.customer_api import MockCustomerApiClient, CustomerAccount
from app.clients.codex_client import MockCodexClient, FixRecommendation, CodeAnalysisRequest
from app.code_ai.readers import MockLogReader, MockCodeReader
from app.db.models import TicketStatus, TicketPath, MessageSender, FixRecommendationStatus


@pytest.fixture
async def integration_ticket_service(async_session: AsyncSession):
    """Create a ticket service for integration tests."""
    return TicketCenterService(async_session)


@pytest.fixture
def mock_qdrant_client():
    """Create a mock Qdrant client with sample documents."""
    client = MockQdrantClient()
    client.add_mock_document(
        SearchResult(
            id="1",
            score=0.85,
            payload={"content": "password reset instructions"},
            content="To reset your password, go to Settings > Security > Change Password",
        )
    )
    client.add_mock_document(
        SearchResult(
            id="2",
            score=0.90,
            payload={"content": "billing information"},
            content="Billing information can be found in your account settings under Subscription",
        )
    )
    return client


@pytest.fixture
def mock_groq_client():
    """Create a mock Groq client with sample responses."""
    client = MockGroqClient()
    client.set_mock_response(
        "password",
        LLMResponse(
            content="To reset your password, go to Settings > Security > Change Password",
            confidence=0.9,
        )
    )
    return client


@pytest.fixture
def mock_customer_api():
    """Create a mock Customer API client."""
    client = MockCustomerApiClient()
    client.add_mock_customer(
        CustomerAccount(
            customer_id="cust_123",
            email="customer@example.com",
            name="Test Customer",
            plan="premium",
            created_at="2024-01-01T00:00:00Z",
        )
    )
    return client


@pytest.fixture
def mock_codex_client():
    """Create a mock Codex client."""
    client = MockCodexClient()
    client.set_mock_fix(
        "error",
        FixRecommendation(
            diff="@@ -1,3 +1,3 @@\n-old code\n+new code",
            explanation="Fixed the error by updating the logic",
            confidence=0.85,
            affected_files=["app/service.py"],
        )
    )
    return client


class TestCompleteRequestFlow:
    """Test the complete request flow from customer message to resolution."""

    @pytest.mark.asyncio
    async def test_customer_support_ai_flow(
        self,
        integration_ticket_service: TicketCenterService,
        mock_qdrant_client: MockQdrantClient,
        mock_groq_client: MockGroqClient,
        mock_customer_api: MockCustomerApiClient,
    ):
        """Test complete flow: Customer message -> AI Router -> Support AI -> Auto-resolution."""
        # Step 1: Customer sends a message
        customer_id = "cust_123"
        message = "How do I reset my password?"
        attachments = []

        # Step 2: Create ticket
        ticket = await integration_ticket_service.create_ticket(
            customer_id=customer_id,
            initial_message=message,
            attachments=attachments,
            path=TicketPath.SUPPORT,
        )

        assert ticket.status == TicketStatus.OPEN
        assert ticket.path == TicketPath.SUPPORT

        # Step 3: AI Router classifies the message
        router = AIRouter(qdrant_client=mock_qdrant_client)
        route_decision = await router.classify(message, attachments)

        assert route_decision == "support"  # Should route to Support AI

        # Step 4: Support AI processes the message
        support_ai = SupportAIService(
            qdrant_client=mock_qdrant_client,
            groq_client=mock_groq_client,
            customer_api_client=mock_customer_api,
        )

        result = await support_ai.handle_customer_message(
            ticket_id=ticket.id,
            customer_id=customer_id,
            message=message,
            ticket_service=integration_ticket_service,
        )

        assert result["action"] == "auto_resolve"
        assert result["confidence"] >= 0.8
        assert result["response"] is not None

        # Step 5: Process and respond (auto-resolve)
        success = await support_ai.process_and_respond(
            ticket_id=ticket.id,
            customer_id=customer_id,
            message=message,
            ticket_service=integration_ticket_service,
        )

        assert success is True

        # Step 6: Verify ticket was auto-resolved
        updated_ticket = await integration_ticket_service.get_ticket(ticket.id)
        assert updated_ticket.status == TicketStatus.RESOLVED_AUTO

        # Step 7: Verify AI response was added
        messages = await integration_ticket_service.get_ticket_messages(ticket.id)
        assert len(messages) == 2  # Initial customer message + AI response
        assert messages[1].sender == MessageSender.SUPPORT_AI
        assert "password" in messages[1].content.lower()

    @pytest.mark.asyncio
    async def test_customer_code_ai_flow(
        self,
        integration_ticket_service: TicketCenterService,
        mock_codex_client: MockCodexClient,
    ):
        """Test complete flow: Customer technical issue -> AI Router -> Code AI -> Fix recommendation."""
        # Step 1: Customer sends a technical message
        customer_id = "cust_456"
        message = "I got a 500 error when trying to upload a file"
        attachments = ["error.log"]

        # Step 2: Create ticket
        ticket = await integration_ticket_service.create_ticket(
            customer_id=customer_id,
            initial_message=message,
            attachments=attachments,
            path=TicketPath.BUG,
        )

        assert ticket.status == TicketStatus.OPEN
        assert ticket.path == TicketPath.BUG

        # Step 3: AI Router classifies the message
        router = AIRouter()
        route_decision = await router.classify(message, attachments)

        assert route_decision == "code"  # Should route to Code AI

        # Step 4: Code AI processes the technical issue
        code_ai = CodeAIService(
            codex_client=mock_codex_client,
            log_reader=MockLogReader(),
            code_reader=MockCodeReader(),
        )

        result = await code_ai.handle_technical_issue(
            ticket_id=ticket.id,
            message=message,
            ticket_service=integration_ticket_service,
            attachments=attachments,
        )

        assert result["success"] is True
        assert result["fix_recommendation_id"] is not None

        # Step 5: Verify ticket was queued for staff
        updated_ticket = await integration_ticket_service.get_ticket(ticket.id)
        assert updated_ticket.status == TicketStatus.PENDING_STAFF

        # Step 6: Verify fix recommendation was created
        assert updated_ticket.fix_recommendation is not None
        assert updated_ticket.fix_recommendation.status == FixRecommendationStatus.PENDING

    @pytest.mark.asyncio
    async def test_staff_approval_flow(
        self,
        integration_ticket_service: TicketCenterService,
        mock_codex_client: MockCodexClient,
    ):
        """Test complete flow: Staff review -> Fix approval -> Apply fix."""
        # Setup: Create a ticket with a pending fix recommendation
        ticket = await integration_ticket_service.create_ticket(
            customer_id="cust_789",
            initial_message="Bug report",
            path=TicketPath.BUG,
        )

        # Create fix recommendation
        await integration_ticket_service.create_fix_recommendation(
            ticket_id=ticket.id,
            diff="fix diff",
            explanation="fix explanation",
        )

        # Queue for staff
        await integration_ticket_service.queue_for_staff(
            ticket_id=ticket.id,
            reason="Fix recommendation ready for review",
        )

        # Step 1: Staff reviews and approves the fix
        fix_rec = await integration_ticket_service.review_fix(
            ticket_id=ticket.id,
            decision=FixRecommendationStatus.APPROVED,
            staff_id="staff_123",
            notes="Looks good, proceed with fix",
        )

        assert fix_rec.status == FixRecommendationStatus.APPROVED
        assert fix_rec.reviewed_by == "staff_123"

        # Step 2: Developer applies the approved fix
        branch_name = await integration_ticket_service.apply_approved_fix(ticket.id)

        assert branch_name == f"fix/ticket-{ticket.id}"

        # Step 3: Staff closes the ticket
        from app.ticket_center.service import UserRole
        closed_ticket = await integration_ticket_service.close_ticket(
            ticket_id=ticket.id,
            closed_by="staff_123",
            role=UserRole.STAFF,
        )

        assert closed_ticket.status == TicketStatus.CLOSED

    @pytest.mark.asyncio
    async def test_customer_reopen_flow(
        self,
        integration_ticket_service: TicketCenterService,
    ):
        """Test customer reopening a resolved ticket."""
        # Create and resolve a ticket
        ticket = await integration_ticket_service.create_ticket(
            customer_id="cust_999",
            initial_message="Initial issue",
            path=TicketPath.SUPPORT,
        )

        await integration_ticket_service.resolve_auto(ticket.id)

        # Verify ticket is resolved
        resolved_ticket = await integration_ticket_service.get_ticket(ticket.id)
        assert resolved_ticket.status == TicketStatus.RESOLVED_AUTO

        # Customer sends a follow-up message (should reopen)
        await integration_ticket_service.append_message(
            ticket_id=ticket.id,
            sender=MessageSender.CUSTOMER,
            content="The fix didn't work, still having issues",
        )

        await integration_ticket_service.reopen_ticket(ticket.id)

        # Verify ticket is reopened
        reopened_ticket = await integration_ticket_service.get_ticket(ticket.id)
        assert reopened_ticket.status == TicketStatus.OPEN

        # Verify message was added
        messages = await integration_ticket_service.get_ticket_messages(ticket.id)
        assert len(messages) == 2  # Initial + follow-up


class TestErrorHandling:
    """Test error handling in the integration flow."""

    @pytest.mark.asyncio
    async def test_ai_router_fallback_on_error(
        self,
        integration_ticket_service: TicketCenterService,
    ):
        """Test that AI Router falls back to staff on errors."""
        class FailingQdrantClient:
            async def embed_text(self, text):
                raise Exception("Qdrant connection failed")

            async def search(self, query_vector, limit, score_threshold):
                raise Exception("Search failed")

        router = AIRouter(qdrant_client=FailingQdrantClient())

        # Should fall back to staff routing on error
        route_decision = await router.classify("How do I reset my password?", [])
        assert route_decision == "staff"

    @pytest.mark.asyncio
    async def test_support_ai_queues_on_low_confidence(
        self,
        integration_ticket_service: TicketCenterService,
        mock_qdrant_client: MockQdrantClient,
        mock_groq_client: MockGroqClient,
        mock_customer_api: MockCustomerApiClient,
    ):
        """Test that Support AI queues for staff on low confidence."""
        # Set up low confidence response
        mock_groq_client.set_mock_response(
            "complex",
            LLMResponse(
                content="I'm not sure about this",
                confidence=0.5,  # Below threshold
            )
        )

        ticket = await integration_ticket_service.create_ticket(
            customer_id="cust_low_conf",
            initial_message="Complex question",
            path=TicketPath.SUPPORT,
        )

        support_ai = SupportAIService(
            qdrant_client=mock_qdrant_client,
            groq_client=mock_groq_client,
            customer_api_client=mock_customer_api,
            confidence_threshold=0.8,  # Higher than mock response
        )

        success = await support_ai.process_and_respond(
            ticket_id=ticket.id,
            customer_id="cust_low_conf",
            message="Complex question",
            ticket_service=integration_ticket_service,
        )

        # Should not auto-respond due to low confidence
        assert success is False

        # Should be queued for staff
        updated_ticket = await integration_ticket_service.get_ticket(ticket.id)
        assert updated_ticket.status == TicketStatus.PENDING_STAFF


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
