# Agent instructions

## Before changing code

- Read `docs/README.md`, `docs/product/current-state.md`, and
  `docs/product/capability-matrix.md`.
- Read the ADRs relevant to the area you are changing. Architectural decisions must be
  changed by adding a superseding ADR, not by silently editing history.
- Read `knowledge/data-scope.yaml` before touching monolith data access.
- If a task also changes the monolith, read the monolith's own `AGENTS.md` first and keep
  the changes independently mergeable.

## Project invariants

- Cerebro is an independent Python service, not a decision module inside the monolith.
- V0 supports one task: identify an incoming payment from a Slack mention with text and/or
  images and answer in the same thread.
- The operational read replica is read-only. Never run DDL/DML, call stored procedures, or
  use it for future writes.
- Business writes (payment association and holds) are out of scope until a dedicated,
  approval-gated monolith API exists. Both hard switches default to false.
- Preserve uncertainty. The difficult first-transfer case can correctly end in “no sé”.
- Bank ingestion is the eventual source of truth and trigger; V0 Slack mentions are a
  temporary manual trigger.
- External model tracing with customer content stays disabled. Never log secrets, raw
  screenshots, or unrestricted query results.
- Keep `docs/product/current-state.md` and the capability matrix accurate in the same PR as
  a capability change.

## Development

- Python is 3.13, dependency management is `uv`, formatting/linting is Ruff, type checking
  is Pyright, and tests use pytest.
- Keep integrations behind small protocols and inject fakes in tests.
- New tools need explicit input/output models, budgets, audit records, and failure behavior.
- Schema changes require an Alembic migration.
- Add tests for behavior, idempotency, permissions, and negative/uncertain paths.
- Use the Graphite CLI (`gt`) for version-control operations. Trunk is `main`; PR titles and
  descriptions are in English. Do not submit, merge, or deploy unless the user asks.
- Do not commit `.env`, tokens, customer data, screenshots, database dumps, or production
  transcripts.
