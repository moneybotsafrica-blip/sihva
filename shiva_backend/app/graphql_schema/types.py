import strawberry
from datetime import datetime
from typing import Optional, List, Annotated
from enum import Enum


@strawberry.enum
class TicketStatus(Enum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    PENDING_STAFF = "PENDING_STAFF"
    PENDING_CUSTOMER = "PENDING_CUSTOMER"
    RESOLVED_AUTO = "RESOLVED_AUTO"
    CLOSED = "CLOSED"


@strawberry.enum
class TicketPath(Enum):
    SUPPORT = "support"
    BUG = "bug"


@strawberry.enum
class MessageSender(Enum):
    CUSTOMER = "customer"
    SUPPORT_AI = "support_ai"
    CODE_AI = "code_ai"
    STAFF = "staff"
    SYSTEM = "system"


@strawberry.enum
class FixRecommendationStatus(Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    NEEDS_INFO = "NEEDS_INFO"


@strawberry.enum
class UserRole(Enum):
    CUSTOMER = "customer"
    STAFF = "staff"
    DEVELOPER = "developer"


@strawberry.enum
class AIResolutionFeedback(Enum):
    HELPFUL = "helpful"
    NOT_HELPFUL = "not_helpful"
    PARTIALLY_HELPFUL = "partially_helpful"
    NEEDS_HUMAN = "needs_human"


@strawberry.enum
class ChatSessionStatus(Enum):
    ACTIVE = "active"
    RESOLVED = "resolved"
    ESCALATED = "escalated"


@strawberry.type
class TicketMessage:
    id: str
    ticket_id: str
    sender: MessageSender
    content: str
    attachments: Optional[List[str]]
    created_at: datetime


@strawberry.type
class ChatMessage:
    id: str
    chat_session_id: str
    sender: MessageSender
    content: str
    attachments: Optional[List[str]]
    created_at: datetime


@strawberry.type
class ChatSession:
    id: str
    customer_id: str
    status: ChatSessionStatus
    created_at: datetime
    updated_at: datetime
    ticket_id: Optional[str]
    ai_attempts: int
    messages: List[ChatMessage]


@strawberry.type
class FixRecommendation:
    id: str
    ticket_id: str
    diff: str
    explanation: str
    status: FixRecommendationStatus
    reviewed_by: Optional[str]
    reviewed_at: Optional[datetime]
    notes: Optional[str]
    created_at: datetime


@strawberry.type
class Ticket:
    id: str
    customer_id: str
    status: TicketStatus
    path: TicketPath
    created_at: datetime
    updated_at: datetime
    assigned_staff_id: Optional[str]
    messages: List[TicketMessage]
    fix_recommendation: Optional[FixRecommendation]
    ai_resolution_feedback: Optional[AIResolutionFeedback]
    ai_resolution_feedback_at: Optional[datetime]
    ai_resolution_feedback_comment: Optional[str]
    ai_resolution_confidence: Optional[float]
    chat_summary: Optional[str]
    staff_notes: Optional[List[str]]


@strawberry.input
class SendMessageInput:
    content: str
    attachment_ids: Optional[List[str]] = None


@strawberry.input
class AssignTicketInput:
    ticket_id: str
    staff_id: str


@strawberry.input
class ReplyToTicketInput:
    ticket_id: str
    content: str
    attachment_ids: Optional[List[str]] = None


@strawberry.input
class ReviewFixInput:
    ticket_id: str
    notes: Optional[str] = None


@strawberry.input
class CloseTicketInput:
    ticket_id: str


@strawberry.input
class RequestHumanAgentInput:
    ticket_id: str
    reason: Optional[str] = None


@strawberry.input
class AIResolutionFeedbackInput:
    ticket_id: str
    feedback: AIResolutionFeedback
    comment: Optional[str] = None


@strawberry.input
class SendChatMessageInput:
    content: str
    attachment_ids: Optional[List[str]] = None


@strawberry.type
class StaffAIAssistance:
    suggested_response: Optional[str]
    confidence: float
    kb_context_used: bool
    reasoning: Optional[str]


@strawberry.type
class TicketContextAnalysis:
    issue_summary: str
    customer_sentiment: str
    suggested_actions: List[str]
    complexity_score: float


@strawberry.type
class EscalationSuggestion:
    should_escalate: bool
    suggested_escalation_target: Optional[str]
    reasoning: str
    confidence: float


@strawberry.input
class StaffAssistanceInput:
    ticket_id: str
    staff_query: str


@strawberry.input
class AnalyzeTicketContextInput:
    ticket_id: str


@strawberry.input
class SuggestEscalationInput:
    ticket_id: str
    current_issue: str


@strawberry.input
class AddStaffNoteInput:
    ticket_id: str
    note: str


@strawberry.type
class StaffInfo:
    staff_id: str
    name: str
    role: str


__all__ = [
    "TicketStatus",
    "TicketPath",
    "MessageSender",
    "FixRecommendationStatus",
    "UserRole",
    "AIResolutionFeedback",
    "ChatSessionStatus",
    "TicketMessage",
    "ChatMessage",
    "ChatSession",
    "FixRecommendation",
    "Ticket",
    "SendMessageInput",
    "AssignTicketInput",
    "ReplyToTicketInput",
    "ReviewFixInput",
    "CloseTicketInput",
    "RequestHumanAgentInput",
    "AIResolutionFeedbackInput",
    "SendChatMessageInput",
    "StaffAIAssistance",
    "TicketContextAnalysis",
    "EscalationSuggestion",
    "StaffAssistanceInput",
    "AnalyzeTicketContextInput",
    "SuggestEscalationInput",
    "AddStaffNoteInput",
    "StaffInfo",
]
