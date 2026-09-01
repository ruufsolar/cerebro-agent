"""Typed, read-only investigation data boundary for Cerebro."""

from collections.abc import Mapping
from datetime import date
from decimal import Decimal
from typing import Annotated, Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, Field, WithJsonSchema, model_validator

ToolDecimal = Annotated[
    Decimal,
    Field(gt=0),
    WithJsonSchema({"type": "number"}),
]


class ToolAuditMetadata(BaseModel):
    query_fingerprint: str | None = None
    referenced_relations: list[str] = Field(default_factory=list)
    row_count: int | None = None
    truncated: bool | None = None


class InvestigationCandidate(BaseModel):
    customer_name: str
    order_id: UUID
    order_number: int | None = None
    account_receivable_id: UUID | None = None
    account_receivable_summary: str | None = None
    outstanding_amount: Decimal | None = None
    currency: str | None = None
    evidence: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    verified: bool = False


class ToolObservation(BaseModel):
    source: str
    available: bool
    summary: str
    candidates: list[InvestigationCandidate] = Field(default_factory=list)
    rows: list[dict[str, object]] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    audit: ToolAuditMetadata = Field(default_factory=ToolAuditMetadata, exclude=True)

    def safe_audit_summary(self) -> dict[str, object]:
        return {
            "source": self.source,
            "available": self.available,
            "candidate_count": len(self.candidates),
            "row_count": self.audit.row_count,
            "truncated": self.audit.truncated,
            "limitation_count": len(self.limitations),
        }


class KnowledgeQuery(BaseModel):
    topic: Literal["identification_policy", "data_scope", "limitations"]


class SchemaQuery(BaseModel):
    names: list[str] = Field(min_length=1, max_length=8)


class PaymentCandidateQuery(BaseModel):
    glosa_or_address: str | None = Field(default=None, max_length=500)
    transferor_name: str | None = Field(default=None, max_length=300)
    transferor_rut: str | None = Field(default=None, max_length=30)
    origin_account_number: str | None = Field(default=None, max_length=80)
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=40)
    amount: ToolDecimal | None = None
    currency: Literal["CLP", "USD", "CLF"] | None = None
    payment_date: date | None = None

    @model_validator(mode="after")
    def has_signal(self) -> "PaymentCandidateQuery":
        values = (
            self.glosa_or_address,
            self.transferor_name,
            self.transferor_rut,
            self.origin_account_number,
            self.email,
            self.phone,
            self.amount,
        )
        if not any(value is not None and value != "" for value in values):
            raise ValueError("at least one payment-identification signal is required")
        return self


class VerifyCandidateQuery(BaseModel):
    order_id: UUID
    account_receivable_id: UUID | None = None
    amount: ToolDecimal | None = None
    currency: Literal["CLP", "USD", "CLF"] | None = None
    transferor_name: str | None = Field(default=None, max_length=300)
    address: str | None = Field(default=None, max_length=500)


class VambeQuery(BaseModel):
    order_id: UUID | None = None
    phone: str | None = Field(default=None, max_length=40)
    query: str | None = Field(default=None, max_length=300)
    start_date: date | None = None
    end_date: date | None = None

    @model_validator(mode="after")
    def candidate_scoped(self) -> "VambeQuery":
        if self.order_id is None and not self.phone:
            raise ValueError("Vambe search requires an order_id or phone")
        if (self.start_date is None) != (self.end_date is None):
            raise ValueError("start_date and end_date must be provided together")
        return self


class ReadonlySqlQuery(BaseModel):
    query: str = Field(min_length=1, max_length=10_000)


ToolRequest = (
    KnowledgeQuery
    | SchemaQuery
    | PaymentCandidateQuery
    | VerifyCandidateQuery
    | VambeQuery
    | ReadonlySqlQuery
)


def safe_input_summary(request: ToolRequest) -> dict[str, object]:
    if isinstance(request, ReadonlySqlQuery):
        return {"query_present": True, "query_characters": len(request.query)}
    if isinstance(request, SchemaQuery):
        return {"table_count": len(request.names)}
    if isinstance(request, KnowledgeQuery):
        return {"topic": request.topic}
    values = request.model_dump(mode="json", exclude_none=True)
    return {f"has_{name}": True for name in values}


class InvestigationData(Protocol):
    async def start(self) -> None: ...

    async def close(self) -> None: ...

    async def read_finops_knowledge(self, request: KnowledgeQuery) -> ToolObservation: ...

    async def describe_database_tables(self, request: SchemaQuery) -> ToolObservation: ...

    async def search_payment_candidates(
        self, request: PaymentCandidateQuery
    ) -> ToolObservation: ...

    async def verify_payment_candidate(self, request: VerifyCandidateQuery) -> ToolObservation: ...

    async def search_vambe_messages(self, request: VambeQuery) -> ToolObservation: ...

    async def run_readonly_sql(self, request: ReadonlySqlQuery) -> ToolObservation: ...


class EmptyInvestigationData:
    @staticmethod
    def _unavailable(source: str) -> ToolObservation:
        return ToolObservation(
            source=source,
            available=False,
            summary="La fuente de datos reales todavía no está conectada.",
            limitations=["No se consultaron datos de clientes de Ruuf."],
        )

    async def start(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def read_finops_knowledge(self, request: KnowledgeQuery) -> ToolObservation:
        del request
        return self._unavailable("finops_knowledge")

    async def describe_database_tables(self, request: SchemaQuery) -> ToolObservation:
        del request
        return self._unavailable("database_schema")

    async def search_payment_candidates(self, request: PaymentCandidateQuery) -> ToolObservation:
        del request
        return self._unavailable("payment_candidates")

    async def verify_payment_candidate(self, request: VerifyCandidateQuery) -> ToolObservation:
        del request
        return self._unavailable("candidate_verification")

    async def search_vambe_messages(self, request: VambeQuery) -> ToolObservation:
        del request
        return self._unavailable("vambe")

    async def run_readonly_sql(self, request: ReadonlySqlQuery) -> ToolObservation:
        del request
        return self._unavailable("readonly_sql")


class FixtureInvestigationData(EmptyInvestigationData):
    """Synthetic-only backend for tests and opt-in model evaluations."""

    def __init__(self, observations: Mapping[str, ToolObservation]) -> None:
        self._observations = dict(observations)

    def _get(self, name: str) -> ToolObservation:
        return self._observations.get(
            name,
            ToolObservation(source=name, available=True, summary="Sin coincidencias sintéticas."),
        )

    async def read_finops_knowledge(self, request: KnowledgeQuery) -> ToolObservation:
        del request
        return self._get("finops_knowledge")

    async def describe_database_tables(self, request: SchemaQuery) -> ToolObservation:
        del request
        return self._get("database_schema")

    async def search_payment_candidates(self, request: PaymentCandidateQuery) -> ToolObservation:
        del request
        return self._get("payment_candidates")

    async def verify_payment_candidate(self, request: VerifyCandidateQuery) -> ToolObservation:
        del request
        return self._get("candidate_verification")

    async def search_vambe_messages(self, request: VambeQuery) -> ToolObservation:
        del request
        return self._get("vambe")

    async def run_readonly_sql(self, request: ReadonlySqlQuery) -> ToolObservation:
        del request
        return self._get("readonly_sql")
