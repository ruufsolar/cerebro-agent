# Quickstart

## What the current Slack shell gives you

- A Python 3.13 package managed by `uv`.
- FastAPI `GET /health`.
- PostgreSQL/Alembic tables for Slack events, conversations, runs, tool calls, outputs,
  and feedback.
- Durable Procrastinate event/run/output jobs with periodic recovery.
- A harness-independent `AgentRunner` protocol and deterministic fake.
- Socket Mode mentions, known-thread follow-ups, fake in-thread replies, and 🧀/🔌 feedback.
- Safe-off configuration and explicit future write switches.
- CI, container, VM deployment, backup, and documentation skeletons.

It does not yet connect to Azure OpenAI, the monolith replica, screenshot bytes, or PostHog.

## Run with Docker

```bash
cp deploy/env.example .env
docker compose -f deploy/compose.local.yml up --build
curl http://localhost:8000/health
```

Expected response includes `"status":"ok"` and `"phase":"slack-shell"`. The Slack process
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

## Next implementation slice

Build Slice 2 from [vertical-slices.md](../delivery/vertical-slices.md): Agents SDK and
Azure with fake tools, preserving the tested Slack surface and durable pipeline.
