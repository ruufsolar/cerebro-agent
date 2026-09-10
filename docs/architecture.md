# Architecture

The model chooses investigative steps; application code owns permissions, state, budgets,
grounding and delivery. Cerebro's PostgreSQL is its writable workflow database. The monolith
replica is a separate, strictly read-only source.

## Components

| Location | Responsibility |
| --- | --- |
| `api/src/cerebro/slack/` | Socket Mode, safe events/files, workflow orchestration, reply rendering and gateway |
| `agent/` | Typed runner contracts, router/specialists, prompt, evidence ledger and optional memory wrapper |
| `replica/` | Dedicated connection pool, schema/safety checks, bounded queries and deterministic matching |
| `db/`, `jobs/` | Alembic models, Procrastinate queues, idempotency and recovery |
| `ops/`, `evals/` | Readiness, aggregate diagnostics and isolated synthetic evaluations |
| `knowledge/` | Runtime policy, allowlisted relations, required schema |
| `deploy/`, `infra/terraform/` | Compose/runtime scripts and Azure infrastructure |

There are separate `web`, `slack`, `control-worker`, `agent-worker` and `db` services.
Control handles ingestion, feedback, delivery/recovery/watchdog; agent handles Azure and images.
Each worker defaults to concurrency two. Only the agent worker initializes Azure, the replica,
and image-directory sweeping. Optional Caddy ingress is preparatory, not an implemented bank API.

## One request

1. Socket Mode acknowledges promptly; persist a sanitized envelope keyed by Slack `event_id`.
2. A control job upserts the channel/root-thread conversation, idempotent message and queued run.
3. An agent job holds the conversation lock. Cancel stale/off work before expensive I/O.
4. Load at most the latest 30 ordered messages. Download only triggering image IDs, validate
   origin/bytes and keep them in a per-run private temporary directory.
5. A tool-free structured router classifies the request. Mixed, uncertain, malformed or
   adversarial classifications use the payment route; only certain general routes bypass it.
6. The specialist gets its application-selected tools. Router and specialist share the deadline
   and custom tool budget. Images attach only to the exact triggering user turn.
7. Payment output is evidence-validated and application-rendered; general output is word-bounded.
   Persist result, safe audits, versions, usage and a unique pending output in a transaction.
8. The control queue rechecks off/staleness, sends in-thread with the output UUID as
   `client_msg_id`, records Slack's timestamp and mirrors the reply into the transcript.

Successful posts clear native status; investigation cancellation/failure clears it best-effort.
Every image directory is removed in `finally`; startup sweeps abandoned directories after
hard crashes. File URLs, bytes, local paths and model reasoning are never persisted.

## Durability and failure semantics

Unique event/message/run/output keys and per-conversation job locks prevent ordinary duplicate
processing. Output jobs have execution and enqueue locks. Slack sends are retried using the same
identifier; a crash after Slack accepts but before the DB commit still crosses two systems, so
do not claim mathematically exact-once external delivery.

Periodic recovery closes database-commit/enqueue gaps for received events, queued runs and
pending outputs. Jobs belonging to workers with expired heartbeats are finalized to release locks.
An interrupted running investigation becomes `failed/worker_interrupted`, with one error reply
when enabled. It is **not automatically replayed**, because an optional memory write may have
completed before the crash. A new explicit user request can retry. Late old workers cannot
overwrite the recovered terminal run.

An outbox enqueue failure after a successful run must not rewrite that run as failed:
the committed pending output is recovered. Superseded outputs become `cancelled`.
The `off` gate also applies to previously queued work, not just new Slack events.

Tool unavailability is a bounded observation; model exhaustion returns ambiguity.
Authentication/provider/configuration failures produce a failed run and generic error reply.
No failure ever falls back to a primary database.

## Schema and boundaries

Workflow entities: `slack_event`, `conversation`, `message`, `agent_run`, `tool_call`,
`slack_output`, `feedback`, `runtime_heartbeat`, plus Procrastinate's schema.
Use additive/backward-compatible Alembic migrations; keep the previous deployed image usable.
Historical result shapes and IDs remain readable. No new schema is needed for the cleanup.

Replica startup verifies role privileges, transaction read-only, recovery mode, SSL outside
local/test, and required relations/columns. SQLGlot resolves CTE scopes before relation checks;
CTE names never grant access to unrelated physical tables. Transactions independently enforce
read-only, result/row/time limits and restricted functions.

See [operations](operations.md) for drain/rollback and retained data; historical rationale
remains in [ADRs](adr/012-operational-simplification.md).
