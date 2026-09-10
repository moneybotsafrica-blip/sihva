import pytest
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Ticket,
    TicketMessage,
    FixRecommendation,
    TicketStatus,
    TicketPath,
    MessageSender,
    FixRecommendationStatus,
)
from app.ticket_center.service import TicketCenterService, UserRole


@pytest.fixture
async def ticket_service(async_session: AsyncSession):
    """Create a ticket service instance."""
    return TicketCenterService(async_session)


@pytest.fixture
async def sample_ticket(ticket_service: TicketCenterService):
    """Create a sample ticket for testing."""
    return await ticket_service.create_ticket(
        customer_id="cust_123",
        initial_message="I need help with my account",
        path=TicketPath.SUPPORT,
    )


class TestTicketCreation:
    """Test ticket creation functionality."""

    @pytest.mark.asyncio
    async def test_create_ticket_success(self, ticket_service: TicketCenterService):
        """Test successful ticket creation."""
        ticket = await ticket_service.create_ticket(
            customer_id="cust_123",
            initial_message="I need help",
            path=TicketPath.SUPPORT,
        )

        assert ticket.id is not None
        assert ticket.customer_id == "cust_123"
        assert ticket.status == TicketStatus.OPEN
        assert ticket.path == TicketPath.SUPPORT
        assert ticket.assigned_staff_id is None

    @pytest.mark.asyncio
    async def test_create_ticket_with_attachments(
        self, ticket_service: TicketCenterService
    ):
        """Test ticket creation with attachments."""
        attachments = ["file1.pdf", "file2.png"]
        ticket = await ticket_service.create_ticket(
            customer_id="cust_123",
            initial_message="Here are my files",
            attachments=attachments,
        )

        # Verify initial message was created
        messages = await ticket_service.get_ticket_messages(ticket.id)
        assert len(messages) == 1
        assert messages[0].sender == MessageSender.CUSTOMER
        assert messages[0].content == "Here are my files"

    @pytest.mark.asyncio
    async def test_create_ticket_initial_message_added(
        self, ticket_service: TicketCenterService
    ):
        """Test that initial message is automatically added to ticket."""
        ticket = await ticket_service.create_ticket(
            customer_id="cust_123",
            initial_message="Hello, I need help",
        )

        messages = await ticket_service.get_ticket_messages(ticket.id)
        assert len(messages) == 1
        assert messages[0].content == "Hello, I need help"
        assert messages[0].sender == MessageSender.CUSTOMER

    @pytest.mark.asyncio
    async def test_duplicate_open_ticket_prevention(
        self, ticket_service: TicketCenterService
    ):
        """Test that customers cannot have multiple open tickets."""
        # Create first ticket
        await ticket_service.create_ticket(
            customer_id="cust_123",
            initial_message="First issue",
        )

        # Try to create second ticket for same customer
        with pytest.raises(ValueError, match="already has an open ticket"):
            await ticket_service.create_ticket(
                customer_id="cust_123",
                initial_message="Second issue",
            )


class TestTicketRetrieval:
    """Test ticket retrieval functionality."""

    @pytest.mark.asyncio
    async def test_get_ticket_by_id(self, ticket_service: TicketCenterService):
        """Test retrieving a ticket by ID."""
        created_ticket = await ticket_service.create_ticket(
            customer_id="cust_123",
            initial_message="Test message",
        )

        retrieved_ticket = await ticket_service.get_ticket(created_ticket.id)
        assert retrieved_ticket is not None
        assert retrieved_ticket.id == created_ticket.id
        assert retrieved_ticket.customer_id == "cust_123"

    @pytest.mark.asyncio
    async def test_get_nonexistent_ticket(self, ticket_service: TicketCenterService):
        """Test retrieving a non-existent ticket."""
        ticket = await ticket_service.get_ticket("nonexistent_id")
        assert ticket is None

    @pytest.mark.asyncio
    async def test_get_customer_ticket(
        self, ticket_service: TicketCenterService, sample_ticket: Ticket
    ):
        """Test retrieving a customer's open ticket."""
        customer_ticket = await ticket_service.get_customer_ticket("cust_123")
        assert customer_ticket is not None
        assert customer_ticket.id == sample_ticket.id
        assert customer_ticket.customer_id == "cust_123"

    @pytest.mark.asyncio
    async def test_get_customer_ticket_none(
        self, ticket_service: TicketCenterService
    ):
        """Test retrieving ticket for customer with no open ticket."""
        customer_ticket = await ticket_service.get_customer_ticket("nonexistent_cust")
        assert customer_ticket is None


class TestMessageManagement:
    """Test message appending and retrieval."""

    @pytest.mark.asyncio
    async def test_append_message(
        self, ticket_service: TicketCenterService, sample_ticket: Ticket
    ):
        """Test appending a message to a ticket."""
        message = await ticket_service.append_message(
            ticket_id=sample_ticket.id,
            sender=MessageSender.STAFF,
            content="Here's the solution",
        )

        assert message.id is not None
        assert message.ticket_id == sample_ticket.id
        assert message.sender == MessageSender.STAFF
        assert message.content == "Here's the solution"

    @pytest.mark.asyncio
    async def test_append_message_updates_timestamp(
        self, ticket_service: TicketCenterService, sample_ticket: Ticket
    ):
        """Test that appending a message updates ticket timestamp."""
        original_updated = sample_ticket.updated_at

        # Small delay to ensure timestamp difference
        import asyncio
        await asyncio.sleep(0.01)

        await ticket_service.append_message(
            ticket_id=sample_ticket.id,
            sender=MessageSender.STAFF,
            content="New message",
        )

        updated_ticket = await ticket_service.get_ticket(sample_ticket.id)
        assert updated_ticket.updated_at > original_updated

    @pytest.mark.asyncio
    async def test_get_ticket_messages(
        self, ticket_service: TicketCenterService, sample_ticket: Ticket
    ):
        """Test retrieving all messages for a ticket."""
        # Add multiple messages
        await ticket_service.append_message(
            ticket_id=sample_ticket.id,
            sender=MessageSender.STAFF,
            content="Response 1",
        )
        await ticket_service.append_message(
            ticket_id=sample_ticket.id,
            sender=MessageSender.CUSTOMER,
            content="Follow-up",
        )

        messages = await ticket_service.get_ticket_messages(sample_ticket.id)
        assert len(messages) == 3  # Initial + 2 new
        assert messages[0].sender == MessageSender.CUSTOMER  # Initial message

    @pytest.mark.asyncio
    async def test_append_message_nonexistent_ticket(
        self, ticket_service: TicketCenterService
    ):
        """Test appending message to non-existent ticket."""
        with pytest.raises(ValueError, match="not found"):
            await ticket_service.append_message(
                ticket_id="nonexistent_id",
                sender=MessageSender.STAFF,
                content="Test",
            )


class TestTicketStatusTransitions:
    """Test ticket status state machine."""

    @pytest.mark.asyncio
    async def test_valid_status_transition(
        self, ticket_service: TicketCenterService, sample_ticket: Ticket
    ):
        """Test valid status transition from OPEN to IN_PROGRESS."""
        updated_ticket = await ticket_service.update_ticket_status(
            ticket_id=sample_ticket.id,
            new_status=TicketStatus.IN_PROGRESS,
        )

        assert updated_ticket.status == TicketStatus.IN_PROGRESS

    @pytest.mark.asyncio
    async def test_invalid_status_transition(
        self, ticket_service: TicketCenterService, sample_ticket: Ticket
    ):
        """Test invalid status transition."""
        # First transition to a terminal state
        await ticket_service.update_ticket_status(
            ticket_id=sample_ticket.id,
            new_status=TicketStatus.CLOSED,
        )
        
        # Try to transition from CLOSED to a non-OPEN state (should fail)
        with pytest.raises(ValueError, match="Invalid status transition"):
            await ticket_service.update_ticket_status(
                ticket_id=sample_ticket.id,
                new_status=TicketStatus.IN_PROGRESS,  # Can't go from CLOSED to IN_PROGRESS
            )

    @pytest.mark.asyncio
    async def test_queue_for_staff(
        self, ticket_service: TicketCenterService, sample_ticket: Ticket
    ):
        """Test queuing ticket for staff review."""
        ticket = await ticket_service.queue_for_staff(
            ticket_id=sample_ticket.id,
            reason="Requires human review",
        )

        assert ticket.status == TicketStatus.PENDING_STAFF

    @pytest.mark.asyncio
    async def test_assign_staff(
        self, ticket_service: TicketCenterService, sample_ticket: Ticket
    ):
        """Test assigning staff to a ticket."""
        ticket = await ticket_service.assign_staff(
            ticket_id=sample_ticket.id,
            staff_id="staff_123",
        )

        assert ticket.assigned_staff_id == "staff_123"

    @pytest.mark.asyncio
    async def test_resolve_auto(
        self, ticket_service: TicketCenterService, sample_ticket: Ticket
    ):
        """Test auto-resolving a ticket."""
        ticket = await ticket_service.resolve_auto(ticket_id=sample_ticket.id)

        assert ticket.status == TicketStatus.RESOLVED_AUTO

    @pytest.mark.asyncio
    async def test_close_ticket_by_staff(
        self, ticket_service: TicketCenterService, sample_ticket: Ticket
    ):
        """Test closing a ticket by staff."""
        ticket = await ticket_service.close_ticket(
            ticket_id=sample_ticket.id,
            closed_by="staff_123",
            role=UserRole.STAFF,
        )

        assert ticket.status == TicketStatus.CLOSED

    @pytest.mark.asyncio
    async def test_close_ticket_by_developer(
        self, ticket_service: TicketCenterService, sample_ticket: Ticket
    ):
        """Test closing a ticket by developer."""
        ticket = await ticket_service.close_ticket(
            ticket_id=sample_ticket.id,
            closed_by="dev_123",
            role=UserRole.DEVELOPER,
        )

        assert ticket.status == TicketStatus.CLOSED

    @pytest.mark.asyncio
    async def test_close_ticket_by_customer_forbidden(
        self, ticket_service: TicketCenterService, sample_ticket: Ticket
    ):
        """Test that customers cannot close tickets that are not RESOLVED_AUTO."""
        # Customers should not be able to close OPEN tickets
        with pytest.raises(ValueError, match="Customers can only close tickets that are RESOLVED_AUTO"):
            await ticket_service.close_ticket(
                ticket_id=sample_ticket.id,
                closed_by="cust_123",
                role=UserRole.CUSTOMER,
            )
        
        # Customers should not be able to close PENDING_STAFF tickets
        await ticket_service.queue_for_staff(
            ticket_id=sample_ticket.id,
            reason="Test escalation",
        )
        with pytest.raises(ValueError, match="Customers can only close tickets that are RESOLVED_AUTO"):
            await ticket_service.close_ticket(
                ticket_id=sample_ticket.id,
                closed_by="cust_123",
                role=UserRole.CUSTOMER,
            )
    
    @pytest.mark.asyncio
    async def test_close_ticket_by_customer_allowed_resolved_auto(
        self, ticket_service: TicketCenterService, sample_ticket: Ticket
    ):
        """Test that customers can close their own RESOLVED_AUTO tickets."""
        # First resolve the ticket
        await ticket_service.resolve_auto(ticket_id=sample_ticket.id)
        
        # Then customer should be able to close it
        ticket = await ticket_service.close_ticket(
            ticket_id=sample_ticket.id,
            closed_by="cust_123",
            role=UserRole.CUSTOMER,
        )
        
        assert ticket.status == TicketStatus.CLOSED

    @pytest.mark.asyncio
    async def test_reopen_resolved_ticket(
        self, ticket_service: TicketCenterService, sample_ticket: Ticket
    ):
        """Test reopening a resolved ticket."""
        # First resolve the ticket
        await ticket_service.resolve_auto(ticket_id=sample_ticket.id)

        # Then reopen it
        ticket = await ticket_service.reopen_ticket(ticket_id=sample_ticket.id)

        assert ticket.status == TicketStatus.OPEN

    @pytest.mark.asyncio
    async def test_reopen_closed_ticket(
        self, ticket_service: TicketCenterService, sample_ticket: Ticket
    ):
        """Test reopening a closed ticket."""
        # First close the ticket
        await ticket_service.close_ticket(
            ticket_id=sample_ticket.id,
            closed_by="staff_123",
            role=UserRole.STAFF,
        )

        # Then reopen it
        ticket = await ticket_service.reopen_ticket(ticket_id=sample_ticket.id)

        assert ticket.status == TicketStatus.OPEN

    @pytest.mark.asyncio
    async def test_reopen_active_ticket_forbidden(
        self, ticket_service: TicketCenterService, sample_ticket: Ticket
    ):
        """Test that active tickets cannot be reopened."""
        with pytest.raises(ValueError, match="Cannot reopen ticket"):
            await ticket_service.reopen_ticket(ticket_id=sample_ticket.id)


class TestFixRecommendations:
    """Test fix recommendation functionality."""

    @pytest.mark.asyncio
    async def test_create_fix_recommendation(
        self, ticket_service: TicketCenterService, sample_ticket: Ticket
    ):
        """Test creating a fix recommendation."""
        fix_rec = await ticket_service.create_fix_recommendation(
            ticket_id=sample_ticket.id,
            diff="@@ -1,3 +1,3 @@\n-old\n+new",
            explanation="Fixed the bug by updating the logic",
        )

        assert fix_rec.id is not None
        assert fix_rec.ticket_id == sample_ticket.id
        assert fix_rec.status == FixRecommendationStatus.PENDING
        assert fix_rec.diff == "@@ -1,3 +1,3 @@\n-old\n+new"
        assert fix_rec.explanation == "Fixed the bug by updating the logic"

    @pytest.mark.asyncio
    async def test_duplicate_fix_recommendation_forbidden(
        self, ticket_service: TicketCenterService, sample_ticket: Ticket
    ):
        """Test that duplicate fix recommendations are forbidden."""
        await ticket_service.create_fix_recommendation(
            ticket_id=sample_ticket.id,
            diff="fix1",
            explanation="explanation1",
        )

        with pytest.raises(ValueError, match="already exists"):
            await ticket_service.create_fix_recommendation(
                ticket_id=sample_ticket.id,
                diff="fix2",
                explanation="explanation2",
            )

    @pytest.mark.asyncio
    async def test_approve_fix(
        self, ticket_service: TicketCenterService, sample_ticket: Ticket
    ):
        """Test approving a fix recommendation."""
        # Create fix recommendation
        await ticket_service.create_fix_recommendation(
            ticket_id=sample_ticket.id,
            diff="fix",
            explanation="explanation",
        )

        # Approve it
        fix_rec = await ticket_service.review_fix(
            ticket_id=sample_ticket.id,
            decision=FixRecommendationStatus.APPROVED,
            staff_id="staff_123",
            notes="Looks good",
        )

        assert fix_rec.status == FixRecommendationStatus.APPROVED
        assert fix_rec.reviewed_by == "staff_123"
        assert fix_rec.notes == "Looks good"
        assert fix_rec.reviewed_at is not None

    @pytest.mark.asyncio
    async def test_reject_fix(
        self, ticket_service: TicketCenterService, sample_ticket: Ticket
    ):
        """Test rejecting a fix recommendation."""
        await ticket_service.create_fix_recommendation(
            ticket_id=sample_ticket.id,
            diff="fix",
            explanation="explanation",
        )

        fix_rec = await ticket_service.review_fix(
            ticket_id=sample_ticket.id,
            decision=FixRecommendationStatus.REJECTED,
            staff_id="staff_123",
            notes="Not correct",
        )

        assert fix_rec.status == FixRecommendationStatus.REJECTED
        assert fix_rec.notes == "Not correct"

    @pytest.mark.asyncio
    async def test_reject_fix(
        self, ticket_service: TicketCenterService, sample_ticket: Ticket
    ):
        """Test rejecting a fix recommendation."""
        await ticket_service.create_fix_recommendation(
            ticket_id=sample_ticket.id,
            diff="fix",
            explanation="explanation",
        )

        fix_rec = await ticket_service.review_fix(
            ticket_id=sample_ticket.id,
            decision=FixRecommendationStatus.REJECTED,
            staff_id="staff_123",
            notes="Need more context",
        )

        assert fix_rec.status == FixRecommendationStatus.REJECTED
        assert fix_rec.notes == "Need more context"

    @pytest.mark.asyncio
    async def test_review_non_pending_fix_forbidden(
        self, ticket_service: TicketCenterService, sample_ticket: Ticket
    ):
        """Test that only pending fixes can be reviewed."""
        await ticket_service.create_fix_recommendation(
            ticket_id=sample_ticket.id,
            diff="fix",
            explanation="explanation",
        )

        # Approve it first
        await ticket_service.review_fix(
            ticket_id=sample_ticket.id,
            decision=FixRecommendationStatus.APPROVED,
            staff_id="staff_123",
        )

        # Try to review again
        with pytest.raises(ValueError, match="not in PENDING status"):
            await ticket_service.review_fix(
                ticket_id=sample_ticket.id,
                decision=FixRecommendationStatus.REJECTED,
                staff_id="staff_456",
            )

    @pytest.mark.asyncio
    async def test_apply_approved_fix(
        self, ticket_service: TicketCenterService, sample_ticket: Ticket
    ):
        """Test applying an approved fix."""
        # Create and approve fix
        await ticket_service.create_fix_recommendation(
            ticket_id=sample_ticket.id,
            diff="fix",
            explanation="explanation",
        )
        await ticket_service.review_fix(
            ticket_id=sample_ticket.id,
            decision=FixRecommendationStatus.APPROVED,
            staff_id="staff_123",
        )

        # Apply the fix
        branch_name = await ticket_service.apply_approved_fix(ticket_id=sample_ticket.id)

        assert branch_name == f"fix/ticket-{sample_ticket.id}"

    @pytest.mark.asyncio
    async def test_apply_unapproved_fix_forbidden(
        self, ticket_service: TicketCenterService, sample_ticket: Ticket
    ):
        """Test that only approved fixes can be applied."""
        await ticket_service.create_fix_recommendation(
            ticket_id=sample_ticket.id,
            diff="fix",
            explanation="explanation",
        )

        with pytest.raises(ValueError, match="not approved"):
            await ticket_service.apply_approved_fix(ticket_id=sample_ticket.id)


class TestTicketListing:
    """Test ticket listing and filtering."""

    @pytest.mark.asyncio
    async def test_list_all_tickets(self, ticket_service: TicketCenterService):
        """Test listing all tickets."""
        # Create multiple tickets
        await ticket_service.create_ticket(
            customer_id="cust_1",
            initial_message="Issue 1",
        )
        await ticket_service.create_ticket(
            customer_id="cust_2",
            initial_message="Issue 2",
        )

        tickets = await ticket_service.list_tickets()
        assert len(tickets) >= 2

    @pytest.mark.asyncio
    async def test_list_tickets_by_status(
        self, ticket_service: TicketCenterService
    ):
        """Test filtering tickets by status."""
        # Create tickets
        ticket1 = await ticket_service.create_ticket(
            customer_id="cust_1",
            initial_message="Issue 1",
        )
        ticket2 = await ticket_service.create_ticket(
            customer_id="cust_2",
            initial_message="Issue 2",
        )

        # Change one status
        await ticket_service.update_ticket_status(
            ticket_id=ticket1.id,
            new_status=TicketStatus.PENDING_STAFF,
        )

        # Filter by status
        pending_tickets = await ticket_service.list_tickets(
            status=TicketStatus.PENDING_STAFF
        )
        assert len(pending_tickets) == 1
        assert pending_tickets[0].id == ticket1.id

    @pytest.mark.asyncio
    async def test_list_tickets_by_assignment(
        self, ticket_service: TicketCenterService
    ):
        """Test filtering tickets by staff assignment."""
        ticket = await ticket_service.create_ticket(
            customer_id="cust_1",
            initial_message="Issue",
        )

        await ticket_service.assign_staff(
            ticket_id=ticket.id,
            staff_id="staff_123",
        )

        assigned_tickets = await ticket_service.list_tickets(assigned_to="staff_123")
        assert len(assigned_tickets) == 1
        assert assigned_tickets[0].assigned_staff_id == "staff_123"

    @pytest.mark.asyncio
    async def test_list_tickets_pagination(
        self, ticket_service: TicketCenterService
    ):
        """Test ticket listing with pagination."""
        # Create multiple tickets
        for i in range(5):
            await ticket_service.create_ticket(
                customer_id=f"cust_{i}",
                initial_message=f"Issue {i}",
            )

        # Test limit
        tickets = await ticket_service.list_tickets(limit=3)
        assert len(tickets) == 3

        # Test offset
        tickets = await ticket_service.list_tickets(limit=2, offset=2)
        assert len(tickets) == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
