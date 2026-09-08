import uuid
from datetime import datetime, timezone
from typing import Optional, List, TYPE_CHECKING
from enum import Enum

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import (
    ChatSession,
    ChatMessage,
    ChatSessionStatus,
    Ticket,
    TicketStatus,
    TicketPath,
    MessageSender,
)
from app.ticket_center.service import TicketCenterService
from app.support_ai.service import SupportAIService
from app.clients.qdrant_client import QdrantClient
from app.clients.groq_client import GroqClient
from app.clients.customer_api import CustomerApiClient
from app.config import settings
import structlog

if TYPE_CHECKING:
    from app.db.models import TicketMessage

logger = structlog.get_logger(__name__)


class ChatCenterService:
    """Service for managing chat sessions before ticket creation."""

    def __init__(self, session: AsyncSession):
        self.session = session
        from app.config import settings
        self.max_ai_attempts = settings.max_ai_attempts_before_escalation

    async def get_or_create_chat_session(self, customer_id: str) -> ChatSession:
        """Get active chat session or create new one."""
        # Check for active session
        result = await self.session.execute(
            select(ChatSession).where(
                and_(
                    ChatSession.customer_id == customer_id,
                    ChatSession.status == ChatSessionStatus.ACTIVE,
                )
            )
        )
        active_session = result.scalar_one_or_none()

        if active_session:
            logger.info(
                "Found active chat session",
                customer_id=customer_id,
                chat_session_id=active_session.id,
            )
            return active_session

        # Create new chat session
        chat_session = ChatSession(
            id=str(uuid.uuid4()),
            customer_id=customer_id,
            status=ChatSessionStatus.ACTIVE,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        self.session.add(chat_session)
        await self.session.flush()

        logger.info(
            "Created new chat session",
            customer_id=customer_id,
            chat_session_id=chat_session.id,
        )

        return chat_session

    async def add_chat_message(
        self,
        chat_session_id: str,
        sender: MessageSender,
        content: str,
        attachments: Optional[List[str]] = None,
    ) -> ChatMessage:
        """Add a message to a chat session."""
        chat_session = await self.get_chat_session(chat_session_id)
        if not chat_session:
            raise ValueError(f"Chat session {chat_session_id} not found")

        message = ChatMessage(
            id=str(uuid.uuid4()),
            chat_session_id=chat_session_id,
            sender=sender,
            content=content,
            attachments=attachments,
            created_at=datetime.now(timezone.utc),
        )

        self.session.add(message)

        # Update chat session timestamp
        chat_session.updated_at = datetime.now(timezone.utc)

        logger.info(
            "Added message to chat session",
            chat_session_id=chat_session_id,
            sender=sender,
        )

        return message

    async def get_chat_session(self, chat_session_id: str) -> Optional[ChatSession]:
        """Get a chat session by ID."""
        result = await self.session.execute(
            select(ChatSession)
            .options(selectinload(ChatSession.messages))
            .where(ChatSession.id == chat_session_id)
        )
        return result.scalar_one_or_none()

    async def get_chat_messages(self, chat_session_id: str) -> List[ChatMessage]:
        """Get all messages for a chat session."""
        result = await self.session.execute(
            select(ChatMessage)
            .where(ChatMessage.chat_session_id == chat_session_id)
            .order_by(ChatMessage.created_at)
        )
        return list(result.scalars().all())

    async def process_chat_message(
        self,
        chat_session_id: str,
        customer_id: str,
        message: str,
        attachments: Optional[List[str]] = None,
    ) -> dict:
        """
        Process a customer message through AI and decide whether to resolve or escalate.

        Implements multi-turn AI attempts before escalation to maximize AI resolution rate.

        Returns:
            Dict with keys: action, response, ticket_id (if escalated)
        """
        chat_session = await self.get_chat_session(chat_session_id)
        if not chat_session:
            raise ValueError(f"Chat session {chat_session_id} not found")

        # Add customer message
        await self.add_chat_message(
            chat_session_id=chat_session_id,
            sender=MessageSender.CUSTOMER,
            content=message,
            attachments=attachments,
        )

        # Get conversation history
        conversation_history = await self.get_chat_messages(chat_session_id)

        # Initialize Support AI
        support_ai = SupportAIService(
            qdrant_client=QdrantClient(),
            groq_client=GroqClient(),
            customer_api_client=CustomerApiClient(),
        )

        # Convert chat messages to ticket messages format for AI processing
        # We'll create a simple object structure that mimics TicketMessage
        from collections import namedtuple
        TicketMessageLike = namedtuple('TicketMessageLike', ['id', 'ticket_id', 'sender', 'content', 'attachments', 'created_at'])

        ticket_style_messages = [
            TicketMessageLike(
                id=msg.id,
                ticket_id=chat_session_id,  # Use chat session ID as temp ticket ID
                sender=msg.sender,
                content=msg.content,
                attachments=msg.attachments,
                created_at=msg.created_at,
            )
            for msg in conversation_history
        ]

        # Process through AI (without ticket creation)
        result = await support_ai.handle_customer_message(
            ticket_id=chat_session_id,  # Use chat session ID
            customer_id=customer_id,
            message=message,
            ticket_service=None,  # No ticket service yet
            is_agent_request=False,
            conversation_history=ticket_style_messages,
        )

        # Check for out-of-scope messages - don't create tickets for these
        if result["action"] == "out_of_scope":
            # Add the out-of-scope response and resolve the chat
            await self.add_chat_message(
                chat_session_id=chat_session_id,
                sender=MessageSender.SUPPORT_AI,
                content=result["response"],
            )

            # Mark chat as resolved
            chat_session.status = ChatSessionStatus.RESOLVED
            chat_session.updated_at = datetime.now(timezone.utc)

            logger.info(
                "Out-of-scope message detected in chat (Groq classification) - resolved without ticket",
                chat_session_id=chat_session_id,
                message=message,
            )

            return {
                "action": "resolved",
                "response": result["response"],
                "ticket_id": None,
                "message_type": "out_of_scope"
            }

        if result["action"] == "auto_resolve" and result["response"]:
            # AI can handle it - add response and resolve chat
            await self.add_chat_message(
                chat_session_id=chat_session_id,
                sender=MessageSender.SUPPORT_AI,
                content=result["response"],
            )

            # Mark chat as resolved
            chat_session.status = ChatSessionStatus.RESOLVED
            chat_session.updated_at = datetime.now(timezone.utc)

            logger.info(
                "Chat resolved by AI with complete solution",
                chat_session_id=chat_session_id,
                confidence=result["confidence"],
                ai_attempts=chat_session.ai_attempts,
                kb_context_used=result.get("kb_context_used", False),
            )

            return {
                "action": "resolved",
                "response": result["response"],
                "ticket_id": None,
                "confidence": result["confidence"],
                "solution_quality": "complete"
            }
        else:
            # AI couldn't resolve - check if we should try again or escalate
            chat_session.ai_attempts += 1

            is_complex = bool(result.get("complexity_analysis", {}).get("is_complex"))

            if not is_complex and chat_session.ai_attempts < self.max_ai_attempts:
                # Still have attempts left - add AI response and continue
                ai_response = result.get("response") or "I'd like to help you better. Could you provide more details about your issue? For example, what specific error are you seeing or which part of the process isn't working as expected?"
                await self.add_chat_message(
                    chat_session_id=chat_session_id,
                    sender=MessageSender.SUPPORT_AI,
                    content=ai_response,
                )

                chat_session.updated_at = datetime.now(timezone.utc)

                logger.info(
                    "AI attempt made, continuing conversation for better solution",
                    chat_session_id=chat_session_id,
                    attempt=chat_session.ai_attempts,
                    max_attempts=self.max_ai_attempts,
                    confidence=result["confidence"],
                    kb_context_count=result.get("kb_context_used", False),
                )

                return {
                    "action": "continue",
                    "response": ai_response,
                    "ticket_id": None,
                    "attempt": chat_session.ai_attempts,
                    "max_attempts": self.max_ai_attempts
                }
            else:
                # Complex issues are escalated immediately; other unresolved
                # requests escalate after the configured AI attempts.
                escalation_reason = result.get("error", "AI unable to provide complete solution after multiple attempts")
                if result.get("complexity_analysis") and result["complexity_analysis"]["is_complex"]:
                    escalation_reason = f"Complex issue detected: {', '.join(result['complexity_analysis']['reasons'])}"
                escalation_reason += f" (AI attempts: {chat_session.ai_attempts}, final confidence: {result.get('confidence', 0.0):.2f})"

                # Generate comprehensive chat summary
                chat_summary = await support_ai.generate_chat_summary(
                    ticket_id=chat_session_id,
                    conversation_history=ticket_style_messages,
                    escalation_reason=escalation_reason,
                )

                # Create ticket from chat with full context
                ticket = await self._create_ticket_from_chat(
                    chat_session=chat_session,
                    conversation_history=conversation_history,
                    chat_summary=chat_summary,
                    escalation_reason=escalation_reason,
                )

                # Store AI confidence for tracking
                ticket.ai_resolution_confidence = result.get("confidence", 0.0)

                # Mark chat as escalated
                chat_session.status = ChatSessionStatus.ESCALATED
                chat_session.ticket_id = ticket.id
                chat_session.updated_at = datetime.now(timezone.utc)

                logger.info(
                    "Chat escalated to ticket after max AI attempts",
                    chat_session_id=chat_session_id,
                    ticket_id=ticket.id,
                    reason=escalation_reason,
                    ai_attempts=chat_session.ai_attempts,
                    final_confidence=result.get("confidence", 0.0),
                )

                return {
                    "action": "escalated",
                    "response": result.get("response"),
                    "ticket_id": ticket.id,
                    "escalation_reason": escalation_reason,
                    "ai_attempts": chat_session.ai_attempts
                }

    async def _create_ticket_from_chat(
        self,
        chat_session: ChatSession,
        conversation_history: List[ChatMessage],
        chat_summary: str,
        escalation_reason: str,
    ) -> Ticket:
        """Create a ticket from an escalated chat session."""
        from app.db.models import TicketMessage
        ticket_service = TicketCenterService(self.session)

        # Get first customer message as initial message
        first_customer_message = None
        for msg in conversation_history:
            if msg.sender == MessageSender.CUSTOMER:
                first_customer_message = msg
                break

        if not first_customer_message:
            raise ValueError("No customer messages found in chat session")

        # Create ticket
        ticket = await ticket_service.create_ticket(
            customer_id=chat_session.customer_id,
            initial_message=first_customer_message.content,
            attachments=first_customer_message.attachments,
            path=TicketPath.SUPPORT,
        )

        # Store chat summary
        ticket.chat_summary = chat_summary

        # Add remaining messages to ticket
        for msg in conversation_history:
            if msg.id != first_customer_message.id:  # Skip the first one (already added)
                await ticket_service.append_message(
                    ticket_id=ticket.id,
                    sender=msg.sender,
                    content=msg.content,
                    attachments=msg.attachments,
                )

        # Queue for staff with intelligent auto-assignment
        await ticket_service.queue_for_staff(ticket.id, escalation_reason, chat_summary)
        assigned_ticket = await ticket_service.auto_assign_staff(ticket.id)

        logger.info(
            "Created ticket from chat session with auto-assignment",
            chat_session_id=chat_session.id,
            ticket_id=ticket.id,
            messages_count=len(conversation_history),
            assigned_staff_id=assigned_ticket.assigned_staff_id,
        )

        return ticket

    async def get_active_chat_session(self, customer_id: str) -> Optional[ChatSession]:
        """Get customer's active chat session if exists."""
        result = await self.session.execute(
            select(ChatSession).where(
                and_(
                    ChatSession.customer_id == customer_id,
                    ChatSession.status == ChatSessionStatus.ACTIVE,
                )
            )
        )
        return result.scalar_one_or_none()
