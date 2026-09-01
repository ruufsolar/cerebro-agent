import os
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest

from cerebro.agent.data_tools import (
    PaymentCandidateQuery,
    ReadonlySqlQuery,
    VambeQuery,
    VerifyCandidateQuery,
)
from cerebro.config import AppConfig
from cerebro.replica.database import ReplicaDatabase
from cerebro.replica.investigation import ReplicaInvestigationData
from cerebro.replica.scope import load_knowledge

KNOWLEDGE_DIR = Path(__file__).parents[2] / "knowledge"
ORDER_ID = UUID("50000000-0000-0000-0000-000000000001")
RECEIVABLE_ID = UUID("a0000000-0000-0000-0000-000000000001")


@pytest.mark.integration
async def test_synthetic_replica_supports_the_complete_readonly_investigation() -> None:
    replica_url = os.environ.get("CEREBRO_TEST_REPLICA_URL")
    if not replica_url:
        pytest.skip("requires the opt-in synthetic replica profile")
    config = AppConfig(
        environment="test",
        database_url="postgresql://cerebro@example.invalid/cerebro",
        read_replica_url=replica_url,
        allow_non_replica_readonly_db=True,
        knowledge_dir=str(KNOWLEDGE_DIR),
    )
    knowledge = load_knowledge(KNOWLEDGE_DIR)
    data = ReplicaInvestigationData(
        ReplicaDatabase(config, knowledge),
        knowledge,
        KNOWLEDGE_DIR,
    )

    await data.start()
    try:
        candidates = await data.search_payment_candidates(
            PaymentCandidateQuery(
                glosa_or_address="Los Paneles 123",
                amount=Decimal("700000"),
                currency="CLP",
            )
        )
        assert candidates.available is True
        assert candidates.audit.row_count == 1
        assert candidates.candidates[0].order_id == ORDER_ID
        assert candidates.candidates[0].verified is False
        assert candidates.candidates[0].outstanding_amount == Decimal("700000")

        verified = await data.verify_payment_candidate(
            VerifyCandidateQuery(
                order_id=ORDER_ID,
                account_receivable_id=RECEIVABLE_ID,
                amount=Decimal("700000"),
                currency="CLP",
                address="Los Paneles 123",
            )
        )
        assert verified.candidates[0].verified is True
        assert verified.candidates[0].account_receivable_id == RECEIVABLE_ID
        assert "saldo pendiente 700000" in str(verified.candidates[0].account_receivable_summary)

        vambe = await data.search_vambe_messages(VambeQuery(order_id=ORDER_ID, query="comprobante"))
        assert vambe.available is True
        assert vambe.audit.row_count == 1
        assert "700000" in str(vambe.rows[0]["content"])

        raw = await data.run_readonly_sql(
            ReadonlySqlQuery(
                query=(
                    "SELECT id, amount, currency FROM account_receivable "
                    f"WHERE id = '{RECEIVABLE_ID}'::uuid"
                )
            )
        )
        assert raw.available is True
        assert raw.audit.row_count == 1
        assert raw.audit.referenced_relations == ["account_receivable"]
        assert raw.audit.query_fingerprint is not None
    finally:
        await data.close()
