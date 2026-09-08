"""
Mock Database for Testing

This module provides realistic test data and seed functions for the Shiva AI Support Platform.
It can be used in both pytest fixtures and the GUI for testing purposes.
"""

import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional, List, TYPE_CHECKING
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete

if TYPE_CHECKING:
    from app.db.models import ChatMessage

from app.db.models import (
    Ticket,
    TicketMessage,
    FixRecommendation,
    TicketStatus,
    TicketPath,
    MessageSender,
    FixRecommendationStatus,
    AIResolutionFeedback,
    ChatSession,
    ChatMessage,
    ChatSessionStatus,
)


class MockDatabase:
    """Mock database with realistic test data for testing purposes."""

    # Mock Customer Data
    CUSTOMERS = {
        "cust_001": {
            "name": "Alice Johnson",
            "email": "alice@example.com",
            "company": "TechCorp Inc."
        },
        "cust_002": {
            "name": "Bob Smith", 
            "email": "bob@example.com",
            "company": "StartupXYZ"
        },
        "cust_003": {
            "name": "Carol Williams",
            "email": "carol@example.com",
            "company": "Enterprise Solutions"
        },
        "cust_004": {
            "name": "David Brown",
            "email": "david@example.com",
            "company": "Digital Agency"
        },
        "cust_005": {
            "name": "Eva Martinez",
            "email": "eva@example.com",
            "company": "Cloud Services LLC"
        }
    }

    # Mock Staff Data
    STAFF = {
        "staff_001": {
            "name": "John Support",
            "email": "john.support@shiva.com",
            "role": "support_agent"
        },
        "staff_002": {
            "name": "Sarah Engineer",
            "email": "sarah.engineer@shiva.com",
            "role": "developer"
        },
        "staff_003": {
            "name": "Mike Lead",
            "email": "mike.lead@shiva.com",
            "role": "team_lead"
        }
    }

    @staticmethod
    def generate_ticket_id() -> str:
        """Generate a realistic ticket ID."""
        return f"ticket_{uuid.uuid4().hex[:12]}"

    @staticmethod
    def generate_message_id() -> str:
        """Generate a realistic message ID."""
        return f"msg_{uuid.uuid4().hex[:12]}"

    @staticmethod
    def generate_fix_id() -> str:
        """Generate a realistic fix recommendation ID."""
        return f"fix_{uuid.uuid4().hex[:12]}"

    @classmethod
    def create_support_ticket(
        cls,
        customer_id: str = "cust_001",
        status: TicketStatus = TicketStatus.OPEN,
        path: TicketPath = TicketPath.SUPPORT,
        created_days_ago: int = 0,
        assigned_staff_id: Optional[str] = None
    ) -> Ticket:
        """Create a mock support ticket."""
        created_at = datetime.now(timezone.utc) - timedelta(days=created_days_ago)
        
        ticket = Ticket(
            id=cls.generate_ticket_id(),
            customer_id=customer_id,
            status=status,
            path=path,
            created_at=created_at,
            updated_at=created_at,
            assigned_staff_id=assigned_staff_id
        )
        return ticket

    @classmethod
    def create_bug_ticket(
        cls,
        customer_id: str = "cust_002",
        status: TicketStatus = TicketStatus.PENDING_STAFF,
        path: TicketPath = TicketPath.BUG,
        created_days_ago: int = 1,
        assigned_staff_id: Optional[str] = "staff_002"
    ) -> Ticket:
        """Create a mock bug/technical ticket."""
        created_at = datetime.now(timezone.utc) - timedelta(days=created_days_ago)
        
        ticket = Ticket(
            id=cls.generate_ticket_id(),
            customer_id=customer_id,
            status=status,
            path=path,
            created_at=created_at,
            updated_at=created_at,
            assigned_staff_id=assigned_staff_id
        )
        return ticket

    @classmethod
    def create_message(
        cls,
        ticket_id: str,
        sender: MessageSender = MessageSender.CUSTOMER,
        content: str = "This is a test message",
        attachments: Optional[List[str]] = None,
        created_minutes_ago: int = 0
    ) -> TicketMessage:
        """Create a mock ticket message."""
        created_at = datetime.now(timezone.utc) - timedelta(minutes=created_minutes_ago)
        
        message = TicketMessage(
            id=cls.generate_message_id(),
            ticket_id=ticket_id,
            sender=sender,
            content=content,
            attachments=attachments,
            created_at=created_at
        )
        return message

    @classmethod
    def create_fix_recommendation(
        cls,
        ticket_id: str,
        diff: str = "Sample code diff",
        explanation: str = "This fix addresses the reported issue",
        status: FixRecommendationStatus = FixRecommendationStatus.PENDING,
        reviewed_by: Optional[str] = None,
        reviewed_days_ago: Optional[int] = None
    ) -> FixRecommendation:
        """Create a mock fix recommendation."""
        created_at = datetime.now(timezone.utc)
        reviewed_at = datetime.now(timezone.utc) - timedelta(days=reviewed_days_ago) if reviewed_days_ago else None
        
        fix = FixRecommendation(
            id=cls.generate_fix_id(),
            ticket_id=ticket_id,
            diff=diff,
            explanation=explanation,
            status=status,
            reviewed_by=reviewed_by,
            reviewed_at=reviewed_at,
            notes=None,
            created_at=created_at
        )
        return fix

    @classmethod
    def create_complete_support_ticket(cls) -> Ticket:
        """Create a complete support ticket with messages."""
        ticket = cls.create_support_ticket(
            customer_id="cust_001",
            status=TicketStatus.IN_PROGRESS,
            assigned_staff_id="staff_001"
        )
        
        # Add customer message
        message1 = cls.create_message(
            ticket_id=ticket.id,
            sender=MessageSender.CUSTOMER,
            content="How do I reset my password? I can't access my account.",
            created_minutes_ago=60
        )
        
        # Add support AI response
        message2 = cls.create_message(
            ticket_id=ticket.id,
            sender=MessageSender.SUPPORT_AI,
            content="To reset your password, go to Settings > Security > Change Password. You'll receive an email with instructions.",
            created_minutes_ago=55
        )
        
        # Add customer follow-up
        message3 = cls.create_message(
            ticket_id=ticket.id,
            sender=MessageSender.CUSTOMER,
            content="I tried that but I'm not receiving the email. Can you help?",
            created_minutes_ago=30
        )
        
        ticket.messages = [message1, message2, message3]
        return ticket

    @classmethod
    def create_complete_bug_ticket(cls) -> Ticket:
        """Create a complete bug ticket with messages and fix recommendation."""
        ticket = cls.create_bug_ticket(
            customer_id="cust_002",
            status=TicketStatus.PENDING_STAFF,
            assigned_staff_id="staff_002"
        )
        
        # Add customer message with error
        message1 = cls.create_message(
            ticket_id=ticket.id,
            sender=MessageSender.CUSTOMER,
            content="I'm getting a 500 Internal Server Error when uploading files. Here's the error log.",
            attachments=["error.log", "screenshot.png"],
            created_minutes_ago=120
        )
        
        # Add code AI analysis
        message2 = cls.create_message(
            ticket_id=ticket.id,
            sender=MessageSender.CODE_AI,
            content="Error analysis complete. The issue appears to be in the file upload handler. A fix recommendation has been generated.",
            created_minutes_ago=115
        )
        
        # Add fix recommendation
        fix = cls.create_fix_recommendation(
            ticket_id=ticket.id,
            diff="```diff\n- if file.size > MAX_SIZE:\n-     raise ValidationError()\n+ if file.size > MAX_SIZE:\n+     raise ValidationError('File size exceeds limit')\n```",
            explanation="Add descriptive error message to help users understand the validation failure",
            status=FixRecommendationStatus.PENDING
        )
        
        ticket.messages = [message1, message2]
        ticket.fix_recommendation = fix
        return ticket

    @classmethod
    def create_auto_resolved_ticket(cls) -> Ticket:
        """Create a ticket that was auto-resolved by Support AI."""
        ticket = cls.create_support_ticket(
            customer_id="cust_003",
            status=TicketStatus.RESOLVED_AUTO,
            created_days_ago=2
        )
        
        message1 = cls.create_message(
            ticket_id=ticket.id,
            sender=MessageSender.CUSTOMER,
            content="What are your business hours?",
            created_minutes_ago=120
        )
        
        message2 = cls.create_message(
            ticket_id=ticket.id,
            sender=MessageSender.SUPPORT_AI,
            content="Our business hours are Monday-Friday, 9 AM - 6 PM EST. We also offer limited support on weekends.",
            created_minutes_ago=115
        )
        
        ticket.messages = [message1, message2]
        return ticket

    @classmethod
    def create_closed_ticket(cls) -> Ticket:
        """Create a closed ticket with full resolution."""
        ticket = cls.create_bug_ticket(
            customer_id="cust_004",
            status=TicketStatus.CLOSED,
            created_days_ago=5,
            assigned_staff_id="staff_003"
        )
        
        message1 = cls.create_message(
            ticket_id=ticket.id,
            sender=MessageSender.CUSTOMER,
            content="Database connection timeout error in production",
            attachments=["db_error.log"],
            created_minutes_ago=300
        )
        
        message2 = cls.create_message(
            ticket_id=ticket.id,
            sender=MessageSender.STAFF,
            content="I'm investigating the database connection issue. Can you provide more details about when this occurs?",
            created_minutes_ago=250
        )
        
        fix = cls.create_fix_recommendation(
            ticket_id=ticket.id,
            diff="```diff\n+ pool_timeout = 30\n+ connection_retry = 3\n```",
            explanation="Increase connection pool timeout and add retry logic for transient failures",
            status=FixRecommendationStatus.APPROVED,
            reviewed_by="staff_003",
            reviewed_days_ago=4
        )
        
        message3 = cls.create_message(
            ticket_id=ticket.id,
            sender=MessageSender.SYSTEM,
            content="Fix has been deployed to production",
            created_minutes_ago=60
        )
        
        ticket.messages = [message1, message2, message3]
        ticket.fix_recommendation = fix
        return ticket

    @classmethod
    def create_resolved_chat_session(cls, customer_id: str = "cust_001", created_hours_ago: int = 2) -> ChatSession:
        """Create a chat session that was resolved by AI."""
        chat_session = ChatSession(
            id=str(uuid.uuid4()),
            customer_id=customer_id,
            status=ChatSessionStatus.RESOLVED,
            created_at=datetime.now(timezone.utc) - timedelta(hours=created_hours_ago),
            updated_at=datetime.now(timezone.utc) - timedelta(hours=created_hours_ago - 1),
            ticket_id=None,
            ai_attempts=1,
        )

        # Create chat messages
        message1 = cls.create_chat_message(
            chat_session_id=chat_session.id,
            sender=MessageSender.CUSTOMER,
            content="How do I reset my password?",
            created_minutes_ago=120
        )

        message2 = cls.create_chat_message(
            chat_session_id=chat_session.id,
            sender=MessageSender.SUPPORT_AI,
            content="To reset your password, go to Settings > Security > Change Password. You'll receive an email with instructions to complete the reset.",
            created_minutes_ago=115
        )

        chat_session.messages = [message1, message2]
        return chat_session

    @classmethod
    def create_escalated_chat_session(cls, customer_id: str = "cust_002", created_hours_ago: int = 4) -> ChatSession:
        """Create a chat session that was escalated to a ticket."""
        chat_session = ChatSession(
            id=str(uuid.uuid4()),
            customer_id=customer_id,
            status=ChatSessionStatus.ESCALATED,
            created_at=datetime.now(timezone.utc) - timedelta(hours=created_hours_ago),
            updated_at=datetime.now(timezone.utc) - timedelta(hours=created_hours_ago - 2),
            ticket_id=str(uuid.uuid4()),  # Reference to created ticket
            ai_attempts=3,  # Max attempts reached
        )

        # Create chat messages showing escalation
        message1 = cls.create_chat_message(
            chat_session_id=chat_session.id,
            sender=MessageSender.CUSTOMER,
            content="I'm having trouble with my account billing. I was charged twice this month.",
            created_minutes_ago=240
        )

        message2 = cls.create_chat_message(
            chat_session_id=chat_session.id,
            sender=MessageSender.SUPPORT_AI,
            content="I understand you're concerned about duplicate charges. Let me help you with this billing issue. Can you provide your invoice number?",
            created_minutes_ago=235
        )

        message3 = cls.create_chat_message(
            chat_session_id=chat_session.id,
            sender=MessageSender.CUSTOMER,
            content="I don't have the invoice number handy, but the charges appeared on my statement on the 15th.",
            created_minutes_ago=230
        )

        message4 = cls.create_chat_message(
            chat_session_id=chat_session.id,
            sender=MessageSender.SUPPORT_AI,
            content="Thank you for that information. Since this involves billing discrepancies and I don't have access to your specific account details, I'll need to escalate this to our billing team.",
            created_minutes_ago=225
        )

        chat_session.messages = [message1, message2, message3, message4]
        return chat_session

    @classmethod
    def create_active_chat_session(cls, customer_id: str = "cust_003", created_minutes_ago: int = 10) -> ChatSession:
        """Create an active chat session that's still ongoing."""
        chat_session = ChatSession(
            id=str(uuid.uuid4()),
            customer_id=customer_id,
            status=ChatSessionStatus.ACTIVE,
            created_at=datetime.now(timezone.utc) - timedelta(minutes=created_minutes_ago),
            updated_at=datetime.now(timezone.utc) - timedelta(minutes=created_minutes_ago - 5),
            ticket_id=None,
            ai_attempts=1,
        )

        # Create chat messages
        message1 = cls.create_chat_message(
            chat_session_id=chat_session.id,
            sender=MessageSender.CUSTOMER,
            content="What are your business hours?",
            created_minutes_ago=10
        )

        message2 = cls.create_chat_message(
            chat_session_id=chat_session.id,
            sender=MessageSender.SUPPORT_AI,
            content="Our business hours are Monday-Friday, 9 AM - 6 PM EST. We also offer limited support on weekends.",
            created_minutes_ago=5
        )

        chat_session.messages = [message1, message2]
        return chat_session

    @classmethod
    def create_chat_message(
        cls,
        chat_session_id: str,
        sender: MessageSender = MessageSender.CUSTOMER,
        content: str = "This is a test message",
        created_minutes_ago: int = 0,
        attachments: Optional[List[str]] = None,
    ) -> "ChatMessage":
        """Create a chat message with realistic timestamps."""
        # Import here to avoid circular dependency
        from app.db.models import ChatMessage
        return ChatMessage(
            id=str(uuid.uuid4()),
            chat_session_id=chat_session_id,
            sender=sender,
            content=content,
            attachments=attachments,
            created_at=datetime.now(timezone.utc) - timedelta(minutes=created_minutes_ago),
        )


async def seed_mock_database(session: AsyncSession) -> None:
    """
    Seed the database with mock data for testing.

    This function creates a variety of tickets and chat sessions in different states to support
    comprehensive testing of the platform.
    """
    mock_db = MockDatabase()

    # Create different types of tickets
    tickets = [
        mock_db.create_complete_support_ticket(),
        mock_db.create_complete_bug_ticket(),
        mock_db.create_auto_resolved_ticket(),
        mock_db.create_closed_ticket(),

        # Additional simple tickets
        mock_db.create_support_ticket(
            customer_id="cust_005",
            status=TicketStatus.OPEN,
            created_days_ago=0
        ),
        mock_db.create_bug_ticket(
            customer_id="cust_001",
            status=TicketStatus.PENDING_CUSTOMER,
            created_days_ago=3,
            assigned_staff_id="staff_001"
        ),
    ]

    # Create different types of chat sessions
    chat_sessions = [
        mock_db.create_resolved_chat_session(),
        mock_db.create_escalated_chat_session(),
        mock_db.create_active_chat_session(),
    ]

    # Add all tickets and their relationships to the session
    for ticket in tickets:
        session.add(ticket)
        # Messages and fix_recommendations are automatically added via cascade

    # Add all chat sessions and their relationships to the session
    for chat_session in chat_sessions:
        session.add(chat_session)
        # Messages are automatically added via cascade
    
    await session.commit()


async def clear_mock_database(session: AsyncSession) -> None:
    """
    Clear all mock data from the database.
    
    This is useful for cleaning up between tests or when resetting the
    GUI to a clean state.
    """
    # Delete in order of dependencies (fix recommendations first, then messages, then tickets)
    await session.execute(delete(FixRecommendation))
    await session.execute(delete(TicketMessage))
    await session.execute(delete(Ticket))
    
    await session.commit()


def get_mock_customer_ids() -> List[str]:
    """Get list of mock customer IDs."""
    return list(MockDatabase.CUSTOMERS.keys())


def get_mock_staff_ids() -> List[str]:
    """Get list of mock staff IDs."""
    return list(MockDatabase.STAFF.keys())


def get_mock_customer_info(customer_id: str) -> Optional[dict]:
    """Get mock customer information by ID."""
    return MockDatabase.CUSTOMERS.get(customer_id)


def get_mock_staff_info(staff_id: str) -> Optional[dict]:
    """Get mock staff information by ID."""
    return MockDatabase.STAFF.get(staff_id)