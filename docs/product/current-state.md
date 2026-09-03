# Current state

Last updated: 2026-09-03.

## Completed in code: Phase 0 through Slice 6A pilot hardening

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
- Safe image metadata validation with categorical accepted/rejected counts and no URL retention.
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
- Staged candidate retrieval, glosa-to-customer-name token evidence, and bounded retries for
  physical-replica recovery conflicts. Exhausted replica retries become an unavailable-source
  observation rather than a generic failed Slack run.
- Partial tool audits survive fatal model/provider failures and are persisted idempotently.
- Six-case synthetic eval corpus and opt-in Azure eval runner.
- Azure-compatible numeric tool schemas retain Decimal validation without unsupported JSON
  Schema regex, and the Slice 3 v2 prompt applies the documented confidence ceiling when
  no glosa/address evidence exists.
- Authenticated Slack screenshot retrieval for the triggering message only, using
  `files.info`, manually validated Slack HTTPS redirects, and streamed size enforcement.
- Static PNG/JPEG/WebP validation with MIME-signature agreement, animation/malformed-image
  rejection, an 8 MiB/four-file limit, and a configurable 25-megapixel ceiling.
- Per-run mode-`0700` temporary directories and mode-`0600` files with cleanup on every
  result path plus worker-start orphan sweeping.
- Base64 data-URL multimodal model input at `detail: high`; no OpenAI Files uploads, image
  persistence, external traces, historical-image replay, or image content in audits.
- Explicit partial-image fallback counts and a synthetic opt-in Azure vision evaluation.
- Azure main-deployment default changed to the deployment serving GPT-5.6 Luna; Responses,
  medium reasoning, vision, structured output, and existing runtime budgets remain unchanged.
- Four explicit outcomes: matched, ambiguous, no customer found, and out of scope.
- Opaque evidence IDs and a per-run evidence ledger. The model selects evidence, while
  application code validates the customer, evidence ownership, confidence, contradictions,
  ranking, CRM URL, account-receivable summary, and final Spanish prose.
- Normalized address matching, bounded noisy-glosa token discovery, and correct partial-payment
  semantics. Smaller same-currency amounts are not contradictions; overpayments and currency
  mismatches are.
- Concise outcome-specific Slack rendering with deterministic line and word budgets.
- A 20-case anonymized Slice 5 corpus with outcome, evidence, tool, safety, and verbosity graders
  plus an optional JSON gate report.
- Separate two-concurrency `control` and `agent` Procrastinate workers so long Azure runs do
  not block Slack ingestion, feedback, delivery, or recovery.
- Foundation/pilot readiness profiles with additive Slack/control/agent runtime heartbeats.
- Privacy-safe structured JSON/text logs that discard arbitrary messages, exception content,
  Slack payloads, customer data, SQL, screenshots, and private URLs.
- Local preflight, aggregate status, and anonymized ten-case pilot-gate commands.
- Five-minute aggregate watchdog warnings, 240-second drain/graceful-stop behavior, and a
  deployment readiness gate that preserves the `last-good` rollback path.
- Hard ten-case pilot gates for quality, screenshots, feedback, grounding, response length,
  end-to-end latency, and model-token usage.
- No PostHog dependency or external operational telemetry in V0. Agents SDK tracing remains
  disabled; ADR-008 records the local-only telemetry decision.
- A senior-reviewable Terraform production stack provisions a dedicated private Azure VM,
  explicit stable NAT egress, retained data disk, Key Vault/managed-identity secret delivery,
  and remote Entra-authenticated state. It has not been applied by this repository change;
  capability remains preview and production mode defaults to `off`.

## Deliberately not connected

- PostHog, external dashboards, and external alert sinks in V0.
- Any automatic bank trigger.
- Any monolith write API.

## Slice 5 acceptance status

- Live synthetic Luna gate: **passed 20/20 on 2026-09-02** with
  `payment-identification-slice5-v1`, `payment-identification-knowledge-v3`, and deployment
  `gpt-5-6-luna`; zero wrong high-confidence matches and zero unsupported claims.
- Pending: complete the ten-case controlled FinOps Slack pilot and obtain explicit FinOps
  signoff.

Until the Slack pilot passes, payment identification remains preview. Slice 6A's hardening
is implemented; running the real ten cases, recording aggregate results, completing the
rollback drill, and obtaining FinOps signoff remain manual release gates.

## Known facts from the reference systems

- Wattson establishes the current baseline: Python 3.13, FastAPI, PostgreSQL/Alembic,
  Procrastinate, OpenAI Agents SDK on Azure, GHCR, and Docker Compose on the VM.
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
