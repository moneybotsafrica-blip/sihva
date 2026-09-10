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
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


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


class AISuggestedResolutionStatus(str, PyEnum):
    PENDING = "PENDING"
    REVIEWED = "REVIEWED"
    USED = "USED"
    DISMISSED = "DISMISSED"
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
    title: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
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
    # Additional custom data for customer-specific information
    custom_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    # External system reference (if syncing from another system)
    external_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    external_system: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # e.g., "shopify", "stripe"


class Staff(Base):
    """Staff members who handle support tickets."""
    __tablename__ = "staff"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)  # Staff ID from your system
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(50), nullable=False, default="staff")  # "staff" or "developer"
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False
    )
    # Additional custom data for staff-specific information
    custom_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    # External system reference (if syncing from another system)
    external_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    external_system: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # e.g., "okta", "auth0"


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

    # AI-generated title for the ticket
    title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Track AI attempts on this ticket to prevent endless AI loops
    ai_attempts: Mapped[int] = mapped_column(nullable=False, default=0)

    # AI Resolution Feedback
    ai_resolution_feedback: Mapped[Optional[AIResolutionFeedback]] = mapped_column(
        SQLEnum(AIResolutionFeedback), nullable=True
    )
    ai_resolution_feedback_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    ai_resolution_feedback_comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ai_resolution_confidence: Mapped[Optional[float]] = mapped_column(nullable=True)
    
    # AI resolution metadata for analytics
    ai_agent_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # e.g., "Technical", "Billing", "General"
    ai_kb_article_ids: Mapped[Optional[list[str]]] = mapped_column(JSON, nullable=True)  # KB articles used
    ai_kb_similarity_score: Mapped[Optional[float]] = mapped_column(nullable=True)  # Best KB match score

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
    ai_suggested_resolution: Mapped[Optional["AISuggestedResolution"]] = relationship(
        "AISuggestedResolution", back_populates="ticket", uselist=False, cascade="all, delete-orphan"
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


class AISuggestedResolution(Base):
    """Staff-only AI suggested resolution for escalated tickets.
    
    This stores the AI's proposed solution/diagnosis for complex issues that
    were escalated to staff. It's only visible to staff and developer roles,
    not to customers. Staff can review, use, or dismiss these suggestions.
    """
    __tablename__ = "ai_suggested_resolutions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    ticket_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    suggested_solution: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(nullable=False)
    escalation_reason: Mapped[str] = mapped_column(Text, nullable=False)
    kb_article_ids: Mapped[Optional[list[str]]] = mapped_column(JSON, nullable=True)
    kb_similarity_score: Mapped[Optional[float]] = mapped_column(nullable=True)
    agent_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    status: Mapped[AISuggestedResolutionStatus] = mapped_column(
        SQLEnum(AISuggestedResolutionStatus), nullable=False, default=AISuggestedResolutionStatus.PENDING
    )
    reviewed_by: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    ticket: Mapped["Ticket"] = relationship("Ticket", back_populates="ai_suggested_resolution")


# Dynamic Routing Models
class RuleConditionType(str, PyEnum):
    """Types of conditions for routing rules."""
    CONTAINS = "contains"
    REGEX = "regex"
    EXACT_MATCH = "exact_match"
    LENGTH_GREATER_THAN = "length_greater_than"
    LENGTH_LESS_THAN = "length_less_than"
    HAS_ATTACHMENT = "has_attachment"
    ATTACHMENT_TYPE = "attachment_type"
    CUSTOMER_PLAN = "customer_plan"
    TIME_OF_DAY = "time_of_day"
    DAY_OF_WEEK = "day_of_week"
    CONFIDENCE_THRESHOLD = "confidence_threshold"
    KB_SIMILARITY = "kb_similarity"
    COMPLEXITY_SCORE = "complexity_score"


class RuleActionType(str, PyEnum):
    """Types of actions for routing rules."""
    ROUTE_TO = "route_to"
    SET_PRIORITY = "set_priority"
    ADD_TAG = "add_tag"
    ESCALATE = "escalate"
    REQUIRE_HUMAN = "require_human"
    USE_AI_MODEL = "use_ai_model"
    CALL_WEBHOOK = "call_webhook"


class RoutingDestination(Base):
    """Available routing destinations for customer queries."""
    __tablename__ = "routing_destinations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)  # e.g., "support_ai", "code_ai", "billing", "staff"
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)  # Human-readable name
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    destination_type: Mapped[str] = mapped_column(String(50), nullable=False)  # "ai", "human", "webhook", "api"
    config: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)  # Destination-specific config
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    priority: Mapped[int] = mapped_column(nullable=False, default=100)  # Lower number = higher priority
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False
    )


class RoutingRule(Base):
    """Dynamic routing rules for intelligent query classification."""
    __tablename__ = "routing_rules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)  # Human-readable rule name
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Rule conditions (stored as JSON array of condition objects)
    conditions: Mapped[list[dict]] = mapped_column(JSON, nullable=False)
    # Example: [{"type": "contains", "field": "message", "value": "error", "case_sensitive": false}]
    
    # Rule actions (stored as JSON array of action objects)
    actions: Mapped[list[dict]] = mapped_column(JSON, nullable=False)
    # Example: [{"type": "route_to", "destination": "code_ai", "priority": 1}]
    
    # Rule metadata
    priority: Mapped[int] = mapped_column(nullable=False, default=100)  # Rule evaluation order
    weight: Mapped[float] = mapped_column(nullable=False, default=1.0)  # Scoring weight
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    
    # Performance tracking
    total_matches: Mapped[int] = mapped_column(nullable=False, default=0)
    successful_matches: Mapped[int] = mapped_column(nullable=False, default=0)  # Led to positive outcome
    last_matched_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    
    # Lifecycle
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False
    )
    created_by: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)  # Staff ID or "system"
    
    # Versioning for A/B testing
    version: Mapped[int] = mapped_column(nullable=False, default=1)
    is_experiment: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    parent_rule_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)


class RoutingMetric(Base):
    """Metrics for tracking routing performance."""
    __tablename__ = "routing_metrics"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    ticket_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    chat_session_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    
    # Routing decision
    rule_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    destination: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    confidence_score: Mapped[Optional[float]] = mapped_column(nullable=True)
    
    # Context
    message: Mapped[str] = mapped_column(Text, nullable=False)
    customer_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    customer_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    
    # Outcome tracking
    resolution_time_seconds: Mapped[Optional[int]] = mapped_column(nullable=True)
    first_response_time_seconds: Mapped[Optional[int]] = mapped_column(nullable=True)
    customer_satisfaction: Mapped[Optional[int]] = mapped_column(nullable=True)  # 1-5 scale
    was_escalated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    escalation_count: Mapped[int] = mapped_column(nullable=False, default=0)
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class RoutingFeedback(Base):
    """Feedback on routing decisions for continuous improvement."""
    __tablename__ = "routing_feedback"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    metric_id: Mapped[str] = mapped_column(String(36), ForeignKey("routing_metrics.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Feedback source
    feedback_source: Mapped[str] = mapped_column(String(50), nullable=False)  # "customer", "staff", "system"
    feedback_type: Mapped[str] = mapped_column(String(50), nullable=False)  # "correct", "incorrect", "partial"
    
    # Feedback details
    correct_destination: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    rating: Mapped[Optional[int]] = mapped_column(nullable=True)  # 1-5 scale
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    
    # Relationship
    metric: Mapped["RoutingMetric"] = relationship("RoutingMetric", backref="feedback")
