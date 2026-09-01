from enum import StrEnum

from pydantic import BaseModel, Field


class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNKNOWN = "unknown"


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
