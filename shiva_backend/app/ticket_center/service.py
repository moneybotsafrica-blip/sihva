import uuid
from datetime import datetime, timezone
from typing import Optional, List
from enum import Enum

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import (
    Ticket,
    TicketMessage,
    FixRecommendation,
    TicketStatus,
    TicketPath,
    MessageSender,
    FixRecommendationStatus,
    AIResolutionFeedback as DBAIResolutionFeedback,
)
from app.db.session import get_db_context
import structlog

logger = structlog.get_logger(__name__)


class UserRole(str, Enum):
    CUSTOMER = "customer"
    STAFF = "staff"
    DEVELOPER = "developer"


class TicketCenterService:
    """Core service for managing tickets, messages, and fix recommendations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_ticket(
        self,
        customer_id: str,
        initial_message: str,
        attachments: Optional[List[str]] = None,
        path: Optional[TicketPath] = None,
    ) -> Ticket:
        """
        Create a new ticket for a customer.
        Enforces one-open-ticket-per-customer constraint at DB level.
        """
        # Check if customer already has an open ticket
        existing_ticket = await self._get_open_ticket(customer_id)
        if existing_ticket:
            logger.warning(
                "Customer already has an open ticket",
                customer_id=customer_id,
                existing_ticket_id=existing_ticket.id,
            )
            raise ValueError(f"Customer {customer_id} already has an open ticket")

        # Determine path if not provided
        if path is None:
            path = TicketPath.SUPPORT  # Default to support path

        # Create ticket
        ticket = Ticket(
            id=str(uuid.uuid4()),
            customer_id=customer_id,
            status=TicketStatus.OPEN,
            path=path,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        self.session.add(ticket)
        await self.session.flush()

        # Add initial message
        await self.append_message(
            ticket_id=ticket.id,
            sender=MessageSender.CUSTOMER,
            content=initial_message,
            attachments=attachments,
        )

        logger.info(
            "Created new ticket",
            ticket_id=ticket.id,
            customer_id=customer_id,
            path=path,
        )

        return ticket

    async def _get_open_ticket(self, customer_id: str) -> Optional[Ticket]:
        """Get the customer's currently open ticket, if any."""
        result = await self.session.execute(
            select(Ticket).where(
                and_(
                    Ticket.customer_id == customer_id,
                    Ticket.status.notin_([TicketStatus.CLOSED, TicketStatus.RESOLVED_AUTO]),
                )
            )
        )
        return result.scalar_one_or_none()

    async def get_ticket(self, ticket_id: str) -> Optional[Ticket]:
        """Get a ticket by ID."""
        result = await self.session.execute(
            select(Ticket)
            .options(selectinload(Ticket.fix_recommendation))
            .where(Ticket.id == ticket_id)
        )
        return result.scalar_one_or_none()

    async def get_customer_ticket(self, customer_id: str) -> Optional[Ticket]:
        """Get the customer's current open ticket."""
        return await self._get_open_ticket(customer_id)

    async def append_message(
        self,
        ticket_id: str,
        sender: MessageSender,
        content: str,
        attachments: Optional[List[str]] = None,
    ) -> TicketMessage:
        """Append a message to a ticket's conversation history."""
        ticket = await self.get_ticket(ticket_id)
        if not ticket:
            raise ValueError(f"Ticket {ticket_id} not found")

        message = TicketMessage(
            id=str(uuid.uuid4()),
            ticket_id=ticket_id,
            sender=sender,
            content=content,
            attachments=attachments,
            created_at=datetime.now(timezone.utc),
        )

        self.session.add(message)

        # Update ticket's updated_at timestamp
        ticket.updated_at = datetime.now(timezone.utc)

        logger.info(
            "Appended message to ticket",
            ticket_id=ticket_id,
            sender=sender,
        )

        return message

    async def get_ticket_messages(self, ticket_id: str) -> List[TicketMessage]:
        """Get all messages for a ticket."""
        result = await self.session.execute(
            select(TicketMessage)
            .where(TicketMessage.ticket_id == ticket_id)
            .order_by(TicketMessage.created_at)
        )
        return list(result.scalars().all())

    async def update_ticket_status(
        self, ticket_id: str, new_status: TicketStatus, updated_by: Optional[str] = None
    ) -> Ticket:
        """
        Update ticket status through the state machine.
        This is the only method that should change ticket status.
        """
        ticket = await self.get_ticket(ticket_id)
        if not ticket:
            raise ValueError(f"Ticket {ticket_id} not found")

        # Validate state transition
        if not self._is_valid_status_transition(ticket.status, new_status):
            raise ValueError(
                f"Invalid status transition from {ticket.status} to {new_status}"
            )

        old_status = ticket.status
        ticket.status = new_status
        ticket.updated_at = datetime.now(timezone.utc)
        await self.session.flush()

        logger.info(
            "Updated ticket status",
            ticket_id=ticket_id,
            old_status=old_status,
            new_status=new_status,
            updated_by=updated_by,
        )

        return ticket

    def _is_valid_status_transition(
        self, current_status: TicketStatus, new_status: TicketStatus
    ) -> bool:
        """Validate ticket status transitions."""
        valid_transitions = {
            TicketStatus.OPEN: [
                TicketStatus.IN_PROGRESS,
                TicketStatus.PENDING_STAFF,
                TicketStatus.RESOLVED_AUTO,
                TicketStatus.CLOSED,  # Allow direct close for staff/developer
            ],
            TicketStatus.IN_PROGRESS: [
                TicketStatus.PENDING_STAFF,
                TicketStatus.PENDING_CUSTOMER,
                TicketStatus.RESOLVED_AUTO,
                TicketStatus.CLOSED,
            ],
            TicketStatus.PENDING_STAFF: [
                TicketStatus.IN_PROGRESS,
                TicketStatus.CLOSED,
            ],
            TicketStatus.PENDING_CUSTOMER: [
                TicketStatus.IN_PROGRESS,
                TicketStatus.RESOLVED_AUTO,
                TicketStatus.CLOSED,
            ],
            TicketStatus.RESOLVED_AUTO: [
                TicketStatus.OPEN,  # Reopen
                TicketStatus.CLOSED,
            ],
            TicketStatus.CLOSED: [
                TicketStatus.OPEN,  # Reopen closed tickets
            ],  # Allow reopening
        }
        return new_status in valid_transitions.get(current_status, [])

    async def queue_for_staff(self, ticket_id: str, reason: str, chat_summary: Optional[str] = None) -> Ticket:
        """Queue a ticket for staff review with optional chat summary."""
        ticket = await self.get_ticket(ticket_id)
        if not ticket:
            raise ValueError(f"Ticket {ticket_id} not found")

        # Store chat summary if provided
        if chat_summary:
            ticket.chat_summary = chat_summary

        await self.update_ticket_status(ticket_id, TicketStatus.PENDING_STAFF)
        await self.session.flush()
        
        logger.info(
            "Queued ticket for staff",
            ticket_id=ticket_id,
            reason=reason,
            has_summary=chat_summary is not None,
        )
        return await self.get_ticket(ticket_id)

    async def assign_staff(self, ticket_id: str, staff_id: str) -> Ticket:
        """Assign a staff member to a ticket."""
        ticket = await self.get_ticket(ticket_id)
        if not ticket:
            raise ValueError(f"Ticket {ticket_id} not found")

        ticket.assigned_staff_id = staff_id
        ticket.updated_at = datetime.now(timezone.utc)

        await self.session.flush()

        logger.info(
            "Assigned staff to ticket",
            ticket_id=ticket_id,
            staff_id=staff_id,
        )

        return ticket

    async def auto_assign_staff(self, ticket_id: str) -> Ticket:
        """
        Automatically assign a ticket to the staff member with the lowest current workload.
        This implements intelligent workload distribution for escalated tickets.
        """
        ticket = await self.get_ticket(ticket_id)
        if not ticket:
            raise ValueError(f"Ticket {ticket_id} not found")

        # Get all available staff members
        from app.db.mock_db import get_mock_staff_ids
        staff_ids = get_mock_staff_ids()

        if not staff_ids:
            logger.warning("No staff members available for auto-assignment")
            # Fall back to default staff ID
            from app.config import settings
            return await self.assign_staff(ticket_id, settings.default_escalation_staff_id)

        # Count current assigned tickets for each staff member
        staff_workload = {}
        for staff_id in staff_ids:
            result = await self.session.execute(
                select(Ticket).where(
                    and_(
                        Ticket.assigned_staff_id == staff_id,
                        Ticket.status.notin_([TicketStatus.CLOSED, TicketStatus.RESOLVED_AUTO])
                    )
                )
            )
            active_tickets = len(list(result.scalars().all()))
            staff_workload[staff_id] = active_tickets

        # Find staff member with lowest workload
        min_workload = min(staff_workload.values())
        available_staff = [staff_id for staff_id, workload in staff_workload.items() if workload == min_workload]

        # If multiple staff have same workload, pick the first one (could be enhanced with round-robin)
        selected_staff_id = available_staff[0] if available_staff else staff_ids[0]

        # Assign the ticket
        return await self.assign_staff(ticket_id, selected_staff_id)

    async def resolve_auto(self, ticket_id: str) -> Ticket:
        """Auto-resolve a ticket (typically by Support AI)."""
        await self.update_ticket_status(ticket_id, TicketStatus.RESOLVED_AUTO)
        logger.info(
            "Auto-resolved ticket",
            ticket_id=ticket_id,
        )
        return await self.get_ticket(ticket_id)

    async def close_ticket(self, ticket_id: str, closed_by: str, role: UserRole) -> Ticket:
        """
        Close a ticket. Customers can close their own tickets, staff and developers can close any ticket.
        """
        # Allow customers to close their own tickets
        if role == UserRole.CUSTOMER:
            # Additional check for ticket ownership should be done at the mutation level
            pass
        elif role not in [UserRole.STAFF, UserRole.DEVELOPER]:
            raise ValueError(f"Role {role} is not authorized to close tickets")

        await self.update_ticket_status(ticket_id, TicketStatus.CLOSED, updated_by=closed_by)
        logger.info(
            "Closed ticket",
            ticket_id=ticket_id,
            closed_by=closed_by,
            role=role,
        )
        return await self.get_ticket(ticket_id)

    async def reopen_ticket(self, ticket_id: str) -> Ticket:
        """Reopen a resolved or closed ticket."""
        ticket = await self.get_ticket(ticket_id)
        if not ticket:
            raise ValueError(f"Ticket {ticket_id} not found")

        if ticket.status not in [TicketStatus.RESOLVED_AUTO, TicketStatus.CLOSED]:
            raise ValueError(f"Cannot reopen ticket with status {ticket.status}")

        await self.update_ticket_status(ticket_id, TicketStatus.OPEN)
        logger.info(
            "Reopened ticket",
            ticket_id=ticket_id,
        )
        return ticket

    async def create_fix_recommendation(
        self,
        ticket_id: str,
        diff: str,
        explanation: str,
    ) -> FixRecommendation:
        """Create a fix recommendation for a ticket."""
        ticket = await self.get_ticket(ticket_id)
        if not ticket:
            raise ValueError(f"Ticket {ticket_id} not found")

        # Check if fix recommendation already exists
        if ticket.fix_recommendation:
            raise ValueError(f"Fix recommendation already exists for ticket {ticket_id}")

        fix_rec = FixRecommendation(
            id=str(uuid.uuid4()),
            ticket_id=ticket_id,
            diff=diff,
            explanation=explanation,
            status=FixRecommendationStatus.PENDING,
            created_at=datetime.now(timezone.utc),
        )

        self.session.add(fix_rec)
        await self.session.flush()

        # Refresh the ticket to load the new relationship
        await self.session.refresh(ticket, attribute_names=["fix_recommendation"])

        logger.info(
            "Created fix recommendation",
            ticket_id=ticket_id,
            fix_rec_id=fix_rec.id,
        )

        return fix_rec

    async def review_fix(
        self,
        ticket_id: str,
        decision: FixRecommendationStatus,
        staff_id: str,
        notes: Optional[str] = None,
    ) -> FixRecommendation:
        """
        Review a fix recommendation.
        Decision can be APPROVED, REJECTED, or NEEDS_INFO.
        """
        ticket = await self.get_ticket(ticket_id)
        if not ticket:
            raise ValueError(f"Ticket {ticket_id} not found")

        fix_rec = ticket.fix_recommendation
        if not fix_rec:
            raise ValueError(f"No fix recommendation found for ticket {ticket_id}")

        if fix_rec.status != FixRecommendationStatus.PENDING:
            raise ValueError(f"Fix recommendation is not in PENDING status")

        fix_rec.status = decision
        fix_rec.reviewed_by = staff_id
        fix_rec.reviewed_at = datetime.now(timezone.utc)
        fix_rec.notes = notes

        logger.info(
            "Reviewed fix recommendation",
            ticket_id=ticket_id,
            decision=decision,
            staff_id=staff_id,
        )

        return fix_rec

    async def list_tickets(
        self,
        status: Optional[TicketStatus] = None,
        assigned_to: Optional[str] = None,
        customer_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Ticket]:
        """List tickets with optional filters."""
        query = select(Ticket)

        conditions = []
        if status:
            conditions.append(Ticket.status == status)
        if assigned_to:
            conditions.append(Ticket.assigned_staff_id == assigned_to)
        if customer_id:
            conditions.append(Ticket.customer_id == customer_id)

        if conditions:
            query = query.where(and_(*conditions))

        query = query.options(selectinload(Ticket.fix_recommendation))
        query = query.order_by(Ticket.created_at.desc()).limit(limit).offset(offset)

        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def apply_approved_fix(self, ticket_id: str) -> str:
        """
        Apply an approved fix by creating a Git branch/PR.
        This is a separate action from review - only called after staff approval.
        Returns the branch/PR identifier.
        """
        ticket = await self.get_ticket(ticket_id)
        if not ticket:
            raise ValueError(f"Ticket {ticket_id} not found")

        fix_rec = ticket.fix_recommendation
        if not fix_rec or fix_rec.status != FixRecommendationStatus.APPROVED:
            raise ValueError(f"Fix recommendation is not approved for ticket {ticket_id}")

        # This would integrate with Git operations
        # For now, return a placeholder branch name
        branch_name = f"fix/ticket-{ticket_id}"

        logger.info(
            "Applied approved fix",
            ticket_id=ticket_id,
            branch_name=branch_name,
        )

        return branch_name

    async def add_ai_resolution_feedback(
        self,
        ticket_id: str,
        feedback: DBAIResolutionFeedback,
        comment: Optional[str] = None,
    ) -> Ticket:
        """Add AI resolution feedback to a ticket."""
        ticket = await self.get_ticket(ticket_id)
        if not ticket:
            raise ValueError(f"Ticket {ticket_id} not found")

        ticket.ai_resolution_feedback = feedback
        ticket.ai_resolution_feedback_at = datetime.now(timezone.utc)
        ticket.ai_resolution_feedback_comment = comment
        await self.session.flush()

        logger.info(
            "Added AI resolution feedback",
            ticket_id=ticket_id,
            feedback=feedback,
            comment=comment,
        )

        return ticket

    async def store_ai_confidence(self, ticket_id: str, confidence: float) -> Ticket:
        """Store AI confidence score for a ticket."""
        ticket = await self.get_ticket(ticket_id)
        if not ticket:
            raise ValueError(f"Ticket {ticket_id} not found")

        ticket.ai_resolution_confidence = confidence
        await self.session.flush()

        logger.debug(
            "Stored AI confidence",
            ticket_id=ticket_id,
            confidence=confidence,
        )

        return ticket

    async def add_staff_note(self, ticket_id: str, note: str, staff_id: str) -> Ticket:
        """Add a staff note to a ticket for internal communication."""
        ticket = await self.get_ticket(ticket_id)
        if not ticket:
            raise ValueError(f"Ticket {ticket_id} not found")

        # Initialize staff_notes if None
        if ticket.staff_notes is None:
            ticket.staff_notes = []

        # Add note with timestamp and staff info
        from datetime import datetime, timezone
        timestamped_note = f"[{datetime.now(timezone.utc).isoformat()}] {staff_id}: {note}"
        ticket.staff_notes.append(timestamped_note)
        ticket.updated_at = datetime.now(timezone.utc)
        await self.session.flush()

        logger.info(
            "Added staff note",
            ticket_id=ticket_id,
            staff_id=staff_id,
            note_length=len(note),
        )

        return ticket

    async def list_ai_resolved_tickets(
        self,
        feedback: Optional[DBAIResolutionFeedback] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Ticket]:
        """List AI-resolved tickets with optional feedback filter."""
        query = select(Ticket).where(Ticket.status == TicketStatus.RESOLVED_AUTO)

        if feedback:
            query = query.where(Ticket.ai_resolution_feedback == feedback)

        query = query.options(selectinload(Ticket.fix_recommendation))
        query = query.order_by(Ticket.created_at.desc()).limit(limit).offset(offset)

        result = await self.session.execute(query)
        return list(result.scalars().all())


# Convenience function for creating service instances
async def get_ticket_service() -> TicketCenterService:
    """Get a ticket service instance with a fresh session."""
    async with get_db_context() as session:
        return TicketCenterService(session)
