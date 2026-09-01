# Current state

Last updated: 2026-09-01.

## Completed: Phase 0 through Slice 3 replica investigation

- Independent Python 3.13/`uv` project.
- FastAPI health endpoint.
- PostgreSQL and Alembic foundation schema.
- Procrastinate worker skeleton.
- Structured payment-identification result and harness-independent runner protocol.
- Deterministic fake runner for vertical-slice development.
- Capability registry with future business writes visibly planned but disabled.
- Safe default mode (`off`), disabled payment/hold switches, configurable turn/tool/image/SQL
  budgets, and disabled external tracing.
- Container, Compose, GHCR CI/deploy, VM update/backup skeleton.
- Additive Slack manifest events for private-channel thread messages and reaction feedback.
- Product/engineering/operations wiki and configurable data-scope knowledge.
- Async Slack Socket Mode process using the existing app.
- Durable, idempotent event → conversation/message → run → outbox processing.
- Public/private installed-channel mentions and human follow-ups in known threads.
- Native investigation status and same-thread fake Spanish responses in `review`/`apply`.
- Safe image metadata validation; no URL retention, byte download, or `image_paths` yet.
- `off`, `shadow`, `review`, and pre-write `apply` mode gates.
- 🧀/🔌 feedback, removal, and idempotent in-thread pain response.
- Periodic recovery for event/run/output commit-to-enqueue gaps.
- Azure OpenAI v1 adapter behind `AgentRunner`, using the Agents SDK and Responses by default.
- Automatic real/fake runner selection with startup rejection of partial Azure credentials.
- Structured model output, server-owned CRM URLs, and unsupported-candidate rejection.
- Versioned production prompt and knowledge revision recorded on every real run.
- Six typed read-only tools for FinOps knowledge, schema, candidates, verification, Vambe,
  and long-tail SQL.
- Dedicated asyncpg replica pool with read-only session settings, non-dangerous-role and
  physical-replica verification, SSL enforcement outside local/test, and schema drift checks.
- SQLGlot AST validation with one-statement, relation/function allowlists and rejection of
  writes, locks, catalogs, recursive CTEs, table functions, Cartesian joins, and projections
  using `SELECT *`.
- Deterministic outstanding balance using active same-currency payments and losses; candidate
  filtering excludes cancelled, fully paid, non-client, and non-Ruuf receivables.
- Candidate-scoped Vambe lookup with 30-day default, 90-day maximum, and no attachment bytes.
- Server-enforced final verification: discovery or raw SQL cannot authorize a recommendation.
- Safe SQL/tool auditing by fingerprint, relations, timing, row count, truncation, and bounded
  summaries; raw SQL, PII, and reasoning are not audit payloads.
- Synthetic schema-compatible replica profile and opt-in end-to-end data integration test.
- Configurable 8-turn, 20-tool, 180-second, and 4,096-output-token budgets.
- Safe `unknown` outcomes for timeout, budget, refusal, and invalid structured output.
- Durable bounded tool-call audit records without chain-of-thought.
- Six-case synthetic eval corpus and opt-in Azure eval runner.

## Not connected

- Screenshot download/validation/temporary cleanup.
- PostHog emission and launch dashboards.
- Any automatic bank trigger.
- Any monolith write API.

## Next slice

Slice 4 downloads and validates Slack screenshots into short-lived files and supplies them
as multimodal model input. Until then, screenshot metadata is visible but image bytes are
not investigated. Live Azure + production-replica acceptance remains pending on credentials
and platform access; the complete data path is validated against the synthetic replica.

## Known facts from the reference systems

- Wattson establishes the current baseline: Python 3.13, FastAPI, PostgreSQL/Alembic,
  Procrastinate, OpenAI Agents SDK on Azure, PostHog, GHCR, and Docker Compose on the VM.
- Melocotón proves the Slack Socket Mode/thread/reaction and temporary-image patterns and
  uses read-only SQL with a database read-only transaction, 15-second timeout, and 200-row
  ceiling.
- The monolith has `vambe_message` text/context but does not persist a general attachment
  URL from the received-message DTO.
- `pagos@ruuf.solar` is the code convention, but no generic searchable payment mailbox
  exists yet.
- Currency is `CLP`, `USD`, or `CLF`; normal AR creation defaults to CLP.
- The verified CRM route is `/account-receivables/crm-finops/{orderId}`.

## Definition of V0 done

From a real Slack mention containing text and/or screenshots, Cerebro autonomously searches
real monolith data and responds in the same thread with at least a useful, auditable
customer-identification investigation. No business data is written.
