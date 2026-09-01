# Current state

Last updated: 2026-08-31.

## Completed: Phase 0 foundation and Slice 1 Slack shell

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

## Not connected

- Screenshot download/validation/temporary cleanup.
- OpenAI Agents SDK and Azure provider adapter.
- Read-replica connection, SQL validator, or Vambe tools.
- Live FinOps response renderer and PostHog emission.
- Any automatic bank trigger.
- Any monolith write API.

## Next slice

Slice 2 connects the OpenAI Agents SDK to Azure with fake tools. The Slack shell remains
unchanged while the runner becomes a real, bounded model execution that still has no access
to customer data.

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
