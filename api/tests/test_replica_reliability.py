import asyncio
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import asyncpg
import pytest

from cerebro.agent.data_tools import PaymentCandidateQuery
from cerebro.agent.models import EvidenceKind
from cerebro.config import AppConfig
from cerebro.replica.database import QueryResult, ReplicaDatabase
from cerebro.replica.investigation import ReplicaInvestigationData
from cerebro.replica.scope import load_knowledge

KNOWLEDGE_DIR = Path(__file__).parents[2] / "knowledge"


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
    def __init__(self) -> None:
        self.query = ""
        self.args: tuple[object, ...] = ()

    async def fetch_bounded(
        self, query: str, *args: object, max_rows: int | None = None
    ) -> QueryResult:
        assert max_rows == 20
        self.query = query
        self.args = args
        row = {
            "customer_name": "Alberto Amigo",
            "customer_rut": None,
            "customer_email": "alberto@example.test",
            "customer_phone": "+56900000000",
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
    assert "LIMIT 20" in database.query
    assert "payment_aggregates" not in database.query
    assert ["amigo"] in database.args
    assert observation.candidates[0].customer_name == "Alberto Amigo"
    assert observation.candidates[0].evidence[0].kind is EvidenceKind.CUSTOMER_NAME
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
