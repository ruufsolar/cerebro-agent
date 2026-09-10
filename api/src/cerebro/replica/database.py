import asyncio
import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from time import monotonic
from typing import Any
from urllib.parse import parse_qs, urlparse
from uuid import UUID

import asyncpg

from cerebro.config import AppConfig
from cerebro.replica.catalog import LiveCatalog, load_catalog
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
        self._catalog: LiveCatalog | None = None
        self._catalog_at = 0.0

    async def catalog(self, *, refresh: bool = False) -> LiveCatalog:
        if refresh or self._catalog is None or monotonic() - self._catalog_at > 60:
            async with self._require_pool().acquire() as connection:
                self._catalog = await load_catalog(connection)
                self._catalog_at = monotonic()
        return self._catalog

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
        self._catalog = None
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
            catalog = await load_catalog(connection)
            # Check the whole visible schema without one network round trip per relation.
            if any(relation.writable for relation in catalog.relations.values()):
                raise ReplicaConfigurationError("replica role has application write privileges")

    async def check_schema(self) -> SchemaDrift:
        # Only the canonical CRM identity is mandatory. Curated helper dependencies
        # may drift without disabling unrelated exploratory/general reads.
        catalog = await self.catalog(refresh=True)
        order = catalog.relations.get(("public", "order"))
        if order is None:
            return SchemaDrift(missing_relations=("public.order",))
        if "id" not in order.columns:
            return SchemaDrift(missing_columns=("public.order.id",))
        if order.columns["id"] != "uuid":
            return SchemaDrift(incompatible_types=("public.order.id",))
        return SchemaDrift()

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
        records = None
        for attempt in range(3):
            try:
                async with pool.acquire() as connection, connection.transaction(readonly=True):
                    records = await connection.fetch(wrapped, *args)
                break
            except asyncpg.SerializationError:
                if attempt == 2:
                    raise
                # A physical standby may cancel a reader so WAL replay can remove row
                # versions. Retrying in a new transaction obtains a fresh snapshot.
                await asyncio.sleep(0.1 * (2**attempt))
        assert records is not None
        truncated = len(records) > configured_rows
        records = records[:configured_rows]
        columns = tuple(records[0].keys()) if records else ()
        safe_rows: list[dict[str, Any]] = []
        byte_limit = min(
            self.config.sql_max_output_bytes,
            self.knowledge.scope.query_limits.max_output_bytes,
        )
        for record in records:
            if any(isinstance(value, str) and len(value) > 2_000 for value in record.values()):
                truncated = True
            row = {key: _safe_json_value(value) for key, value in record.items()}
            candidate = [*safe_rows, row]
            if len(json.dumps(candidate, ensure_ascii=False, default=str).encode()) > byte_limit:
                truncated = True
                break
            safe_rows.append(row)
        return QueryResult(columns, tuple(safe_rows), len(safe_rows), truncated)
