import strawberry
from typing import Optional, List, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy import select
from strawberry.types import Info

from app.graphql_schema.types import (
    Ticket,
    TicketStatus,
    TicketMessage,
    FixRecommendation,
    AISuggestedResolution,
    AIResolutionFeedback as GraphQLAIResolutionFeedback,
    ChatSession,
    ChatMessage,
    ChatSessionStatus as GraphQLChatSessionStatus,
    StaffInfo,
)
from app.ticket_center.service import TicketCenterService
from app.chat_center.service import ChatCenterService
from app.db.models import (
    Ticket as DBTicket,
    TicketMessage as DBMessage,
    FixRecommendation as DBFix,
    AISuggestedResolution as DBAISuggestedResolution,
    AIResolutionFeedback as DBAIResolutionFeedback,
    ChatSession as DBChatSession,
    ChatMessage as DBChatMessage,
    ChatSessionStatus as DBChatSessionStatus,
    TicketStatus as DBTicketStatus,
    Staff as DBStaff,
)


def chat_session_to_graphql(db_chat_session: DBChatSession) -> ChatSession:
    """Convert database ChatSession model to GraphQL type."""
    # Map database enum to GraphQL enum for chat session status
    status_mapping = {
        DBChatSessionStatus.ACTIVE: GraphQLChatSessionStatus.ACTIVE,
        DBChatSessionStatus.RESOLVED: GraphQLChatSessionStatus.RESOLVED,
        DBChatSessionStatus.ESCALATED: GraphQLChatSessionStatus.ESCALATED,
    }

    graphql_status = status_mapping.get(db_chat_session.status)

    return ChatSession(
        id=db_chat_session.id,
        customer_id=db_chat_session.customer_id,
        status=graphql_status,
        created_at=db_chat_session.created_at,
        updated_at=db_chat_session.updated_at,
        ticket_id=db_chat_session.ticket_id,
        ai_attempts=db_chat_session.ai_attempts,
        messages=[chat_message_to_graphql(msg) for msg in db_chat_session.messages],
    )


def chat_message_to_graphql(db_chat_message: DBChatMessage) -> ChatMessage:
    """Convert database ChatMessage model to GraphQL type."""
    attachments = db_chat_message.attachments if db_chat_message.attachments else None
    return ChatMessage(
        id=db_chat_message.id,
        chat_session_id=db_chat_message.chat_session_id,
        sender=db_chat_message.sender,
        content=db_chat_message.content,
        attachments=attachments,
        created_at=db_chat_message.created_at,
    )


def ticket_to_graphql(db_ticket: DBTicket, user_role: Optional[str] = None) -> Ticket:
    """Convert database Ticket model to GraphQL type."""
    # Map database enum to GraphQL enum for AI resolution feedback
    feedback_mapping = {
        DBAIResolutionFeedback.HELPFUL: GraphQLAIResolutionFeedback.HELPFUL,
        DBAIResolutionFeedback.NOT_HELPFUL: GraphQLAIResolutionFeedback.NOT_HELPFUL,
        DBAIResolutionFeedback.PARTIALLY_HELPFUL: GraphQLAIResolutionFeedback.PARTIALLY_HELPFUL,
        DBAIResolutionFeedback.NEEDS_HUMAN: GraphQLAIResolutionFeedback.NEEDS_HUMAN,
    }

    graphql_feedback = feedback_mapping.get(db_ticket.ai_resolution_feedback) if db_ticket.ai_resolution_feedback else None

    # Only include AI suggested resolution for staff/developer roles
    ai_resolution = None
    if user_role in ["staff", "developer"]:
        ai_resolution = ai_resolution_to_graphql(db_ticket.ai_suggested_resolution) if db_ticket.ai_suggested_resolution else None

    return Ticket(
        id=db_ticket.id,
        customer_id=db_ticket.customer_id,
        status=db_ticket.status,
        path=db_ticket.path,
        created_at=db_ticket.created_at,
        updated_at=db_ticket.updated_at,
        assigned_staff_id=db_ticket.assigned_staff_id,
        title=db_ticket.title,
        messages=[message_to_graphql(msg) for msg in db_ticket.messages],
        fix_recommendation=fix_to_graphql(db_ticket.fix_recommendation) if db_ticket.fix_recommendation else None,
        ai_suggested_resolution=ai_resolution,
        ai_resolution_feedback=graphql_feedback,
        ai_resolution_feedback_at=db_ticket.ai_resolution_feedback_at,
        ai_resolution_feedback_comment=db_ticket.ai_resolution_feedback_comment,
        ai_resolution_confidence=db_ticket.ai_resolution_confidence,
        chat_summary=db_ticket.chat_summary,
        staff_notes=db_ticket.staff_notes,
    )


def message_to_graphql(db_message: DBMessage) -> TicketMessage:
    """Convert database TicketMessage model to GraphQL type."""
    attachments = db_message.attachments if db_message.attachments else None
    return TicketMessage(
        id=db_message.id,
        ticket_id=db_message.ticket_id,
        sender=db_message.sender,
        content=db_message.content,
        attachments=attachments,
        created_at=db_message.created_at,
    )


def fix_to_graphql(db_fix: DBFix) -> FixRecommendation:
    """Convert database FixRecommendation model to GraphQL type."""
    return FixRecommendation(
        id=db_fix.id,
        ticket_id=db_fix.ticket_id,
        diff=db_fix.diff,
        explanation=db_fix.explanation,
        status=db_fix.status,
        reviewed_by=db_fix.reviewed_by,
        reviewed_at=db_fix.reviewed_at,
        notes=db_fix.notes,
        created_at=db_fix.created_at,
    )


def ai_resolution_to_graphql(db_ai_resolution: DBAISuggestedResolution) -> AISuggestedResolution:
    """Convert database AISuggestedResolution model to GraphQL type."""
    from app.graphql_schema.types import AISuggestedResolution as GraphQLAISuggestedResolution
    return GraphQLAISuggestedResolution(
        id=db_ai_resolution.id,
        ticket_id=db_ai_resolution.ticket_id,
        suggested_solution=db_ai_resolution.suggested_solution,
        confidence=db_ai_resolution.confidence,
        escalation_reason=db_ai_resolution.escalation_reason,
        kb_article_ids=db_ai_resolution.kb_article_ids,
        kb_similarity_score=db_ai_resolution.kb_similarity_score,
        agent_type=db_ai_resolution.agent_type,
        status=db_ai_resolution.status,
        reviewed_by=db_ai_resolution.reviewed_by,
        reviewed_at=db_ai_resolution.reviewed_at,
        notes=db_ai_resolution.notes,
        created_at=db_ai_resolution.created_at,
    )


@strawberry.type
class Query:
    @strawberry.field
    async def my_chat_session(self, info: Info) -> Optional[ChatSession]:
        """
        Customer query: Get the customer's current active chat session.
        Requires authentication context.
        """
        context = info.context
        current_user = context.get("current_user")
        if not current_user:
            raise ValueError("Authentication required")

        if current_user.role != "customer":
            raise ValueError("This query is for customers only")

        customer_id = current_user.id
        session: AsyncSession = context.get("session")

        chat_service = ChatCenterService(session)
        db_chat_session = await chat_service.get_active_chat_session(customer_id)

        if db_chat_session:
            return chat_session_to_graphql(db_chat_session)
        return None

    @strawberry.field
    async def my_chat_history(self, info: Info, limit: int = 20) -> List[ChatSession]:
        """Return the customer's stored chat sessions and their messages."""
        context = info.context
        current_user = context.get("current_user")
        if not current_user:
            raise ValueError("Authentication required")
        if current_user.role != "customer":
            raise ValueError("This query is for customers only")

        result = await context.get("session").execute(
            select(DBChatSession)
            .options(selectinload(DBChatSession.messages))
            .where(DBChatSession.customer_id == current_user.id)
            .order_by(DBChatSession.updated_at.desc())
            .limit(limit)
        )
        return [chat_session_to_graphql(session) for session in result.scalars().all()]

    @strawberry.field
    async def my_ticket(self, info: Info) -> Optional[Ticket]:
        """
        Customer query: Get the customer's current open ticket.
        Requires authentication context.
        """
        context = info.context
        current_user = context.get("current_user")
        if not current_user:
            raise ValueError("Authentication required")

        if current_user.role != "customer":
            raise ValueError("This query is for customers only")

        customer_id = current_user.id
        session: AsyncSession = context.get("session")

        ticket_service = TicketCenterService(session)
        db_ticket = await ticket_service.get_customer_ticket(customer_id)

        if db_ticket:
            return ticket_to_graphql(db_ticket, user_role="customer")
        return None

    @strawberry.field
    async def my_support_history(
        self,
        info: Info,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Ticket]:
        """
        Customer query: Get the customer's support history (all past tickets).
        Requires authentication context.
        """
        context = info.context
        current_user = context.get("current_user")
        if not current_user:
            raise ValueError("Authentication required")

        if current_user.role != "customer":
            raise ValueError("This query is for customers only")

        customer_id = current_user.id
        session: AsyncSession = context.get("session")
        ticket_service = TicketCenterService(session)

        db_tickets = await ticket_service.list_tickets(
            customer_id=customer_id,
            limit=limit,
            offset=offset,
        )

        return [ticket_to_graphql(ticket, user_role="customer") for ticket in db_tickets]

    @strawberry.field
    async def tickets(
        self,
        info: Info,
        status: Optional[TicketStatus] = None,
        assigned_to: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Ticket]:
        """
        Staff query: List tickets with optional filters.
        Requires staff or developer role.
        Staff can see all tickets by default, with optional filtering by assignment.
        """
        context = info.context
        current_user = context.get("current_user")
        if not current_user:
            raise ValueError("Authentication required")

        if current_user.role not in ["staff", "developer"]:
            raise ValueError("This query requires staff or developer role")

        session: AsyncSession = context.get("session")
        ticket_service = TicketCenterService(session)

        # Don't default to user's own tickets - let staff see all tickets
        # Only filter by assigned_to if explicitly provided
        db_tickets = await ticket_service.list_tickets(
            status=status,
            assigned_to=assigned_to,
            limit=limit,
            offset=offset,
        )

        return [ticket_to_graphql(ticket, user_role="customer") for ticket in db_tickets]

    @strawberry.field
    async def ticket(self, info: Info, id: str) -> Optional[Ticket]:
        """
        Staff query: Get a specific ticket by ID.
        Requires staff or developer role.
        """
        context = info.context
        current_user = context.get("current_user")
        if not current_user:
            raise ValueError("Authentication required")

        if current_user.role not in ["staff", "developer"]:
            raise ValueError("This query requires staff or developer role")

        session: AsyncSession = context.get("session")
        ticket_service = TicketCenterService(session)

        # Get ticket with eager loading
        result = await session.execute(
            select(DBTicket)
            .options(selectinload(DBTicket.fix_recommendation))
            .options(selectinload(DBTicket.ai_suggested_resolution))
            .where(DBTicket.id == id)
        )
        db_ticket = result.scalar_one_or_none()

        if db_ticket:
            return ticket_to_graphql(db_ticket, user_role=current_user.role)
        return None

    @strawberry.field
    async def ai_resolved_tickets(
        self,
        info: Info,
        feedback: Optional[GraphQLAIResolutionFeedback] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Ticket]:
        """
        Staff query: Get AI-resolved tickets with optional feedback filter.
        Requires staff or developer role.
        """
        context = info.context
        current_user = context.get("current_user")
        if not current_user:
            raise ValueError("Authentication required")

        if current_user.role not in ["staff", "developer"]:
            raise ValueError("This query requires staff or developer role")

        session: AsyncSession = context.get("session")
        ticket_service = TicketCenterService(session)

        # Map GraphQL enum to database enum
        feedback_mapping = {
            GraphQLAIResolutionFeedback.HELPFUL: DBAIResolutionFeedback.HELPFUL,
            GraphQLAIResolutionFeedback.NOT_HELPFUL: DBAIResolutionFeedback.NOT_HELPFUL,
            GraphQLAIResolutionFeedback.PARTIALLY_HELPFUL: DBAIResolutionFeedback.PARTIALLY_HELPFUL,
            GraphQLAIResolutionFeedback.NEEDS_HUMAN: DBAIResolutionFeedback.NEEDS_HUMAN,
        }

        db_feedback = feedback_mapping.get(feedback) if feedback else None

        # Get AI-resolved tickets with optional feedback filter
        db_tickets = await ticket_service.list_ai_resolved_tickets(
            feedback=db_feedback,
            limit=limit,
            offset=offset,
        )

        return [ticket_to_graphql(ticket, user_role="staff") for ticket in db_tickets]

    @strawberry.field
    async def staff_dashboard_tickets(
        self,
        info: Info,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Ticket]:
        """
        Staff query: Get all tickets for staff dashboard.
        Staff can see all tickets with their assignment information.
        Requires staff or developer role.
        """
        context = info.context
        current_user = context.get("current_user")
        if not current_user:
            raise ValueError("Authentication required")

        if current_user.role not in ["staff", "developer"]:
            raise ValueError("This query requires staff or developer role")

        session: AsyncSession = context.get("session")

        # Get all tickets for staff to see
        from app.db.models import DBTicket

        query = select(DBTicket).options(selectinload(DBTicket.fix_recommendation))
        query = query.options(selectinload(DBTicket.ai_suggested_resolution))
        query = query.order_by(DBTicket.created_at.desc()).limit(limit).offset(offset)

        result = await session.execute(query)
        db_tickets = list(result.scalars().all())

        return [ticket_to_graphql(ticket, user_role=current_user.role) for ticket in db_tickets]

    @strawberry.field
    async def unassigned_tickets(
        self,
        info: Info,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Ticket]:
        """
        Staff query: Get tickets that are not assigned to any staff member.
        This helps staff identify tickets that need assignment.
        Requires staff or developer role.
        """
        context = info.context
        current_user = context.get("current_user")
        if not current_user:
            raise ValueError("Authentication required")

        if current_user.role not in ["staff", "developer"]:
            raise ValueError("This query requires staff or developer role")

        session: AsyncSession = context.get("session")

        # Get unassigned tickets
        from app.db.models import DBTicket
        from sqlalchemy import or_

        query = select(DBTicket).options(selectinload(DBTicket.fix_recommendation))
        query = query.options(selectinload(DBTicket.ai_suggested_resolution))
        query = query.where(
            or_(
                DBTicket.assigned_staff_id.is_(None),
                DBTicket.assigned_staff_id == ""
            )
        )
        query = query.order_by(DBTicket.created_at.desc()).limit(limit).offset(offset)

        result = await session.execute(query)
        db_tickets = list(result.scalars().all())

        return [ticket_to_graphql(ticket, user_role=current_user.role) for ticket in db_tickets]

    @strawberry.field
    async def staff_members(
        self,
        info: Info,
    ) -> List["StaffInfo"]:
        """
        Staff query: Get all staff members information.
        This helps staff identify who they can assign tickets to.
        Requires staff or developer role.
        """
        context = info.context
        current_user = context.get("current_user")
        if not current_user:
            raise ValueError("Authentication required")

        if current_user.role not in ["staff", "developer"]:
            raise ValueError("This query requires staff or developer role")

        session: AsyncSession = context.get("session")

        # Get all active staff members from database
        result = await session.execute(
            select(DBStaff).where(DBStaff.is_active == True)
        )
        staff_members_db = list(result.scalars().all())

        return [
            StaffInfo(
                staff_id=staff.id,
                name=staff.name,
                role=staff.role
            )
            for staff in staff_members_db
        ]

    @strawberry.field
    async def ticket_queue(
        self,
        info: Info,
        status: Optional[TicketStatus] = None,
        assigned_to: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Ticket]:
        """
        Staff query: Get comprehensive ticket queue showing all staff-assigned tickets.
        This includes:
        - All tickets assigned to any staff member
        - Tickets pending staff assignment
        - Optional filtering by status or specific staff assignment
        Requires staff or developer role.
        """
        context = info.context
        current_user = context.get("current_user")
        if not current_user:
            raise ValueError("Authentication required")

        if current_user.role not in ["staff", "developer"]:
            raise ValueError("This query requires staff or developer role")

        session: AsyncSession = context.get("session")

        # Get all tickets that are either assigned to staff or pending staff assignment
        from sqlalchemy import or_, and_

        query = select(DBTicket).options(selectinload(DBTicket.fix_recommendation))
        query = query.options(selectinload(DBTicket.ai_suggested_resolution))

        # Build conditions for staff-relevant tickets
        # Include all tickets that are either:
        # 1. Assigned to staff (not null and not empty)
        # 2. Or pending staff assignment
        assigned_condition = and_(
            DBTicket.assigned_staff_id.isnot(None),
            DBTicket.assigned_staff_id != ""
        )
        pending_condition = DBTicket.status == DBTicketStatus.PENDING_STAFF
        
        # Apply the OR condition for staff-relevant tickets
        query = query.where(or_(assigned_condition, pending_condition))
        
        # Apply optional filters
        if status:
            query = query.where(DBTicket.status == status)
        
        if assigned_to:
            query = query.where(DBTicket.assigned_staff_id == assigned_to)

        query = query.order_by(DBTicket.created_at.desc()).limit(limit).offset(offset)

        result = await session.execute(query)
        db_tickets = list(result.scalars().all())

        return [ticket_to_graphql(ticket, user_role=current_user.role) for ticket in db_tickets]

    @strawberry.field
    async def customer_support_history(
        self,
        info: Info,
        customer_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Ticket]:
        """
        Staff query: Get support history for a specific customer.
        Requires staff or developer role.
        """
        context = info.context
        current_user = context.get("current_user")
        if not current_user:
            raise ValueError("Authentication required")

        if current_user.role not in ["staff", "developer"]:
            raise ValueError("This query requires staff or developer role")

        session: AsyncSession = context.get("session")
        ticket_service = TicketCenterService(session)

        db_tickets = await ticket_service.list_tickets(
            customer_id=customer_id,
            limit=limit,
            offset=offset,
        )

        return [ticket_to_graphql(ticket, user_role=current_user.role) for ticket in db_tickets]
