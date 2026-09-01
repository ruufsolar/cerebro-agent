from enum import StrEnum

from pydantic import BaseModel, Field


class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNKNOWN = "unknown"


class CompletionReason(StrEnum):
    COMPLETED = "completed"
    TIMEOUT = "timeout"
    TURN_LIMIT = "turn_limit"
    TOOL_LIMIT = "tool_limit"
    REFUSAL = "refusal"
    INVALID_OUTPUT = "invalid_output"


class CustomerCandidate(BaseModel):
    customer_name: str
    order_id: str
    crm_url: str
    reason: str


class PaymentIdentification(BaseModel):
    """Structured result rendered to Spanish Slack prose by the surface adapter."""

    recommended_customer: CustomerCandidate | None = None
    account_receivable_summary: str | None = None
    confidence: Confidence
    investigation_summary: str
    unable_to_verify: list[str] = Field(default_factory=list)
    alternatives: list[CustomerCandidate] = Field(default_factory=list, max_length=3)


class AgentUsage(BaseModel):
    model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    turns: int = 0
    tool_calls: int = 0


class ToolAuditRecord(BaseModel):
    sequence: int
    tool_name: str
    status: str
    input: dict[str, object] | None = None
    output: dict[str, object] | list[object] | None = None
    duration_ms: int | None = None
    error: str | None = None
    query_fingerprint: str | None = None
    referenced_relations: list[str] = Field(default_factory=list)
    row_count: int | None = None
    truncated: bool | None = None


class AgentStep(BaseModel):
    type: str
    name: str | None = None
    status: str | None = None
