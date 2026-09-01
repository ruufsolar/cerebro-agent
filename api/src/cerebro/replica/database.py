import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from urllib.parse import parse_qs, urlparse
from uuid import UUID

import asyncpg

from cerebro.config import AppConfig
from cerebro.replica.scope import KnowledgeBundle
from cerebro.replica.sql_policy import ValidatedSql


class ReplicaConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True)
class QueryResult:
    columns: tuple[str, ...]
    rows: tuple[dict[str, Any], ...]
    row_count: int
    truncated: bool


@dataclass(frozen=True)
class SchemaDrift:
    missing_relations: tuple[str, ...] = ()
    missing_columns: tuple[str, ...] = ()
    incompatible_types: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not (self.missing_relations or self.missing_columns or self.incompatible_types)


def _safe_json_value(value: Any) -> Any:
    if value is None or isinstance(value, bool | int | float | str):
        return value[:2_000] if isinstance(value, str) else value
    if isinstance(value, Decimal | UUID | date | datetime):
        return str(value)
    if isinstance(value, bytes):
        return f"[binary value omitted: {len(value)} bytes]"
    return str(value)[:2_000]


class ReplicaDatabase:
    def __init__(self, config: AppConfig, knowledge: KnowledgeBundle) -> None:
        self.config = config
        self.knowledge = knowledge
        self.pool: asyncpg.Pool | None = None

    def _validate_dsn(self) -> None:
        if not self.config.read_replica_url:
            raise ReplicaConfigurationError("CEREBRO_READ_REPLICA_URL is required")
        if self.config.read_replica_url.rstrip("/") == self.config.database_url.rstrip("/"):
            raise ReplicaConfigurationError("replica DSN must differ from Cerebro's database DSN")
        parsed = urlparse(self.config.read_replica_url)
        if parsed.scheme not in {"postgres", "postgresql"} or not parsed.hostname:
            raise ReplicaConfigurationError("replica DSN must be a PostgreSQL URL")
        if self.config.environment not in {"local", "test"}:
            sslmode = parse_qs(parsed.query).get("sslmode", [""])[0]
            if sslmode not in {"require", "verify-ca", "verify-full"}:
                raise ReplicaConfigurationError("non-local replica connections must require SSL")

    async def start(self) -> None:
        if self.pool is not None:
            return
        self._validate_dsn()
        limits = self.knowledge.scope.query_limits

        async def initialize(connection: asyncpg.Connection) -> None:
            await connection.execute("SET default_transaction_read_only = on")
            timeout = limits.statement_timeout_seconds
            await connection.execute(f"SET statement_timeout = '{timeout}s'")
            await connection.execute("SET lock_timeout = '3s'")
            await connection.execute("SET idle_in_transaction_session_timeout = '20s'")
            await connection.execute("SET application_name = 'cerebro-agent'")

        self.pool = await asyncpg.create_pool(
            dsn=self.config.read_replica_url,
            min_size=1,
            max_size=min(self.config.sql_max_connections, limits.max_connections),
            command_timeout=float(limits.statement_timeout_seconds + 2),
            init=initialize,
        )
        try:
            await self.verify_safety()
            drift = await self.check_schema()
            if not drift.ok:
                raise ReplicaConfigurationError(
                    "replica schema does not match the configured scope: "
                    f"missing relations={list(drift.missing_relations)}, "
                    f"missing columns={list(drift.missing_columns)}, "
                    f"incompatible types={list(drift.incompatible_types)}"
                )
        except Exception:
            await self.close()
            raise

    async def close(self) -> None:
        pool, self.pool = self.pool, None
        if pool is not None:
            await pool.close()

    def _require_pool(self) -> asyncpg.Pool:
        if self.pool is None:
            raise ReplicaConfigurationError("replica pool has not been started")
        return self.pool

    async def verify_safety(self) -> None:
        pool = self._require_pool()
        async with pool.acquire() as connection:
            settings = await connection.fetchrow(
                """
                SELECT current_setting('transaction_read_only') AS read_only,
                       pg_is_in_recovery() AS in_recovery,
                       r.rolsuper, r.rolcreaterole, r.rolcreatedb,
                       r.rolreplication, r.rolbypassrls
                FROM pg_roles r WHERE r.rolname = current_user
                """
            )
            if settings is None or settings["read_only"] != "on":
                raise ReplicaConfigurationError("replica session is not read-only")
            dangerous = (
                "rolsuper",
                "rolcreaterole",
                "rolcreatedb",
                "rolreplication",
                "rolbypassrls",
            )
            if any(bool(settings[name]) for name in dangerous):
                raise ReplicaConfigurationError("replica role has dangerous PostgreSQL privileges")
            if not settings["in_recovery"] and not (
                self.config.environment in {"local", "test"}
                and self.config.allow_non_replica_readonly_db
            ):
                raise ReplicaConfigurationError("database is not a physical read replica")
            for relation in sorted(self.knowledge.scope.relation_names):
                writable = await connection.fetchval(
                    """
                    SELECT has_table_privilege(
                               current_user,
                               to_regclass(format('%I.%I', 'public', $1::text)),
                               'INSERT'
                           )
                        OR has_table_privilege(
                               current_user,
                               to_regclass(format('%I.%I', 'public', $1::text)),
                               'UPDATE'
                           )
                        OR has_table_privilege(
                               current_user,
                               to_regclass(format('%I.%I', 'public', $1::text)),
                               'DELETE'
                           )
                        OR has_table_privilege(
                               current_user,
                               to_regclass(format('%I.%I', 'public', $1::text)),
                               'TRUNCATE'
                           )
                    """,
                    relation,
                )
                if writable:
                    raise ReplicaConfigurationError(f"replica role can write relation {relation}")

    async def check_schema(self) -> SchemaDrift:
        pool = self._require_pool()
        async with pool.acquire() as connection:
            rows = await connection.fetch(
                """
                SELECT table_name, column_name, data_type
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = ANY($1::text[])
                """,
                sorted(self.knowledge.scope.relation_names),
            )
        actual: dict[str, dict[str, str]] = {}
        for row in rows:
            actual.setdefault(row["table_name"], {})[row["column_name"]] = row["data_type"]
        missing_relations: list[str] = []
        missing_columns: list[str] = []
        incompatible: list[str] = []
        aliases = {
            "varchar": {"character varying", "text"},
            "timestamp": {"timestamp without time zone", "timestamp with time zone"},
            "numeric": {"numeric", "decimal"},
            "enum": {"USER-DEFINED", "text", "character varying"},
        }
        for name, schema in self.knowledge.catalog.relations.items():
            if name not in actual:
                missing_relations.append(name)
                continue
            for column, expected in schema.columns.items():
                observed = actual[name].get(column)
                alias_mismatch = expected in aliases and observed not in aliases[expected]
                direct_mismatch = expected not in aliases and observed != expected
                if observed is None:
                    missing_columns.append(f"{name}.{column}")
                elif alias_mismatch or direct_mismatch:
                    incompatible.append(f"{name}.{column}:{observed}!={expected}")
        return SchemaDrift(
            tuple(sorted(missing_relations)),
            tuple(sorted(missing_columns)),
            tuple(sorted(incompatible)),
        )

    async def run_validated(self, sql: ValidatedSql) -> QueryResult:
        return await self.fetch_bounded(sql.normalized_sql)

    async def fetch_bounded(
        self,
        query: str,
        *args: Any,
        max_rows: int | None = None,
    ) -> QueryResult:
        pool = self._require_pool()
        configured_rows = min(
            max_rows or self.config.sql_max_rows,
            self.config.sql_max_rows,
            self.knowledge.scope.query_limits.max_rows,
        )
        inner = query.rstrip(";")
        fetch_limit = configured_rows + 1
        wrapped = f"SELECT * FROM ({inner}) AS cerebro_bounded_query LIMIT {fetch_limit}"
        async with pool.acquire() as connection, connection.transaction(readonly=True):
            records = await connection.fetch(wrapped, *args)
        truncated = len(records) > configured_rows
        records = records[:configured_rows]
        columns = tuple(records[0].keys()) if records else ()
        safe_rows: list[dict[str, Any]] = []
        byte_limit = min(
            self.config.sql_max_output_bytes,
            self.knowledge.scope.query_limits.max_output_bytes,
        )
        for record in records:
            row = {key: _safe_json_value(value) for key, value in record.items()}
            candidate = [*safe_rows, row]
            if len(json.dumps(candidate, ensure_ascii=False, default=str).encode()) > byte_limit:
                truncated = True
                break
            safe_rows.append(row)
        return QueryResult(columns, tuple(safe_rows), len(safe_rows), truncated)
