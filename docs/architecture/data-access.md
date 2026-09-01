# Data access

## Decision

Cerebro will use a dedicated monolith read replica with a dedicated PostgreSQL role. The
agent gets both deterministic tools and a free-form read-only SQL tool. This follows
Melocotón's ability to investigate unstructured questions while adding stronger structural
controls and auditing.

## Why not only fixed APIs

Fixed read APIs offer narrow contracts, smaller payloads, independent schema evolution,
and easy authorization. They are best for high-frequency/stable facts and all writes.
However, payment identification is exploratory: names, addresses, balances, bookings, and
conversation context combine differently case by case. Shipping a monolith API for every
new read path would slow learning and turn Cerebro into a rigid decision service.

## Why not unrestricted SQL

Database-level read-only permissions prevent mutations but do not prevent expensive joins,
PII overcollection, accidental schema coupling, or hallucinated columns. A string-prefix
check alone is insufficient.

## Layered controls

1. Connect only to the replica with a role that cannot write.
2. Set `default_transaction_read_only=on` at role/session level.
3. Allow one SQL statement beginning with `SELECT` or `WITH`; parse/reject DDL, DML,
   procedures, locking clauses, multiple statements, and catalog escape paths.
4. Expose only allowlisted tables/views from `knowledge/data-scope.yaml`.
5. Apply a 15-second statement timeout, 200-row default/ceiling, bounded connection pool,
   and configured maximum tool calls.
6. Prefer purpose-built tools for schema description, Vambe search, candidate search, and
   candidate verification; use raw SQL for the long tail.
7. Return column names plus bounded rows; redact/truncate large values before the model.
8. Audit normalized SQL fingerprint, referenced relations, duration, row count, and errors.
9. Never place a primary/writer DSN in Cerebro configuration.

The initial PII scope includes RUT, bank account, phone, email, and address because each can
be material identification evidence. It remains internal to FinOps and must not be emitted
to PostHog or logs. Slack answers should use the minimum evidence necessary.

## Implemented tools

- `read_finops_knowledge(topic)`
- `describe_database_tables(names)`
- `search_payment_candidates(glosa, transferor, amount, currency, date)`
- `search_vambe_messages(query, phone?, order_id?, date_range?)`
- `verify_payment_candidate(order_id, amount, transferor?, address?)`
- `run_readonly_sql(query)`

The first four heuristics stay in prompt/knowledge policy, while calculations such as
outstanding balance should be deterministic SQL/tool output.

The raw SQL validator uses SQLGlot's PostgreSQL AST, not a prefix/regular-expression check.
It accepts only one query, resolves CTEs separately from physical relations, allowlists
relations and functions, and rejects wildcard projections, writes, row locks, catalogs,
recursive CTEs, table functions, and Cartesian joins. The database then wraps the query in
a row limit and executes it inside a read-only transaction.

## Schema evolution

Treat the replica schema as an external dependency. Each allowed table has a reason in
`knowledge/data-scope.yaml` and required columns in `knowledge/database-schema.yaml`.
Worker startup validates both against the connected replica; a missing/incompatible column
fails startup explicitly. The synthetic Compose profile exercises the same checks. Stable,
frequently used queries should graduate into monolith read APIs or read views.
