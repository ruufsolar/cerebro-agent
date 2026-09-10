import os
from collections.abc import AsyncIterator
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest

from cerebro.agent.data_tools import (
    ReadonlySqlQuery,
    RecordKey,
    SchemaQuery,
    SchemaSearchQuery,
    SourceLink,
    SourceRecordQuery,
    VerifyCandidateQuery,
)
from cerebro.agent.openai_runner import RunState
from cerebro.config import AppConfig
from cerebro.replica.database import ReplicaDatabase
from cerebro.replica.investigation import ReplicaInvestigationData
from cerebro.replica.scope import load_knowledge
from cerebro.replica.sql_policy import SqlPolicyError, validate_readonly_sql

KNOWLEDGE = Path(__file__).parents[2] / "knowledge"
ORDER = UUID("50000000-0000-0000-0000-000000000001")
SOURCE = "13000000-0000-0000-0000-000000000001"


@pytest.fixture
async def data() -> AsyncIterator[ReplicaInvestigationData]:
    url = os.environ.get("CEREBRO_TEST_REPLICA_URL")
    if not url:
        pytest.skip("requires the disposable synthetic replica")
    config = AppConfig(
        environment="test",
        read_replica_url=url,
        allow_non_replica_readonly_db=True,
        knowledge_dir=str(KNOWLEDGE),
    )
    knowledge = load_knowledge(KNOWLEDGE)
    backend = ReplicaInvestigationData(ReplicaDatabase(config, knowledge), knowledge, KNOWLEDGE)
    await backend.start()
    try:
        yield backend
    finally:
        await backend.close()


def test_dynamic_schema_policy_does_not_use_the_curated_subset() -> None:
    scope = load_knowledge(KNOWLEDGE).scope
    sql = validate_readonly_sql(
        "SELECT id FROM ops.payer_reference", scope, readable_relations={("ops", "payer_reference")}
    )
    assert sql.relations == ("ops.payer_reference",)
    with pytest.raises(SqlPolicyError):
        validate_readonly_sql("SELECT id FROM account_receivable", scope, readable_relations=set())
    with pytest.raises(SqlPolicyError):
        validate_readonly_sql(
            "SELECT rolname FROM pg_catalog.pg_roles",
            scope,
            readable_relations={("pg_catalog", "pg_roles")},
        )


async def test_discovery_descriptions_grants_views_and_paging(
    data: ReplicaInvestigationData,
) -> None:
    found = await data.search_database_schema(SchemaSearchQuery(query="payer", limit=1))
    assert found.available and len(found.rows) == 1 and found.audit.truncated
    following = await data.search_database_schema(SchemaSearchQuery(query="payer", offset=1))
    assert following.rows[0]["name"] != found.rows[0]["name"]
    described = await data.describe_database_tables(SchemaQuery(names=["ops.payer_reference"]))
    assert described.rows[0]["primary_key"] == ["id"]
    columns = described.rows[0]["columns"]
    assert isinstance(columns, dict) and "fullName" in columns
    relationships = await data.inspect_database_relationships(
        SchemaQuery(names=["ops.payer_reference"])
    )
    assert relationships.rows[0]["identifier"] == "ops.payer_reference.payer_order_fk"
    catalog = await data.database.catalog()
    assert ("ops", "unreadable") not in catalog.relations
    assert ("ops", "payer_view") in catalog.relations
    denied = await data.run_readonly_sql(ReadonlySqlQuery(query="SELECT id FROM ops.unreadable"))
    assert not denied.available
    page = await data.run_readonly_sql(
        ReadonlySqlQuery(query="SELECT id FROM ops.payer_view", offset=1)
    )
    assert page.rows == []


@pytest.mark.parametrize(
    "name, path, verified",
    [
        ("Emilia Pinto Vega", ["ops.payer_reference.payer_order_fk"], True),
        ("Invented Customer", ["ops.payer_reference.payer_order_fk"], False),
        ("Emilia Pinto Vega", ["ops.payer_reference.invented_join"], False),
        ("Emilia Pinto Vega", [], False),
    ],
)
async def test_exploratory_evidence_rereads_records_not_sql_literals(
    data: ReplicaInvestigationData,
    name: str,
    path: list[str],
    verified: bool,
) -> None:
    state = RunState()
    request = ReadonlySqlQuery(
        query="SELECT id, 'Invented Customer' AS name FROM ops.payer_reference",
        source_records=[
            SourceRecordQuery(
                relation="ops.payer_reference", keys=[RecordKey(column="id", value=SOURCE)]
            )
        ],
    )
    await state.invoke("run_readonly_sql", request, data.run_readonly_sql)
    assert set(state.source_records) == {"src_001"}
    check = VerifyCandidateQuery(
        order_id=ORDER,
        amount=Decimal("700000"),
        currency="CLP",
        transferor_name=name,
        source_links=[SourceLink(reference="src_001", relationship_path=path)],
    )
    await state.invoke(
        "verify_payment_candidate",
        check,
        lambda q: data.verify_payment_sources(q, list(state.source_records.values())),
    )
    sources = [signal for signal in state.evidence.values() if signal.source_reference]
    assert bool(sources) is verified
    if verified:
        assert sources[0].source_reference == "src_001"
        assert sources[0].strength == "weak"  # relationship is not proof of payer identity
    serialized_audit = str(state.calls)
    assert name not in serialized_audit and SOURCE not in serialized_audit
    assert "Invented Customer" not in serialized_audit


async def test_fabricated_source_primary_key_has_no_reference(
    data: ReplicaInvestigationData,
) -> None:
    result = await data.run_readonly_sql(
        ReadonlySqlQuery(
            query="SELECT id FROM ops.payer_reference",
            source_records=[
                SourceRecordQuery(
                    relation="ops.payer_reference",
                    keys=[RecordKey(column="id", value=str(UUID(int=0)))],
                )
            ],
        )
    )
    assert result.available and result.source_records == []


async def test_stale_memory_relation_stays_unavailable(data: ReplicaInvestigationData) -> None:
    described = await data.describe_database_tables(SchemaQuery(names=["ops.old_payer_table"]))
    assert described.rows == [] and described.limitations
    query = await data.run_readonly_sql(
        ReadonlySqlQuery(query="SELECT id FROM ops.old_payer_table")
    )
    assert not query.available and not query.candidates


async def test_long_sql_value_explicitly_reports_truncation(data: ReplicaInvestigationData) -> None:
    result = await data.database.fetch_bounded("SELECT repeat('a', 2100) AS long_value")
    assert result.truncated
    assert len(result.rows[0]["long_value"]) == 2000
