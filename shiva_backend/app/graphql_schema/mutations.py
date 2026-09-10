import strawberry
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import structlog

logger = structlog.get_logger(__name__)

from app.graphql_schema.types import (
    Ticket,
    TicketMessage,
    FixRecommendation,
    SendMessageInput,
    AssignTicketInput,
    ReplyToTicketInput,
    ReviewFixInput,
    CloseTicketInput,
    RequestHumanAgentInput,
    AIResolutionFeedbackInput,
    AIResolutionFeedback,
    ChatSession,
    ChatMessage,
    SendChatMessageInput,
    StaffAIAssistance,
    TicketContextAnalysis,
    EscalationSuggestion,
    StaffAssistanceInput,
    AnalyzeTicketContextInput,
    SuggestEscalationInput,
    AddStaffNoteInput,
)
from app.graphql_schema.queries import ticket_to_graphql, message_to_graphql, fix_to_graphql, chat_session_to_graphql, chat_message_to_graphql
from app.ticket_center.service import TicketCenterService, UserRole
from app.chat_center.service import ChatCenterService
from app.db.models import TicketMessage as DBMessage, MessageSender as DBMessageSender, AIResolutionFeedback as DBAIResolutionFeedback, Customer, ChatSessionStatus
from app.ai_router.classifier import AIRouter
from app.support_ai.service import SupportAIService
from app.code_ai.service import CodeAIService
from app.staff_ai.service import StaffAIService
from app.clients.qdrant_client import QdrantClient
from app.clients.groq_client import GroqClient
from app.clients.codex_client import CodexClient
from app.code_ai.readers import FileLogReader, GitCodeReader


@strawberry.type
class Mutation:
    @strawberry.mutation
    async def send_chat_message(
        self,
        info,
        input: SendChatMessageInput,
    ) -> ChatSession:
        """
        Customer mutation: Send a message to support chat.
        Creates/uses a chat session and only creates a ticket if escalation is needed.
        """
        context = info.context
        current_user = context.get("current_user")
        if not current_user:
            raise ValueError("Authentication required")

        if current_user.role != "customer":
            raise ValueError("This mutation is for customers only")

        customer_id = current_user.id
        session: AsyncSession = context.get("session")
        chat_service = ChatCenterService(session)

        # Handle chat session based on whether chat_session_id is provided
        if input.chat_session_id:
            # Fetch the specific session by ID
            chat_session = await chat_service.get_chat_session(input.chat_session_id)
            if not chat_session:
                raise ValueError(f"Chat session {input.chat_session_id} not found")

            # Validate it belongs to the authenticated customer
            if chat_session.customer_id != customer_id:
                raise ValueError("You can only access your own chat sessions")

            # Handle based on session status
            if chat_session.status == ChatSessionStatus.ESCALATED:
                raise ValueError(
                    "This chat session has been escalated to a ticket. "
                    "Please use the ticket reply flow to continue the conversation."
                )
            elif chat_session.status == ChatSessionStatus.RESOLVED:
                # Reopen the resolved session
                chat_session = await chat_service.reopen_chat_session(input.chat_session_id)
                logger.info(
                    "Reopened resolved chat session",
                    customer_id=customer_id,
                    chat_session_id=chat_session.id,
                )
            # If ACTIVE, use as-is
        else:
            # Fall back to current behavior: get or create active session
            chat_session = await chat_service.get_or_create_chat_session(customer_id)

        # Process the message through AI
        result = await chat_service.process_chat_message(
            chat_session_id=chat_session.id,
            customer_id=customer_id,
            message=input.content,
            attachments=input.attachment_ids,
        )

        # Refresh chat session to get updated status
        updated_chat_session = await chat_service.get_chat_session(chat_session.id)

        logger.info(
            "Chat message processed",
            customer_id=customer_id,
            chat_session_id=chat_session.id,
            action=result["action"],
            ticket_id=result.get("ticket_id"),
        )

        return chat_session_to_graphql(updated_chat_session)

    @strawberry.mutation
    async def send_message(
        self,
        info,
        input: SendMessageInput,
    ) -> Ticket:
        """
        Customer mutation: Send a message to support.
        Creates a new ticket if none exists, or appends to existing open ticket.
        Triggers AI routing.
        """
        context = info.context
        current_user = context.get("current_user")
        if not current_user:
            raise ValueError("Authentication required")

        if current_user.role != "customer":
            raise ValueError("This mutation is for customers only")

        customer_id = current_user.id
        session: AsyncSession = context.get("session")
        ticket_service = TicketCenterService(session)
        
        # Check if customer has an open ticket
        existing_ticket = await ticket_service.get_customer_ticket(customer_id)
        
        if existing_ticket:
            # Append to existing ticket
            await ticket_service.append_message(
                ticket_id=existing_ticket.id,
                sender=DBMessageSender.CUSTOMER,
                content=input.content,
                attachments=input.attachment_ids,
            )
            
            # Reopen if ticket was resolved/closed
            if existing_ticket.status in ["RESOLVED_AUTO", "CLOSED"]:
                await ticket_service.reopen_ticket(existing_ticket.id)
            
            # Trigger AI routing for the new message
            await self._route_ticket(
                existing_ticket.id,
                input.content,
                input.attachment_ids,
                ticket_service,
                context,
            )
            
            updated_ticket = await ticket_service.get_ticket(existing_ticket.id)
            return ticket_to_graphql(updated_ticket)
        else:
            # Generate AI title for the ticket
            try:
                from app.clients.groq_client import GroqClient
                groq_client = GroqClient()
                customer_data = {"customer_id": customer_id}  # Basic customer data
                ticket_title = await groq_client.generate_ticket_title(
                    message=input.content,
                    customer_data=customer_data,
                )
            except Exception as e:
                logger.error("Failed to generate ticket title", error=str(e))
                ticket_title = None

            # Create new ticket
            new_ticket = await ticket_service.create_ticket(
                customer_id=customer_id,
                initial_message=input.content,
                attachments=input.attachment_ids,
                title=ticket_title,
            )
            
            # Trigger AI routing for the new ticket
            await self._route_ticket(
                new_ticket.id,
                input.content,
                input.attachment_ids,
                ticket_service,
                context,
            )
            
            updated_ticket = await ticket_service.get_ticket(new_ticket.id)
            return ticket_to_graphql(updated_ticket)

    @strawberry.mutation
    async def request_human_agent(
        self,
        info,
        input: RequestHumanAgentInput,
    ) -> Ticket:
        """
        Customer mutation: Request to speak to a human agent.
        This is triggered when the user clicks a "Speak to Human Agent" button.
        Uses smart escalation - AI will try to help first, only escalate if complex.
        """
        context = info.context
        current_user = context.get("current_user")
        if not current_user:
            raise ValueError("Authentication required")

        if current_user.role != "customer":
            raise ValueError("This mutation is for customers only")

        customer_id = current_user.id
        session: AsyncSession = context.get("session")
        ticket_service = TicketCenterService(session)

        # Verify the ticket belongs to this customer
        ticket = await ticket_service.get_ticket(input.ticket_id)
        if not ticket:
            raise ValueError(f"Ticket {input.ticket_id} not found")

        if ticket.customer_id != customer_id:
            raise ValueError("You can only request human agent for your own tickets")

        if not input.reason or len(input.reason.strip()) < 15:
            raise ValueError(
                "Please describe what you are facing (at least 15 characters) so AI can try to resolve it first."
            )

        # Add a system message indicating the request
        await ticket_service.append_message(
            ticket_id=input.ticket_id,
            sender=DBMessageSender.SYSTEM,
            content=f"Customer requested to speak to a human agent via button. Reason: {input.reason or 'Not specified'}",
        )

        # Initialize Support AI with smart escalation
        from app.clients.gemini_client import GeminiClient
        from app.config import settings
        
        complex_task_client = None
        if settings.gemini_api_key:
            try:
                complex_task_client = GeminiClient()
            except Exception as e:
                logger.warning("Failed to initialize Gemini client, using Groq only", error=str(e))
        
        support_ai = SupportAIService(
            qdrant_client=QdrantClient(),
            groq_client=GroqClient(),
            complex_task_client=complex_task_client,
        )

        # Process with smart escalation (is_agent_request=True)
        success = await support_ai.process_and_respond(
            ticket_id=input.ticket_id,
            customer_id=customer_id,
            message=input.reason,
            ticket_service=ticket_service,
            is_agent_request=True,
        )

        logger.info(
            "Customer requested human agent via button with smart escalation",
            ticket_id=input.ticket_id,
            customer_id=customer_id,
            reason=input.reason,
            ai_handled=success,
        )

        # Return updated ticket
        updated_ticket = await ticket_service.get_ticket(input.ticket_id)
        return ticket_to_graphql(updated_ticket)

    @strawberry.mutation
    async def provide_ai_resolution_feedback(
        self,
        info,
        input: AIResolutionFeedbackInput,
    ) -> Ticket:
        """
        Customer mutation: Provide feedback on AI-resolved tickets.
        Allows users to indicate whether the AI resolution was helpful.
        """
        context = info.context
        current_user = context.get("current_user")
        if not current_user:
            raise ValueError("Authentication required")

        if current_user.role != "customer":
            raise ValueError("This mutation is for customers only")

        customer_id = current_user.id
        session: AsyncSession = context.get("session")
        ticket_service = TicketCenterService(session)

        # Verify the ticket belongs to this customer
        ticket = await ticket_service.get_ticket(input.ticket_id)
        if not ticket:
            raise ValueError(f"Ticket {input.ticket_id} not found")

        if ticket.customer_id != customer_id:
            raise ValueError("You can only provide feedback for your own tickets")

        # Verify the ticket was AI-resolved
        if ticket.status != "RESOLVED_AUTO":
            raise ValueError("Feedback can only be provided for AI-resolved tickets")

        # Map GraphQL enum to database enum
        feedback_mapping = {
            AIResolutionFeedback.HELPFUL: DBAIResolutionFeedback.HELPFUL,
            AIResolutionFeedback.NOT_HELPFUL: DBAIResolutionFeedback.NOT_HELPFUL,
            AIResolutionFeedback.PARTIALLY_HELPFUL: DBAIResolutionFeedback.PARTIALLY_HELPFUL,
            AIResolutionFeedback.NEEDS_HUMAN: DBAIResolutionFeedback.NEEDS_HUMAN,
        }

        db_feedback = feedback_mapping.get(input.feedback)
        if not db_feedback:
            raise ValueError(f"Invalid feedback value: {input.feedback}")

        # Update ticket with feedback
        await ticket_service.add_ai_resolution_feedback(
            ticket_id=input.ticket_id,
            feedback=db_feedback,
            comment=input.comment,
        )

        # If feedback indicates AI was not helpful, reopen and queue for staff
        if input.feedback in [AIResolutionFeedback.NOT_HELPFUL, AIResolutionFeedback.NEEDS_HUMAN]:
            await ticket_service.reopen_ticket(input.ticket_id)
            reason = f"User feedback: {input.feedback.value}. Comment: {input.comment or 'No comment provided'}"

            # Generate chat summary for staff
            conversation_history = await ticket_service.get_ticket_messages(input.ticket_id)
            
            from app.clients.gemini_client import GeminiClient
            from app.config import settings
            
            complex_task_client = None
            if settings.gemini_api_key:
                try:
                    complex_task_client = GeminiClient()
                except Exception as e:
                    logger.warning("Failed to initialize Gemini client, using Groq only", error=str(e))
            
            support_ai = SupportAIService(
                qdrant_client=QdrantClient(),
                groq_client=GroqClient(),
                complex_task_client=complex_task_client,
            )
            chat_summary = await support_ai.generate_chat_summary(
                ticket_id=input.ticket_id,
                conversation_history=conversation_history,
                escalation_reason=reason,
            )

            await ticket_service.queue_for_staff(input.ticket_id, reason, chat_summary)
            await ticket_service.auto_assign_staff(input.ticket_id)

            logger.info(
                "Ticket reopened due to negative AI feedback",
                ticket_id=input.ticket_id,
                feedback=input.feedback.value,
                comment=input.comment,
            )

        logger.info(
            "AI resolution feedback provided",
            ticket_id=input.ticket_id,
            customer_id=customer_id,
            feedback=input.feedback.value,
            comment=input.comment,
        )

        # Return updated ticket
        updated_ticket = await ticket_service.get_ticket(input.ticket_id)
        return ticket_to_graphql(updated_ticket)

    def _create_support_ai(self):
        """Helper to create SupportAIService with optional Gemini client."""
        from app.clients.gemini_client import GeminiClient
        from app.config import settings
        
        complex_task_client = None
        if settings.gemini_api_key:
            try:
                complex_task_client = GeminiClient()
            except Exception as e:
                logger.warning("Failed to initialize Gemini client, using Groq only", error=str(e))
        
        return SupportAIService(
            qdrant_client=QdrantClient(),
            groq_client=GroqClient(),
            complex_task_client=complex_task_client,
        )

    async def _route_ticket(
        self,
        ticket_id: str,
        message: str,
        attachments: Optional[list],
        ticket_service: TicketCenterService,
        context,
    ):
        """Route ticket through AI Router to appropriate AI service."""
        # Initialize Support AI for chat summary generation
        support_ai = self._create_support_ai()

        try:
            # Initialize AI Router
            qdrant_client = QdrantClient() if hasattr(context, "qdrant_client") else None
            router = AIRouter(qdrant_client=qdrant_client)

            # Classify the message
            route_decision = await router.classify(message, attachments or [])

            # Check if this is an agent request
            is_agent_request = router._is_agent_request(message.lower())

            logger.info(
                "AI Router decision",
                ticket_id=ticket_id,
                route=route_decision,
                is_agent_request=is_agent_request,
            )

            # Route to appropriate AI service
            if route_decision == "code":
                await self._handle_code_ai_route(ticket_id, message, attachments, ticket_service, context, support_ai)
            elif route_decision == "support":
                await self._handle_support_ai_route(ticket_id, message, ticket_service, context, is_agent_request, support_ai)
            elif route_decision == "staff":
                # Generate chat summary for staff
                conversation_history = await ticket_service.get_ticket_messages(ticket_id)
                chat_summary = await support_ai.generate_chat_summary(
                    ticket_id=ticket_id,
                    conversation_history=conversation_history,
                    escalation_reason="Customer requested to speak to human agent",
                )
                await ticket_service.queue_for_staff(ticket_id, "Customer requested to speak to human agent", chat_summary)
                await ticket_service.auto_assign_staff(ticket_id)
            else:  # Default to support AI instead of staff
                await self._handle_support_ai_route(ticket_id, message, ticket_service, context, is_agent_request, support_ai)

        except Exception as e:
            logger.error(
                "AI routing failed, queuing for staff",
                ticket_id=ticket_id,
                error=str(e),
            )
            # Generate chat summary for staff
            conversation_history = await ticket_service.get_ticket_messages(ticket_id)
            chat_summary = await support_ai.generate_chat_summary(
                ticket_id=ticket_id,
                conversation_history=conversation_history,
                escalation_reason=f"AI routing failed: {str(e)}",
            )
            await ticket_service.queue_for_staff(ticket_id, f"AI routing failed: {str(e)}", chat_summary)
            await ticket_service.auto_assign_staff(ticket_id)

    async def _handle_support_ai_route(
        self,
        ticket_id: str,
        message: str,
        ticket_service: TicketCenterService,
        context,
        is_agent_request: bool = False,
        support_ai: Optional["SupportAIService"] = None,
    ):
        """Handle routing to Support AI."""
        # Initialize Support AI if not provided
        if support_ai is None:
            support_ai = self._create_support_ai()

        try:
            ticket = await ticket_service.get_ticket(ticket_id)
            if not ticket:
                raise ValueError(f"Ticket {ticket_id} not found")

            # Process message with agent request flag
            await support_ai.process_and_respond(
                ticket_id=ticket_id,
                customer_id=ticket.customer_id,
                message=message,
                ticket_service=ticket_service,
                is_agent_request=is_agent_request,
            )

        except Exception as e:
            logger.error(
                "Support AI processing failed",
                ticket_id=ticket_id,
                error=str(e),
            )
            # Generate chat summary for staff
            conversation_history = await ticket_service.get_ticket_messages(ticket_id)
            chat_summary = await support_ai.generate_chat_summary(
                ticket_id=ticket_id,
                conversation_history=conversation_history,
                escalation_reason=f"Support AI failed: {str(e)}",
            )
            await ticket_service.queue_for_staff(ticket_id, f"Support AI failed: {str(e)}", chat_summary)
            await ticket_service.auto_assign_staff(ticket_id)

    async def _handle_code_ai_route(
        self,
        ticket_id: str,
        message: str,
        attachments: Optional[list],
        ticket_service: TicketCenterService,
        context,
        support_ai: Optional["SupportAIService"] = None,
    ):
        """Handle routing to Code/Server AI."""
        # Initialize Support AI for chat summary generation if not provided
        if support_ai is None:
            support_ai = self._create_support_ai()

        try:
            # Initialize Code AI
            code_ai = CodeAIService(
                codex_client=CodexClient(),
                log_reader=FileLogReader(),  # Real implementation
                code_reader=GitCodeReader(),  # Real implementation
            )

            # Process technical issue
            await code_ai.handle_technical_issue(
                ticket_id=ticket_id,
                message=message,
                ticket_service=ticket_service,
                attachments=attachments,
            )

        except Exception as e:
            logger.error(
                "Code AI processing failed",
                ticket_id=ticket_id,
                error=str(e),
            )
            # Generate chat summary for staff
            conversation_history = await ticket_service.get_ticket_messages(ticket_id)
            chat_summary = await support_ai.generate_chat_summary(
                ticket_id=ticket_id,
                conversation_history=conversation_history,
                escalation_reason=f"Code AI failed: {str(e)}",
            )
            await ticket_service.queue_for_staff(ticket_id, f"Code AI failed: {str(e)}", chat_summary)
            await ticket_service.auto_assign_staff(ticket_id)

    @strawberry.mutation
    async def assign_ticket(
        self,
        info,
        input: AssignTicketInput,
    ) -> Ticket:
        """
        Staff mutation: Assign a ticket to a specific staff member.
        Requires staff or developer role.
        This overrides the auto-assignment system.
        """
        context = info.context
        current_user = context.get("current_user")
        if not current_user:
            raise ValueError("Authentication required")

        if current_user.role not in ["staff", "developer"]:
            raise ValueError("This mutation requires staff or developer role")

        session: AsyncSession = context.get("session")
        ticket_service = TicketCenterService(session)
        
        ticket = await ticket_service.assign_staff(
            ticket_id=input.ticket_id,
            staff_id=input.staff_id,
        )
        
        return ticket_to_graphql(ticket)

    @strawberry.mutation
    async def auto_assign_ticket(
        self,
        info,
        ticket_id: str,
    ) -> Ticket:
        """
        Staff mutation: Auto-assign a ticket using intelligent workload distribution.
        Requires staff or developer role.
        This re-assigns a ticket to the staff member with the lowest current workload.
        """
        context = info.context
        current_user = context.get("current_user")
        if not current_user:
            raise ValueError("Authentication required")

        if current_user.role not in ["staff", "developer"]:
            raise ValueError("This mutation requires staff or developer role")

        session: AsyncSession = context.get("session")
        ticket_service = TicketCenterService(session)
        
        ticket = await ticket_service.auto_assign_staff(ticket_id)
        
        return ticket_to_graphql(ticket)

    @strawberry.mutation
    async def reply_to_ticket(
        self,
        info,
        input: ReplyToTicketInput,
    ) -> TicketMessage:
        """
        Staff mutation: Reply to a ticket.
        Requires staff or developer role.
        """
        context = info.context
        current_user = context.get("current_user")
        if not current_user:
            raise ValueError("Authentication required")

        if current_user.role not in ["staff", "developer"]:
            raise ValueError("This mutation requires staff or developer role")

        session: AsyncSession = context.get("session")
        ticket_service = TicketCenterService(session)

        ticket = await ticket_service.get_ticket(input.ticket_id)
        if not ticket:
            raise ValueError(f"Ticket {input.ticket_id} not found")
        if (
            current_user.role == "staff"
            and ticket.assigned_staff_id != current_user.id
        ):
            raise ValueError("You can only reply to tickets assigned to you")
        
        message = await ticket_service.append_message(
            ticket_id=input.ticket_id,
            sender=DBMessageSender.STAFF,
            content=input.content,
            attachments=input.attachment_ids,
        )

        # The persisted staff message is the customer chat reply. Mirror it to
        # email so customers receive the update even when they are offline.
        from app.clients.customer_api import CustomerApiClient
        from app.notifications.email import EmailNotificationService

        try:
            # Get customer from database instead of external API
            from app.db.models import Customer
            customer_result = await session.execute(
                select(Customer).where(Customer.id == ticket.customer_id)
            )
            customer = customer_result.scalar_one_or_none()
            
            if customer:
                await EmailNotificationService().send_staff_reply(
                    customer.email, ticket.id, input.content
                )
        except Exception as exc:
            logger.error(
                "Unable to send customer reply notification",
                ticket_id=ticket.id,
                error=str(exc),
            )
        
        return message_to_graphql(message)

    @strawberry.mutation
    async def approve_fix(
        self,
        info,
        input: ReviewFixInput,
    ) -> FixRecommendation:
        """
        Staff mutation: Approve a fix recommendation.
        Requires staff or developer role.
        """
        context = info.context
        current_user = context.get("current_user")
        if not current_user:
            raise ValueError("Authentication required")

        if current_user.role not in ["staff", "developer"]:
            raise ValueError("This mutation requires staff or developer role")

        session: AsyncSession = context.get("session")
        ticket_service = TicketCenterService(session)

        from app.db.models import FixRecommendationStatus
        fix_rec = await ticket_service.review_fix(
            ticket_id=input.ticket_id,
            decision=FixRecommendationStatus.APPROVED,
            staff_id=current_user.id,
            notes=input.notes,
        )
        
        return fix_to_graphql(fix_rec)

    @strawberry.mutation
    async def reject_fix(
        self,
        info,
        input: ReviewFixInput,
    ) -> FixRecommendation:
        """
        Staff mutation: Reject a fix recommendation.
        Requires staff or developer role.
        """
        context = info.context
        current_user = context.get("current_user")
        if not current_user:
            raise ValueError("Authentication required")

        if current_user.role not in ["staff", "developer"]:
            raise ValueError("This mutation requires staff or developer role")

        session: AsyncSession = context.get("session")
        ticket_service = TicketCenterService(session)

        from app.db.models import FixRecommendationStatus
        fix_rec = await ticket_service.review_fix(
            ticket_id=input.ticket_id,
            decision=FixRecommendationStatus.REJECTED,
            staff_id=current_user.id,
            notes=input.notes,
        )
        
        return fix_to_graphql(fix_rec)

    @strawberry.mutation
    async def request_more_info(
        self,
        info,
        input: ReviewFixInput,
    ) -> FixRecommendation:
        """
        Staff mutation: Request more information for a fix recommendation.
        Requires staff or developer role.
        """
        context = info.context
        current_user = context.get("current_user")
        if not current_user:
            raise ValueError("Authentication required")

        if current_user.role not in ["staff", "developer"]:
            raise ValueError("This mutation requires staff or developer role")

        session: AsyncSession = context.get("session")
        ticket_service = TicketCenterService(session)

        from app.db.models import FixRecommendationStatus
        fix_rec = await ticket_service.review_fix(
            ticket_id=input.ticket_id,
            decision=FixRecommendationStatus.NEEDS_INFO,
            staff_id=current_user.id,
            notes=input.notes,
        )
        
        return fix_to_graphql(fix_rec)

    @strawberry.mutation
    async def close_ticket(
        self,
        info,
        input: CloseTicketInput,
    ) -> Ticket:
        """
        Close a ticket.
        Customers can close their own tickets, staff and developers can close any ticket.
        """
        context = info.context
        current_user = context.get("current_user")
        if not current_user:
            raise ValueError("Authentication required")

        session: AsyncSession = context.get("session")
        ticket_service = TicketCenterService(session)

        # Get the ticket to verify ownership if customer
        ticket = await ticket_service.get_ticket(input.ticket_id)
        if not ticket:
            raise ValueError(f"Ticket {input.ticket_id} not found")

        # Determine role based on user role
        if current_user.role == "customer":
            # Customers can only close their own tickets
            if ticket.customer_id != current_user.id:
                raise ValueError("You can only close your own tickets")
            role = UserRole.CUSTOMER
        elif current_user.role == "staff":
            if ticket.assigned_staff_id != current_user.id:
                raise ValueError("You can only close tickets assigned to you")
            messages = await ticket_service.get_ticket_messages(input.ticket_id)
            if not any(message.sender == DBMessageSender.STAFF for message in messages):
                raise ValueError("Send a customer reply before closing this ticket")
            role = UserRole.STAFF
        elif current_user.role == "developer":
            role = UserRole.DEVELOPER
        else:
            raise ValueError("Invalid user role")

        ticket = await ticket_service.close_ticket(
            ticket_id=input.ticket_id,
            closed_by=current_user.id,
            role=role,
        )
        
        return ticket_to_graphql(ticket)

    @strawberry.mutation
    async def apply_approved_fix(
        self,
        info,
        ticket_id: str,
    ) -> str:
        """
        Developer mutation: Apply an approved fix by creating a Git branch/PR.
        Requires developer role.
        """
        context = info.context
        current_user = context.get("current_user")
        if not current_user:
            raise ValueError("Authentication required")

        if current_user.role != "developer":
            raise ValueError("This mutation requires developer role")

        session: AsyncSession = context.get("session")
        ticket_service = TicketCenterService(session)
        
        branch_name = await ticket_service.apply_approved_fix(ticket_id)

        return branch_name

    @strawberry.mutation
    async def get_staff_ai_assistance(
        self,
        info,
        input: StaffAssistanceInput,
    ) -> StaffAIAssistance:
        """
        Staff mutation: Get AI assistance for crafting a response to a customer.
        Uses Groq to generate suggested responses based on conversation history and knowledge base.
        """
        context = info.context
        current_user = context.get("current_user")
        if not current_user:
            raise ValueError("Authentication required")

        if current_user.role not in ["staff", "developer"]:
            raise ValueError("This mutation requires staff or developer role")

        session: AsyncSession = context.get("session")
        ticket_service = TicketCenterService(session)

        # Initialize Staff AI service
        staff_ai = StaffAIService(
            qdrant_client=QdrantClient(),
            groq_client=GroqClient(),
        )

        # Get AI assistance
        result = await staff_ai.assist_staff_response(
            ticket_id=input.ticket_id,
            staff_query=input.staff_query,
            ticket_service=ticket_service,
        )

        logger.info(
            "Staff AI assistance provided",
            ticket_id=input.ticket_id,
            staff_id=current_user.id,
            confidence=result.get("confidence", 0.0),
        )

        return StaffAIAssistance(
            suggested_response=result.get("suggested_response"),
            confidence=result.get("confidence", 0.0),
            kb_context_used=result.get("kb_context_used", False),
            reasoning=result.get("reasoning"),
        )

    @strawberry.mutation
    async def analyze_ticket_context(
        self,
        info,
        input: AnalyzeTicketContextInput,
    ) -> TicketContextAnalysis:
        """
        Staff mutation: Analyze the overall context of a ticket.
        Provides issue summary, customer sentiment, suggested actions, and complexity score.
        """
        context = info.context
        current_user = context.get("current_user")
        if not current_user:
            raise ValueError("Authentication required")

        if current_user.role not in ["staff", "developer"]:
            raise ValueError("This mutation requires staff or developer role")

        session: AsyncSession = context.get("session")
        ticket_service = TicketCenterService(session)

        # Initialize Staff AI service
        staff_ai = StaffAIService(
            qdrant_client=QdrantClient(),
            groq_client=GroqClient(),
        )

        # Analyze ticket context
        analysis = await staff_ai.analyze_ticket_context(
            ticket_id=input.ticket_id,
            ticket_service=ticket_service,
        )

        logger.info(
            "Ticket context analysis completed",
            ticket_id=input.ticket_id,
            staff_id=current_user.id,
            complexity_score=analysis.get("complexity_score", 0.5),
        )

        return TicketContextAnalysis(
            issue_summary=analysis.get("issue_summary", "Unable to analyze"),
            customer_sentiment=analysis.get("customer_sentiment", "neutral"),
            suggested_actions=analysis.get("suggested_actions", []),
            complexity_score=analysis.get("complexity_score", 0.5),
        )

    @strawberry.mutation
    async def suggest_escalation_path(
        self,
        info,
        input: SuggestEscalationInput,
    ) -> EscalationSuggestion:
        """
        Staff mutation: Get AI suggestion for whether a ticket should be escalated.
        Provides recommendation on escalation target and reasoning.
        """
        context = info.context
        current_user = context.get("current_user")
        if not current_user:
            raise ValueError("Authentication required")

        if current_user.role not in ["staff", "developer"]:
            raise ValueError("This mutation requires staff or developer role")

        session: AsyncSession = context.get("session")
        ticket_service = TicketCenterService(session)

        # Initialize Staff AI service
        staff_ai = StaffAIService(
            qdrant_client=QdrantClient(),
            groq_client=GroqClient(),
        )

        # Get escalation suggestion
        suggestion = await staff_ai.suggest_escalation_path(
            ticket_id=input.ticket_id,
            current_issue=input.current_issue,
            ticket_service=ticket_service,
        )

        logger.info(
            "Escalation path suggestion provided",
            ticket_id=input.ticket_id,
            staff_id=current_user.id,
            should_escalate=suggestion.get("should_escalate", False),
        )

        return EscalationSuggestion(
            should_escalate=suggestion.get("should_escalate", False),
            suggested_escalation_target=suggestion.get("suggested_escalation_target"),
            reasoning=suggestion.get("reasoning", "Unable to provide suggestion"),
            confidence=suggestion.get("confidence", 0.0),
        )

    @strawberry.mutation
    async def add_staff_note(
        self,
        info,
        input: AddStaffNoteInput,
    ) -> Ticket:
        """
        Staff mutation: Add an internal note to a ticket.
        These notes are visible only to staff and developers, not to customers.
        Requires staff or developer role.
        """
        context = info.context
        current_user = context.get("current_user")
        if not current_user:
            raise ValueError("Authentication required")

        if current_user.role not in ["staff", "developer"]:
            raise ValueError("This mutation requires staff or developer role")

        session: AsyncSession = context.get("session")
        ticket_service = TicketCenterService(session)

        # Add staff note
        ticket = await ticket_service.add_staff_note(
            ticket_id=input.ticket_id,
            note=input.note,
            staff_id=current_user.id,
        )

        logger.info(
            "Staff note added",
            ticket_id=input.ticket_id,
            staff_id=current_user.id,
            note_length=len(input.note),
        )

        return ticket_to_graphql(ticket)
