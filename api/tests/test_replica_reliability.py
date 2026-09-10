import asyncio
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import asyncpg
import pytest

from cerebro.agent.data_tools import PaymentCandidateQuery, VambeQuery, VerifyCandidateQuery
from cerebro.agent.models import EvidenceKind
from cerebro.config import AppConfig
from cerebro.replica.database import QueryResult, ReplicaDatabase
from cerebro.replica.investigation import ReplicaInvestigationData
from cerebro.replica.scope import load_knowledge

KNOWLEDGE_DIR = Path(__file__).parents[2] / "knowledge"


@pytest.mark.parametrize(
    "glosa, exact",
    [
        ("Pago OTRA, CALLE 12 Santiago", True),
        ("Pago Otra Calle 123 Santiago", False),
        ("Pago Otra Calle 12 Santiaguito", False),
    ],
)
async def test_exact_address_requires_complete_tokens(glosa: str, exact: bool) -> None:
    database = _CandidateDatabase({"full_address": "Otra Calle 12 Santiago"})
    data = ReplicaInvestigationData(
        cast(ReplicaDatabase, database), load_knowledge(KNOWLEDGE_DIR), KNOWLEDGE_DIR
    )
    observation = await data.search_payment_candidates(
        PaymentCandidateQuery(glosa_or_address=glosa, transferor_name="Alberto Amigo")
    )
    kinds = {signal.kind for signal in observation.candidates[0].evidence}
    assert (EvidenceKind.EXACT_ADDRESS in kinds) == exact


async def test_vambe_text_hit_never_becomes_payment_confirmation() -> None:
    class Database:
        async def fetch_bounded(self, query: str, *args: object, **kwargs: object) -> QueryResult:
            row = {"user_id": str(UUID(int=1)), "phone": "123", "content": "No pagué"}
            return QueryResult(tuple(row), (row,), 1, False)

    data = ReplicaInvestigationData(
        cast(ReplicaDatabase, Database()), load_knowledge(KNOWLEDGE_DIR), KNOWLEDGE_DIR
    )
    result = await data.search_vambe_messages(VambeQuery(order_id=UUID(int=2), query="pago"))
    assert [signal.kind for signal in result.evidence] == [EvidenceKind.VAMBE_MENTION]


@pytest.mark.parametrize("hint", ["Pago Calle Antigua 42 Santiago", "Eva Prueba"])
async def test_historical_identity_is_searchable_without_collectible_receivable(hint: str) -> None:
    class HistoricalDatabase:
        async def fetch_bounded(self, query: str, *args: object, **kwargs: object) -> QueryResult:
            if "WITH eligible AS" in query or "WITH scored AS" in query:
                return QueryResult((), (), 0, False)
            # No active receivable; a customer identity and historical installation remain.
            row = {
                "customer_name": "Eva Prueba",
                "order_id": str(UUID(int=4)),
                "order_number": 44,
                "full_address": "Calle Antigua 42 Santiago",
            }
            return QueryResult(tuple(row), (row,), 1, False)

    data = ReplicaInvestigationData(
        cast(ReplicaDatabase, HistoricalDatabase()), load_knowledge(KNOWLEDGE_DIR), KNOWLEDGE_DIR
    )
    discovered = await data.search_payment_candidates(PaymentCandidateQuery(glosa_or_address=hint))
    assert len(discovered.candidates) == 1
    assert discovered.candidates[0].account_receivable_id is None
    verified = await data.verify_payment_candidate(
        VerifyCandidateQuery(order_id=UUID(int=4), address=hint)
    )
    assert verified.candidates[0].verified
    assert verified.candidates[0].account_receivable_id is None
    assert verified.candidates[0].outstanding_amount is None
    assert verified.limitations


class _Context:
    def __init__(self, value: object = None) -> None:
        self.value = value

    async def __aenter__(self) -> object:
        return self.value

    async def __aexit__(self, *args: object) -> None:
        del args


class _RetryConnection:
    def __init__(self) -> None:
        self.attempts = 0

    def transaction(self, *, readonly: bool) -> _Context:
        assert readonly is True
        return _Context()

    async def fetch(self, query: str, *args: object) -> list[dict[str, object]]:
        del query, args
        self.attempts += 1
        if self.attempts < 3:
            raise asyncpg.SerializationError("canceling statement due to conflict with recovery")
        return [{"candidate": "Alberto Amigo"}]


class _RetryPool:
    def __init__(self, connection: _RetryConnection) -> None:
        self.connection = connection

    def acquire(self) -> _Context:
        return _Context(self.connection)


async def test_replica_serialization_conflict_retries_with_fresh_transactions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    delays: list[float] = []

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    database = ReplicaDatabase(AppConfig(), load_knowledge(KNOWLEDGE_DIR))
    connection = _RetryConnection()
    database.pool = cast(Any, _RetryPool(connection))

    result = await database.fetch_bounded("SELECT 1")

    assert connection.attempts == 3
    assert delays == [0.1, 0.2]
    assert result.rows == ({"candidate": "Alberto Amigo"},)


class _CandidateDatabase:
    def __init__(self, row_overrides: dict[str, object] | None = None) -> None:
        self.query = ""
        self.args: tuple[object, ...] = ()
        self.row_overrides = row_overrides or {}

    async def fetch_bounded(
        self, query: str, *args: object, max_rows: int | None = None
    ) -> QueryResult:
        assert max_rows == 20
        if not self.query:
            self.query = query
            self.args = args
        row = {
            "customer_name": "Alberto Amigo",
            "customer_rut": None,
            "customer_email": "alberto@example.test",
            "customer_phone": "+56900000000",
            "signee_names": None,
            "signee_ruts": None,
            "signee_phones": None,
            "signee_emails": None,
            "order_id": UUID("b8970770-6468-4d8c-bd52-5abbd954020e"),
            "order_number": 129182,
            "account_receivable_id": UUID("56d87140-8e97-4f78-975d-0c516471f3c9"),
            "account_receivable_type": "cash",
            "account_receivable_amount": Decimal("4760000"),
            "currency": "CLP",
            "outstanding_amount": Decimal("1428000"),
            "installment_summary": "Después de instalación 30.0%",
            "full_address": "Otra Calle 123 Santiago",
            "legacy_bank_name": None,
            "legacy_bank_rut": None,
            "legacy_bank_account": None,
            "normalized_bank_name": None,
            "normalized_bank_rut": None,
            "normalized_bank_account": None,
        }
        row.update(self.row_overrides)
        return QueryResult(tuple(row), (row,), 1, False)


class _IdentityFallbackDatabase(_CandidateDatabase):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    async def fetch_bounded(
        self, query: str, *args: object, max_rows: int | None = None
    ) -> QueryResult:
        self.calls += 1
        if self.calls == 1:
            self.row_overrides = {"customer_name": "Felipe Ruiz"}
            return await super().fetch_bounded(query, *args, max_rows=max_rows)
        assert max_rows == 20
        row = {
            "customer_name": "Claudio Montecinos",
            "customer_rut": None,
            "customer_email": "claudio@example.test",
            "customer_phone": "+56911112222",
            "signee_names": "Claudio Felipe Montecinos Muñoz",
            "signee_ruts": None,
            "signee_phones": None,
            "signee_emails": None,
            "identity_names": "Claudio Montecinos | Claudio Felipe Montecinos Muñoz",
            "order_id": UUID("b8970770-6468-4d8c-bd52-5abbd954020e"),
            "order_number": 129182,
            "full_address": "Otra Calle 123 Santiago",
        }
        return QueryResult(tuple(row), (row,), 1, False)


async def test_candidate_search_stages_enrichment_and_uses_name_tokens_from_glosa() -> None:
    database = _CandidateDatabase()
    knowledge = load_knowledge(KNOWLEDGE_DIR)
    data = ReplicaInvestigationData(cast(ReplicaDatabase, database), knowledge, KNOWLEDGE_DIR)

    observation = await data.search_payment_candidates(
        PaymentCandidateQuery(
            glosa_or_address="Amigo instalacion",
            amount=Decimal("1428000"),
            currency="CLP",
        )
    )

    assert "matched AS" in database.query
    assert "LIMIT 21" in database.query
    assert "payment_aggregates" not in database.query
    assert ["amigo"] in database.args
    assert observation.candidates[0].customer_name == "Alberto Amigo"
    assert observation.candidates[0].evidence[0].kind is EvidenceKind.NAME_FRAGMENT
    assert any(
        evidence.kind is EvidenceKind.EXACT_OUTSTANDING
        for evidence in observation.candidates[0].evidence
    )


async def test_partial_amount_is_supporting_and_amount_only_search_stays_exact() -> None:
    database = _CandidateDatabase()
    knowledge = load_knowledge(KNOWLEDGE_DIR)
    data = ReplicaInvestigationData(cast(ReplicaDatabase, database), knowledge, KNOWLEDGE_DIR)

    observation = await data.search_payment_candidates(
        PaymentCandidateQuery(
            transferor_name="Alberto Amigo",
            amount=Decimal("500000"),
            currency="CLP",
        )
    )

    kinds = {item.kind for item in observation.candidates[0].evidence}
    assert EvidenceKind.CUSTOMER_NAME in kinds
    assert EvidenceKind.PARTIAL_PAYMENT in kinds
    assert EvidenceKind.AMOUNT_EXCEEDS_OUTSTANDING not in kinds
    assert "outstanding_amount =" in database.query
    assert "outstanding_amount >" not in database.query


async def test_long_transferor_name_matches_shorter_customer_identity() -> None:
    database = _CandidateDatabase({"customer_name": "Claudio Montecinos"})
    data = ReplicaInvestigationData(
        cast(ReplicaDatabase, database), load_knowledge(KNOWLEDGE_DIR), KNOWLEDGE_DIR
    )

    observation = await data.search_payment_candidates(
        PaymentCandidateQuery(transferor_name="Claudio Felipe Montecinos Muñoz")
    )

    kinds = {item.kind for item in observation.candidates[0].evidence}
    assert EvidenceKind.CUSTOMER_NAME in kinds
    assert EvidenceKind.IDENTITY_CONFLICT not in kinds
    assert "COUNT(DISTINCT token.value)" in database.query


async def test_transferor_can_match_a_contract_signee() -> None:
    database = _CandidateDatabase(
        {"signee_names": "Claudio Felipe Montecinos Muñoz | Otra Persona"}
    )
    data = ReplicaInvestigationData(
        cast(ReplicaDatabase, database), load_knowledge(KNOWLEDGE_DIR), KNOWLEDGE_DIR
    )

    observation = await data.search_payment_candidates(
        PaymentCandidateQuery(transferor_name="Claudio Montecinos")
    )

    kinds = {item.kind for item in observation.candidates[0].evidence}
    assert EvidenceKind.SIGNEE_NAME in kinds
    assert EvidenceKind.IDENTITY_CONFLICT not in kinds


async def test_identity_fallback_discards_one_token_noise_without_requiring_open_ar() -> None:
    database = _IdentityFallbackDatabase()
    data = ReplicaInvestigationData(
        cast(ReplicaDatabase, database), load_knowledge(KNOWLEDGE_DIR), KNOWLEDGE_DIR
    )

    observation = await data.search_payment_candidates(
        PaymentCandidateQuery(transferor_name="Claudio Felipe Montecinos Muñoz")
    )

    assert database.calls == 2
    assert [item.customer_name for item in observation.candidates] == ["Claudio Montecinos"]
    assert observation.candidates[0].account_receivable_id is None
    assert EvidenceKind.CUSTOMER_NAME in {
        signal.kind for signal in observation.candidates[0].evidence
    }


@pytest.mark.parametrize(
    ("amount", "currency", "expected"),
    [
        (Decimal("1500000"), "CLP", EvidenceKind.AMOUNT_EXCEEDS_OUTSTANDING),
        (Decimal("1428000"), "CLF", EvidenceKind.CURRENCY_MISMATCH),
    ],
)
async def test_overpayment_and_currency_mismatch_are_contradictions(
    amount: Decimal, currency: str, expected: EvidenceKind
) -> None:
    database = _CandidateDatabase()
    data = ReplicaInvestigationData(
        cast(ReplicaDatabase, database), load_knowledge(KNOWLEDGE_DIR), KNOWLEDGE_DIR
    )

    observation = await data.search_payment_candidates(
        PaymentCandidateQuery(
            transferor_name="Alberto Amigo",
            amount=amount,
            currency=cast(Any, currency),
        )
    )

    contradictions = {
        item.kind
        for item in observation.candidates[0].evidence
        if item.polarity.value == "contradicting"
    }
    assert expected in contradictions
