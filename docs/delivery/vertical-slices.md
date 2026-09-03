# Independently mergeable vertical slices

Each slice ends in observable behavior, tests, updated wiki/current-state, and deploy safety.
Do not create all integrations in one branch.

## Phase 0 — foundation (implemented)

Service/package, configuration, health, durable schema, jobs, agent/capability contracts,
fakes, docs, CI, and deployment skeleton. No credentials or live integrations.

## Slice 1 — Slack shell with fake investigation (implemented)

- Socket Mode process using `xapp` + `xoxb` tokens.
- `app_mention`, known-thread `message.channels`/`message.groups`, and
  `reaction_added`/`reaction_removed`.
- Durable event idempotency, conversations/messages/runs/outbox.
- Native status while processing; one same-thread fake response.
- 🧀 positive feedback and one idempotent `Arrrrgghhh ⚡️☠️` response to 🔌.
- Safe file-metadata validation only; no download, live vision, model, or data.

Acceptance: a real installed-channel mention survives duplicate delivery and process restart,
answers once in-thread, and records feedback.

## Slice 2 — Agents SDK and Azure with fake tools (implemented)

- Concrete `AgentRunner` using OpenAI Agents SDK and Azure deployment.
- Responses API, structured `PaymentIdentification`, Spanish renderer.
- External SDK tracing disabled; configurable turns/tool calls/deadline.
- Fake knowledge/data tools and representative model eval cases.

Acceptance: real model reasoning produces contract-valid responses without real customer
data; budget exhaustion and unknown outcomes are explicit. Live Azure Responses acceptance
and the six-case synthetic tool evaluation passed with the approved credentials.

## Slice 3 — monolith replica and knowledge (implemented)

- Dedicated read-only replica pool/credential.
- Versioned `data-scope.yaml`, schema description, SQL AST/policy validation, read-only
  transaction, 15-second timeout, 200-row ceiling, and audit metadata.
- Curated AR candidate and outstanding-balance tools.
- Vambe text search and documented attachment limitation.
- Schema drift test/snapshot.

If stable facts cannot be read safely or efficiently, this slice includes independently
mergeable monolith PRs for new **read** APIs/views and corresponding domain documentation.
It does not include write APIs.

Acceptance: the synthetic replica proves role/schema checks, outstanding-balance search,
candidate verification, candidate-scoped Vambe, and allowlisted raw SQL. Production/staging
connection and FinOps case reconciliation remain rollout acceptance rather than code work.

## Slice 4 — screenshots (implemented)

- Slack-authorized file download with allowed MIME types, four-image/8 MiB limits, timeouts,
  isolated temporary storage, and guaranteed cleanup.
- Multimodal Agents SDK input.
- Partial fallback when an image is unsupported/unreadable.
- No PDFs.

Acceptance: real bank screenshots feed the model, files disappear after every success/error,
and logs/telemetry contain no bytes or OCR dump.

## Slice 5 — grounded payment identification (implemented; pilot pending)

- GPT-5.6 Luna default, production prompt/knowledge version, and heuristic precedence.
- Typed evidence ledger, application-owned confidence/prose, contradictions, ranked verified
  alternatives, and explicit matched/ambiguous/no-customer/out-of-scope outcomes.
- Normalized address discovery and safe partial-payment/currency semantics.
- Verified CRM URL and human-readable AR summary.
- Concise real end-to-end Slack → replica/Vambe → answer flow.
- Twenty-case synthetic release gate and ten-case controlled FinOps Slack pilot.

Acceptance: the Definition of V0 Done in `current-state.md`, core FinOps fixture suite, and
manual pilot sign-off.

## Slice 6A — V0 pilot hardening

- Split control/agent queues, runtime heartbeats, foundation/pilot readiness, and safe
  structured logs.
- Local preflight/status/pilot commands, watchdog warnings, manual retention procedure, and
  load/retry/deploy-interruption coverage.
- Hard ten-case quality, latency, and token gates with a documented rollback drill.
- PostHog and all external telemetry are deliberately excluded from V0.

Implemented in code on 2026-09-02. The real pilot, rollback exercise, and FinOps signoff are
still pending, so capability state remains preview.

## Slice 6B — Launch decision

- Have platform review and apply the dedicated Azure Terraform stack in mode `off`, then
  complete production preflight and the `last-good` rollback exercise.
- Run and review the ten-case FinOps pilot and the rollback drill.
- Convert failures and representative successes into anonymized fixtures.
- Promote payment identification only through explicit FinOps approval and a normal release.

## Later: actions and proactive flows

Define hold semantics first. Then add narrow monolith write APIs and approval records as
separate slices: propose → approve → idempotent apply → reconcile/repair. Bank ingestion
becomes the only proactive payment trigger and uses the same investigation core.
