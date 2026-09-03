# Quickstart

## What the current service gives you

- A Python 3.13 package managed by `uv`.
- FastAPI `GET /health` and foundation/pilot `GET /ready`.
- PostgreSQL/Alembic tables for Slack events, conversations, runs, tool calls, outputs,
  and feedback.
- Separate two-concurrency Procrastinate control/agent queues with recovery and watchdogs.
- An Agents SDK runner using Azure Responses, plus a deterministic fallback fake.
- Versioned prompt/knowledge, structured results, bounded turns/tools/deadline, and safe tool audit.
- Optional read-replica pool with schema/role checks, deterministic candidate tools, Vambe,
  and SQLGlot-validated long-tail queries.
- Socket Mode mentions, known-thread follow-ups, in-thread replies, and 🧀/🔌 feedback.
- Ephemeral Slack PNG/JPEG/WebP retrieval, byte validation, high-detail multimodal input,
  partial fallback, and guaranteed per-run cleanup.
- Safe-off configuration and explicit future write switches.
- Privacy-safe local structured logs and preflight/status/pilot operator commands.
- CI, container, VM deployment, backup, and documentation skeletons.

V0 deliberately has no PostHog or external tracing. Without a replica DSN, the live model reports sources
unavailable; with a verified replica DSN, text and triggering-message screenshots use real
read-only data for verification.

## Run with Docker

```bash
cp deploy/env.example .env
docker compose -f deploy/compose.local.yml up --build
curl http://localhost:8000/health
curl http://localhost:8000/ready
```

Expected health includes `"status":"ok"` and `"phase":"payment-identification-pilot"`.
Foundation readiness should report `"status":"ready"`. The Slack process
is opt-in; see [local Slack testing](local-slack-testing.md).

## Run with local Python

Install Python 3.13, `uv`, and PostgreSQL. From `api/`:

```bash
uv sync
createdb cerebro
uv run python -m cerebro.jobs.schema
uv run alembic upgrade head
uv run python -m cerebro.web
```

In two other terminals:

```bash
cd api
uv run python -m cerebro.worker --role control
uv run python -m cerebro.worker --role agent
```

## Verify

```bash
cd api
uv run ruff check src tests
uv run ruff format --check src tests
uv run pyright src tests
uv run pytest
uv run alembic check
```

Validate the synthetic evaluation corpus without an external call:

```bash
cd api
uv run python -m cerebro.evals.run
```

Use `--live` only with approved Azure credentials; it still uses synthetic fixtures and
never Slack or customer data.

## Test the replica boundary without Azure

From the repository root:

```bash
docker compose -f deploy/compose.local.yml --profile replica up -d replica --wait
cd api
CEREBRO_TEST_REPLICA_URL=postgresql://cerebro_reader:local-read-only@localhost:5433/monolith_fixture \
  uv run pytest -m integration tests/test_replica_integration.py
```

The fixture contains synthetic identities only. For the operator preflight, set
`CEREBRO_READ_REPLICA_URL` to that DSN plus
`CEREBRO_ALLOW_NON_REPLICA_READONLY_DB=true`, then run
`uv run python -m cerebro.replica.check`. Never enable that override outside local/test.

## Next acceptance step

Run the controlled ten-case pilot and gate from
[Pilot operations](../operations/pilot-operations.md), complete the rollback drill, and
obtain explicit FinOps signoff. Payment identification remains preview until then.
