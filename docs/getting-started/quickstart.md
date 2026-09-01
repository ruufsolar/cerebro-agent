# Quickstart

## What the current service gives you

- A Python 3.13 package managed by `uv`.
- FastAPI `GET /health`.
- PostgreSQL/Alembic tables for Slack events, conversations, runs, tool calls, outputs,
  and feedback.
- Durable Procrastinate event/run/output jobs with periodic recovery.
- An Agents SDK runner using Azure Responses, plus a deterministic fallback fake.
- Versioned prompt/knowledge, structured results, bounded turns/tools/deadline, and safe tool audit.
- Optional read-replica pool with schema/role checks, deterministic candidate tools, Vambe,
  and SQLGlot-validated long-tail queries.
- Socket Mode mentions, known-thread follow-ups, in-thread replies, and 🧀/🔌 feedback.
- Safe-off configuration and explicit future write switches.
- CI, container, VM deployment, backup, and documentation skeletons.

It does not yet download screenshot bytes or emit PostHog events. Without a replica DSN,
the live model reports sources unavailable; with a verified replica DSN, text-based
investigation uses real read-only data.

## Run with Docker

```bash
cp deploy/env.example .env
docker compose -f deploy/compose.local.yml up --build
curl http://localhost:8000/health
```

Expected response includes `"status":"ok"` and `"phase":"replica-tools"`. The Slack process
is opt-in; see [local Slack testing](local-slack-testing.md).

## Run with local Python

Install Python 3.13, `uv`, and PostgreSQL. From `api/`:

```bash
uv sync
createdb cerebro
uv run python -m cerebro.jobs.schema
uv run alembic upgrade head
uv run uvicorn cerebro.main:app --reload
```

In another terminal:

```bash
cd api
uv run python -m cerebro.worker
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

## Next implementation slice

Build Slice 4 from [vertical-slices.md](../delivery/vertical-slices.md): authorized Slack
screenshot download, multimodal input, and guaranteed temporary-file cleanup.
