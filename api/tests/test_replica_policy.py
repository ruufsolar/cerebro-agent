from pathlib import Path

import pytest

from cerebro.replica.scope import load_knowledge
from cerebro.replica.sql_policy import SqlPolicyError, validate_readonly_sql

KNOWLEDGE_DIR = Path(__file__).parents[2] / "knowledge"


def test_knowledge_scope_and_catalog_are_versioned_and_complete() -> None:
    knowledge = load_knowledge(KNOWLEDGE_DIR)

    assert knowledge.scope.version == 2
    assert knowledge.catalog.version == 2
    assert knowledge.scope.relation_names == set(knowledge.catalog.relations)
    assert {
        "account_receivable",
        "account_receivable_payment",
        "bank_account",
        "chile_bank_account",
        "certification_user",
        "vambe_message",
    } <= knowledge.scope.relation_names


def test_readonly_policy_accepts_allowlisted_selects_and_safe_aggregates() -> None:
    scope = load_knowledge(KNOWLEDGE_DIR).scope

    result = validate_readonly_sql(
        """
        WITH open_items AS (
          SELECT id, amount FROM account_receivable WHERE amount > 0
        )
        SELECT COUNT(*), MAX(amount) FROM open_items
        """,
        scope,
    )

    assert result.relations == ("account_receivable",)
    assert len(result.fingerprint) == 64
    assert "COUNT(*)" in result.normalized_sql


@pytest.mark.parametrize(
    "query",
    [
        "UPDATE account_receivable SET amount = 0",
        "SELECT id FROM account_receivable; SELECT id FROM sale",
        "SELECT * FROM account_receivable",
        "SELECT account_receivable.* FROM account_receivable",
        "SELECT rolname FROM pg_roles",
        "SELECT secret FROM unreviewed_table",
        "SELECT value FROM generate_series(1, 10) AS value",
        "SELECT ar.id FROM account_receivable ar CROSS JOIN sale s",
        "SELECT pg_sleep(1) FROM account_receivable",
        "SELECT id FROM account_receivable FOR UPDATE",
        ("WITH locked AS (SELECT id FROM account_receivable FOR UPDATE) SELECT id FROM locked"),
        "WITH RECURSIVE values AS (SELECT 1 UNION ALL SELECT 2) SELECT 1",
    ],
)
def test_readonly_policy_rejects_unsafe_queries(query: str) -> None:
    scope = load_knowledge(KNOWLEDGE_DIR).scope

    with pytest.raises(SqlPolicyError):
        validate_readonly_sql(query, scope)


def test_readonly_policy_does_not_persist_raw_sql_in_audit_contract() -> None:
    scope = load_knowledge(KNOWLEDGE_DIR).scope
    query = "SELECT id, amount FROM account_receivable WHERE amount = 700000"

    result = validate_readonly_sql(query, scope)

    assert result.fingerprint
    assert result.relations == ("account_receivable",)
    assert query not in result.fingerprint
