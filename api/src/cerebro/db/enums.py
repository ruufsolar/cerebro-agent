from enum import StrEnum


class ConversationState(StrEnum):
    OPEN = "open"
    RUNNING = "running"
    ANSWERED = "answered"
    FAILED = "failed"


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class DeliveryStatus(StrEnum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"


class SlackEventDisposition(StrEnum):
    RECEIVED = "received"
    QUEUED = "queued"
    PROCESSED = "processed"
    IGNORED = "ignored"
    FAILED = "failed"


class SlackOutputKind(StrEnum):
    INVESTIGATION = "investigation"
    FEEDBACK_FLAVOR = "feedback_flavor"
    ERROR = "error"
