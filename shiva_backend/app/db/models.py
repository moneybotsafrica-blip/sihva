from datetime import datetime, timezone
from enum import Enum as PyEnum
from typing import Optional
import json
import secrets

from sqlalchemy import (
    String,
    Text,
    DateTime,
    ForeignKey,
    Index,
    CheckConstraint,
    Enum as SQLEnum,
    JSON,
    Boolean,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, selectinload


class Base(DeclarativeBase):
    pass


class TicketStatus(str, PyEnum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    PENDING_STAFF = "PENDING_STAFF"
    PENDING_CUSTOMER = "PENDING_CUSTOMER"
    RESOLVED_AUTO = "RESOLVED_AUTO"
    CLOSED = "CLOSED"


class TicketPath(str, PyEnum):
    SUPPORT = "support"
    BUG = "bug"


class MessageSender(str, PyEnum):
    CUSTOMER = "customer"
    SUPPORT_AI = "support_ai"
    CODE_AI = "code_ai"
    STAFF = "staff"
    SYSTEM = "system"


class FixRecommendationStatus(str, PyEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    NEEDS_INFO = "NEEDS_INFO"


class AIResolutionFeedback(str, PyEnum):
    HELPFUL = "helpful"
    NOT_HELPFUL = "not_helpful"
    PARTIALLY_HELPFUL = "partially_helpful"
    NEEDS_HUMAN = "needs_human"


class ChatSessionStatus(str, PyEnum):
    ACTIVE = "active"
    RESOLVED = "resolved"
    ESCALATED = "escalated"


class APIKeyScope(str, PyEnum):
    """API key scopes for different access levels."""
    FRONTEND = "frontend"  # For frontend applications
    INTERNAL = "internal"  # For internal services
    ADMIN = "admin"  # For administrative access


# For SQLite compatibility, we'll use string storage instead of Enum
API_KEY_SCOPES = ["frontend", "internal", "admin"]


class ChatSession(Base):
    """Chat sessions that may or may not become tickets."""
    __tablename__ = "chat_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    customer_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    status: Mapped[ChatSessionStatus] = mapped_column(
        SQLEnum(ChatSessionStatus), nullable=False, default=ChatSessionStatus.ACTIVE
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False
    )
    # If escalated, link to the created ticket
    ticket_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    # Track AI attempts to prevent premature escalation
    ai_attempts: Mapped[int] = mapped_column(nullable=False, default=0)

    messages: Mapped[list["ChatMessage"]] = relationship(
        "ChatMessage", back_populates="chat_session", cascade="all, delete-orphan"
    )


class ChatMessage(Base):
    """Messages in a chat session before ticket creation."""
    __tablename__ = "chat_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    chat_session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sender: Mapped[MessageSender] = mapped_column(SQLEnum(MessageSender), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    attachments: Mapped[Optional[list[str]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    chat_session: Mapped["ChatSession"] = relationship("ChatSession", back_populates="messages")


class APIKey(Base):
    """API keys for external access to the system."""
    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)  # Human-readable name for the key
    scope: Mapped[str] = mapped_column(String(20), nullable=False, default="frontend")  # Using string for SQLite compatibility
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_by: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)  # User or system that created the key

    @staticmethod
    def generate_key() -> str:
        """Generate a secure API key."""
        return f"shiva_{secrets.token_urlsafe(32)}"

    @staticmethod
    def hash_key(key: str) -> str:
        """Hash an API key for storage."""
        import hashlib
        return hashlib.sha256(key.encode()).hexdigest()


class Customer(Base):
    """Customer accounts stored in the Shiva support database."""
    __tablename__ = "customers"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)  # Customer ID from your system
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    plan: Mapped[str] = mapped_column(String(50), nullable=False, default="basic")  # Subscription plan
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False
    )
    # Additional metadata for custom customer data
    metadata: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    # External system reference (if syncing from another system)
    external_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    external_system: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # e.g., "shopify", "stripe"


class Ticket(Base):
    __tablename__ = "tickets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    customer_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    status: Mapped[TicketStatus] = mapped_column(
        SQLEnum(TicketStatus), nullable=False, default=TicketStatus.OPEN
    )
    path: Mapped[TicketPath] = mapped_column(SQLEnum(TicketPath), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False
    )
    assigned_staff_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)

    # AI Resolution Feedback
    ai_resolution_feedback: Mapped[Optional[AIResolutionFeedback]] = mapped_column(
        SQLEnum(AIResolutionFeedback), nullable=True
    )
    ai_resolution_feedback_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    ai_resolution_feedback_comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ai_resolution_confidence: Mapped[Optional[float]] = mapped_column(nullable=True)

    # Chat summary for staff when ticket is escalated
    chat_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Staff notes for internal communication
    staff_notes: Mapped[Optional[list[str]]] = mapped_column(JSON, nullable=True)

    # One open ticket per customer constraint
    __table_args__ = (
        Index(
            "idx_one_open_ticket_per_customer",
            "customer_id",
            unique=True,
            postgresql_where=(status.notin_([TicketStatus.CLOSED, TicketStatus.RESOLVED_AUTO])),
        ),
    )

    messages: Mapped[list["TicketMessage"]] = relationship(
        "TicketMessage", back_populates="ticket", cascade="all, delete-orphan"
    )
    fix_recommendation: Mapped[Optional["FixRecommendation"]] = relationship(
        "FixRecommendation", back_populates="ticket", uselist=False, cascade="all, delete-orphan"
    )


class TicketMessage(Base):
    __tablename__ = "ticket_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    ticket_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sender: Mapped[MessageSender] = mapped_column(SQLEnum(MessageSender), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    attachments: Mapped[Optional[list[str]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    ticket: Mapped["Ticket"] = relationship("Ticket", back_populates="messages")


class FixRecommendation(Base):
    __tablename__ = "fix_recommendations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    ticket_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    diff: Mapped[str] = mapped_column(Text, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[FixRecommendationStatus] = mapped_column(
        SQLEnum(FixRecommendationStatus), nullable=False, default=FixRecommendationStatus.PENDING
    )
    reviewed_by: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    ticket: Mapped["Ticket"] = relationship("Ticket", back_populates="fix_recommendation")
