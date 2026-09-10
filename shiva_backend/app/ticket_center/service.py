import uuid
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from enum import Enum

from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import (
    Ticket,
    TicketMessage,
    FixRecommendation,
    AISuggestedResolution,
    AISuggestedResolutionStatus,
    TicketStatus,
    TicketPath,
    MessageSender,
    FixRecommendationStatus,
    AIResolutionFeedback as DBAIResolutionFeedback,
    Staff as DBStaff,
)
from app.db.session import get_db_context
from app.config import settings
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
        title: Optional[str] = None,
    ) -> Ticket:
        """
        Create a new ticket for a customer.
        Enforces one-open-ticket-per-customer constraint at DB level.

        Args:
            title: Optional AI-generated title. If not provided, will be generated later.
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
            title=title,
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
            .options(selectinload(Ticket.ai_suggested_resolution))
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

        # Get all active staff members from database
        result = await self.session.execute(
            select(DBStaff).where(DBStaff.is_active == True)
        )
        staff_members = list(result.scalars().all())

        if not staff_members:
            logger.warning("No staff members available for auto-assignment")
            # Fall back to default staff ID
            from app.config import settings
            return await self.assign_staff(ticket_id, settings.default_escalation_staff_id)

        # Count current assigned tickets for each staff member
        staff_workload = {}
        for staff in staff_members:
            result = await self.session.execute(
                select(Ticket).where(
                    and_(
                        Ticket.assigned_staff_id == staff.id,
                        Ticket.status.notin_([TicketStatus.CLOSED, TicketStatus.RESOLVED_AUTO])
                    )
                )
            )
            active_tickets = len(list(result.scalars().all()))
            staff_workload[staff.id] = active_tickets

        # Find staff member with lowest workload
        min_workload = min(staff_workload.values())
        available_staff = [staff_id for staff_id, workload in staff_workload.items() if workload == min_workload]

        # If multiple staff have same workload, pick the first one (could be enhanced with round-robin)
        selected_staff_id = available_staff[0] if available_staff else staff_members[0].id

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
        Close a ticket. 
        - Customers can close their own tickets only while RESOLVED_AUTO (confirming AI fix worked)
        - Staff and developers can close any ticket
        """
        ticket = await self.get_ticket(ticket_id)
        if not ticket:
            raise ValueError(f"Ticket {ticket_id} not found")
        
        # Allow customers to close their own tickets only if RESOLVED_AUTO
        if role == UserRole.CUSTOMER:
            if ticket.status != TicketStatus.RESOLVED_AUTO:
                raise ValueError("Customers can only close tickets that are RESOLVED_AUTO")
            # Additional check for ticket ownership should be done at the mutation level
        elif role not in [UserRole.STAFF, UserRole.DEVELOPER]:
            raise ValueError(f"Role {role} is not authorized to close tickets")

        await self.update_ticket_status(ticket_id, TicketStatus.CLOSED, updated_by=closed_by)
        logger.info(
            "Closed ticket",
            ticket_id=ticket_id,
            closed_by=closed_by,
            role=role,
            previous_status=ticket.status,
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

    async def increment_ai_attempts(self, ticket_id: str) -> Ticket:
        """Increment the AI attempts counter on a ticket."""
        ticket = await self.get_ticket(ticket_id)
        if not ticket:
            raise ValueError(f"Ticket {ticket_id} not found")
        
        ticket.ai_attempts += 1
        await self.session.flush()
        
        logger.info(
            "Incremented AI attempts on ticket",
            ticket_id=ticket_id,
            ai_attempts=ticket.ai_attempts,
        )
        return ticket

    async def check_ai_attempts_cap(self, ticket_id: str) -> bool:
        """
        Check if the ticket has reached the AI attempts cap.
        Returns True if cap is reached (should escalate), False otherwise.
        """
        ticket = await self.get_ticket(ticket_id)
        if not ticket:
            raise ValueError(f"Ticket {ticket_id} not found")
        
        cap_reached = ticket.ai_attempts >= settings.max_ai_attempts_before_escalation
        
        if cap_reached:
            logger.info(
                "AI attempts cap reached for ticket",
                ticket_id=ticket_id,
                ai_attempts=ticket.ai_attempts,
                max_attempts=settings.max_ai_attempts_before_escalation,
            )
        
        return cap_reached

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

    async def create_ai_suggested_resolution(
        self,
        ticket_id: str,
        suggested_solution: str,
        confidence: float,
        escalation_reason: str,
        kb_article_ids: Optional[List[str]] = None,
        kb_similarity_score: Optional[float] = None,
        agent_type: Optional[str] = None,
    ) -> AISuggestedResolution:
        """Create an AI suggested resolution for a ticket (staff-only)."""
        ticket = await self.get_ticket(ticket_id)
        if not ticket:
            raise ValueError(f"Ticket {ticket_id} not found")

        # Check if AI suggested resolution already exists
        if ticket.ai_suggested_resolution:
            raise ValueError(f"AI suggested resolution already exists for ticket {ticket_id}")

        ai_resolution = AISuggestedResolution(
            id=str(uuid.uuid4()),
            ticket_id=ticket_id,
            suggested_solution=suggested_solution,
            confidence=confidence,
            escalation_reason=escalation_reason,
            kb_article_ids=kb_article_ids,
            kb_similarity_score=kb_similarity_score,
            agent_type=agent_type,
            status=AISuggestedResolutionStatus.PENDING,
            created_at=datetime.now(timezone.utc),
        )

        self.session.add(ai_resolution)
        await self.session.flush()

        # Refresh the ticket to load the new relationship
        await self.session.refresh(ticket, attribute_names=["ai_suggested_resolution"])

        logger.info(
            "Created AI suggested resolution",
            ticket_id=ticket_id,
            ai_resolution_id=ai_resolution.id,
            confidence=confidence,
            escalation_reason=escalation_reason,
        )
        return ai_resolution

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
        query = query.options(selectinload(Ticket.ai_suggested_resolution))
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

    async def store_ai_resolution_metadata(
        self,
        ticket_id: str,
        agent_type: Optional[str] = None,
        kb_article_ids: Optional[List[str]] = None,
        kb_similarity_score: Optional[float] = None,
    ) -> Ticket:
        """Store AI resolution metadata for analytics."""
        ticket = await self.get_ticket(ticket_id)
        if not ticket:
            raise ValueError(f"Ticket {ticket_id} not found")

        ticket.ai_agent_type = agent_type
        ticket.ai_kb_article_ids = kb_article_ids
        ticket.ai_kb_similarity_score = kb_similarity_score
        await self.session.flush()

        logger.debug(
            "Stored AI resolution metadata",
            ticket_id=ticket_id,
            agent_type=agent_type,
            kb_article_count=len(kb_article_ids) if kb_article_ids else 0,
            kb_similarity_score=kb_similarity_score,
        )

        return ticket

    async def get_ai_resolution_analytics(
        self,
        days: int = 30,
    ) -> Dict[str, Any]:
        """Get AI resolution analytics for quality improvement."""
        from datetime import timedelta

        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)

        # Get all AI-resolved tickets in the period
        query = select(Ticket).where(
            Ticket.status == TicketStatus.RESOLVED_AUTO,
            Ticket.created_at >= cutoff_date
        )
        result = await self.session.execute(query)
        tickets = list(result.scalars().all())

        if not tickets:
            return {
                "total_ai_resolutions": 0,
                "feedback_breakdown": {},
                "not_helpful_rate": 0.0,
                "agent_type_breakdown": {},
                "agent_type_not_helpful_rates": {},
                "kb_article_not_helpful_rates": {},
            }

        total_resolutions = len(tickets)
        
        # Feedback breakdown
        feedback_counts = {}
        for ticket in tickets:
            feedback = ticket.ai_resolution_feedback.value if ticket.ai_resolution_feedback else "no_feedback"
            feedback_counts[feedback] = feedback_counts.get(feedback, 0) + 1

        not_helpful_count = feedback_counts.get("not_helpful", 0) + feedback_counts.get("needs_human", 0)
        not_helpful_rate = not_helpful_count / total_resolutions if total_resolutions > 0 else 0.0

        # Agent type breakdown
        agent_type_counts = {}
        agent_type_not_helpful = {}
        for ticket in tickets:
            agent = ticket.ai_agent_type or "unknown"
            agent_type_counts[agent] = agent_type_counts.get(agent, 0) + 1
            if ticket.ai_resolution_feedback in [DBAIResolutionFeedback.NOT_HELPFUL, DBAIResolutionFeedback.NEEDS_HUMAN]:
                agent_type_not_helpful[agent] = agent_type_not_helpful.get(agent, 0) + 1

        # Calculate not-helpful rate by agent type
        agent_type_not_helpful_rates = {}
        for agent, count in agent_type_counts.items():
            not_helpful = agent_type_not_helpful.get(agent, 0)
            agent_type_not_helpful_rates[agent] = not_helpful / count if count > 0 else 0.0

        # KB article not-helpful rates
        kb_article_not_helpful_rates = {}
        kb_article_usage = {}
        kb_article_not_helpful = {}
        for ticket in tickets:
            if ticket.ai_kb_article_ids:
                for article_id in ticket.ai_kb_article_ids:
                    kb_article_usage[article_id] = kb_article_usage.get(article_id, 0) + 1
                    if ticket.ai_resolution_feedback in [DBAIResolutionFeedback.NOT_HELPFUL, DBAIResolutionFeedback.NEEDS_HUMAN]:
                        kb_article_not_helpful[article_id] = kb_article_not_helpful.get(article_id, 0) + 1

        for article_id, usage_count in kb_article_usage.items():
            not_helpful_count = kb_article_not_helpful.get(article_id, 0)
            kb_article_not_helpful_rates[article_id] = not_helpful_count / usage_count if usage_count > 0 else 0.0

        return {
            "total_ai_resolutions": total_resolutions,
            "feedback_breakdown": feedback_counts,
            "not_helpful_rate": not_helpful_rate,
            "agent_type_breakdown": agent_type_counts,
            "agent_type_not_helpful_rates": agent_type_not_helpful_rates,
            "kb_article_not_helpful_rates": kb_article_not_helpful_rates,
        }


# Convenience function for creating service instances
async def get_ticket_service() -> TicketCenterService:
    """Get a ticket service instance with a fresh session."""
    async with get_db_context() as session:
        return TicketCenterService(session)
