from enum import StrEnum
from typing import Any, Self

from pydantic import BaseModel, Field, model_validator


class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNKNOWN = "unknown"


class IdentificationOutcome(StrEnum):
    MATCHED = "matched"
    AMBIGUOUS = "ambiguous"
    NO_CUSTOMER_FOUND = "no_customer_found"
    OUT_OF_SCOPE = "out_of_scope"


class EvidenceKind(StrEnum):
    EXACT_ADDRESS = "exact_address"
    PARTIAL_ADDRESS = "partial_address"
    CUSTOMER_NAME = "customer_name"
    BANK_NAME = "bank_name"
    EXACT_OUTSTANDING = "exact_outstanding"
    PARTIAL_PAYMENT = "partial_payment"
    RUT = "rut"
    BANK_ACCOUNT = "bank_account"
    EMAIL = "email"
    PHONE = "phone"
    VAMBE_CONTEXT = "vambe_context"
    IDENTITY_CONFLICT = "identity_conflict"
    AMOUNT_EXCEEDS_OUTSTANDING = "amount_exceeds_outstanding"
    CURRENCY_MISMATCH = "currency_mismatch"


class EvidencePolarity(StrEnum):
    SUPPORTING = "supporting"
    CONTRADICTING = "contradicting"


class EvidenceStrength(StrEnum):
    STRONG = "strong"
    MEDIUM = "medium"
    WEAK = "weak"


class EvidenceSource(StrEnum):
    PAYMENT_CANDIDATES = "payment_candidates"
    CANDIDATE_VERIFICATION = "candidate_verification"
    VAMBE = "vambe"


class UnverifiedField(StrEnum):
    AMOUNT = "amount"
    GLOSA = "glosa"
    TRANSFEROR = "transferor"
    DATE = "date"
    CUSTOMER_IDENTITY = "customer_identity"
    ACCOUNT_RECEIVABLE = "account_receivable"
    VAMBE_CONTEXT = "vambe_context"
    PAYMENT_EVIDENCE = "payment_evidence"


class EvidenceSignal(BaseModel):
    evidence_id: str = Field(default="", max_length=32)
    kind: EvidenceKind
    source: EvidenceSource
    polarity: EvidencePolarity
    strength: EvidenceStrength
    description: str = Field(max_length=240)
    order_id: str | None = None
    account_receivable_id: str | None = None


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
    evidence_ids: list[str] = Field(default_factory=list)


class PaymentIdentification(BaseModel):
    """Structured result rendered to Spanish Slack prose by the surface adapter."""

    outcome: IdentificationOutcome = IdentificationOutcome.AMBIGUOUS
    recommended_customer: CustomerCandidate | None = None
    account_receivable_summary: str | None = None
    confidence: Confidence
    investigation_summary: str
    unable_to_verify: list[str] = Field(default_factory=list)
    alternatives: list[CustomerCandidate] = Field(default_factory=list, max_length=3)
    evidence: list[EvidenceSignal] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def infer_legacy_outcome(cls, value: Any) -> Any:
        if isinstance(value, dict) and "outcome" not in value:
            value = dict(value)
            value["outcome"] = (
                IdentificationOutcome.MATCHED
                if value.get("recommended_customer")
                else IdentificationOutcome.AMBIGUOUS
            )
        return value

    @model_validator(mode="after")
    def outcome_is_consistent(self) -> Self:
        if self.outcome is IdentificationOutcome.MATCHED:
            if self.recommended_customer is None:
                raise ValueError("matched results require a recommended customer")
            if self.confidence not in {Confidence.HIGH, Confidence.MEDIUM}:
                raise ValueError("matched results require high or medium confidence")
        else:
            if self.recommended_customer is not None or self.account_receivable_summary is not None:
                raise ValueError("non-matched results cannot recommend a customer")
            if self.confidence is not Confidence.UNKNOWN:
                raise ValueError("non-matched results require unknown confidence")
        if (
            self.outcome
            in {
                IdentificationOutcome.NO_CUSTOMER_FOUND,
                IdentificationOutcome.OUT_OF_SCOPE,
            }
            and self.alternatives
        ):
            raise ValueError("this outcome cannot include alternatives")
        return self


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
