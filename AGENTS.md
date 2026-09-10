# Agent instructions

## Before changing code

- Call `agents_for_paths` on the files you are about to touch, and `agent_brief cerebro`
  before you read the code: what ops taught Cerebro in Slack is in the shared store and
  not in this repository. `remember` what you work out when you are done — one thing per
  call, never a client's name, RUT, phone or email. `.claude/skills/agent-memory/SKILL.md`
  has the longer version; the tools need `RUUF_AGENTS_TOKEN` in your environment.
- Read `README.md`, `docs/product.md`, and the relevant topical guide.
- Read the ADRs relevant to the area you are changing. Architectural decisions must be
  changed by adding a superseding ADR, not by silently editing history.
- Read `knowledge/data-scope.yaml` before touching monolith data access.
- If a task also changes the monolith, read the monolith's own `AGENTS.md` first and keep
  the changes independently mergeable.

## Project invariants

- Cerebro is an independent Python service, not a decision module inside the monolith.
- V0 routes Slack mentions between grounded incoming-payment identification and bounded general
  FinOps conversation. Payment requests must never bypass the specialist evidence validator.
- The operational read replica is read-only. Never run DDL/DML, call stored procedures, or
  use it for future writes.
- Business writes (payment association and holds) are out of scope until a dedicated,
  approval-gated monolith API exists. No placeholder write switches or tools exist.
- Preserve uncertainty. The difficult first-transfer case can correctly end in “no sé”.
- Bank ingestion is the eventual source of truth and trigger; V0 Slack mentions are a
  temporary manual trigger.
- External model tracing with customer content stays disabled. Never log secrets, raw
  screenshots, or unrestricted query results.
- Keep `docs/product.md` accurate in the same PR as a capability change. Avoid duplicating
  current-state summaries in several guides. ADR-012 supersedes the old rollout modes.

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
