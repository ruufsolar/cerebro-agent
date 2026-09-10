# Development and local testing

Python 3.13, uv, Ruff, Pyright, pytest, FastAPI, SQLAlchemy/Alembic and Procrastinate.
Read [AGENTS.md](../AGENTS.md) first. Use Graphite for version control; do not submit or deploy
without authorization. The generated shared-memory client belongs to its upstream repository.

## Foundation quickstart

From the repo root, create `.env` from [deploy/env.example](../deploy/env.example) only if it
does not already exist; do not overwrite working credentials. Restrict it to mode 0600.
Keep `CEREBRO_GLOBAL_MODE=off` initially.

```bash
docker compose -f deploy/compose.local.yml up --build
curl http://localhost:8000/health
curl http://localhost:8000/ready
```

Web initializes both schemas before workers start. Without Azure, local/test uses the fake.
A production process without Azure credentials fails startup instead of silently serving fake
answers. Docker-internal DB hostname is `db`; a Python process on the host uses localhost.
If an old Compose network causes “failed to resolve host db”, stop/recreate the same project:
`docker compose -f deploy/compose.local.yml down --remove-orphans`, then start again.
Do not add `--volumes`: that deletes local database data.

## Slack acceptance

Use a separate test app/token when production is running. Otherwise coordinate stopping the
production Socket Mode consumer before connecting locally; two consumers split events.
Do not run local integration tests against production credentials/data.

1. Follow [integrations](integrations.md) for Slack, Azure and replica settings.
2. Set `CEREBRO_GLOBAL_MODE=enabled` (`review` remains compatible).
3. Run `docker compose -f deploy/compose.local.yml --profile slack up --build`.
4. Invite the app to a private test channel and mention it with a synthetic payment question.
5. Confirm one in-thread reply and a follow-up without a fresh mention. Add 🧀 then 🔌 to
   Cerebro's reply—not the human message—and confirm feedback/pain reply.
6. Test a PNG/JPEG/WebP, a partially invalid attachment batch, and a general question.
   Confirm explicit missing-image counts and no residual run files under `/tmp/cerebro-images`.
7. Check `docker compose -f deploy/compose.local.yml ps` and safe service logs.

No Tailscale/public tunnel is needed for outbound Socket Mode. Replica networking may separately
require an approved private-network route; never open the DB publicly just for convenience.
Image-capable Azure runs analyze screenshots; the fake never downloads them.

## Safe automated tests

Tests do not use Azure/Slack. Destructive workflow fixtures run only when
`CEREBRO_TEST_DATABASE_URL` is explicitly set and its database name ends in `_test`.
They never fall back to your runtime `CEREBRO_DATABASE_URL`. Use a **dedicated disposable**
database, not the application DB or replica, even if someone renamed it with that suffix.

From `api/` with local credentials absent or isolated:
```bash
uv sync --frozen
uv run ruff check src tests
uv run ruff format --check src tests
uv run pyright src tests
uv run pytest -q
```

Database tests skip without the test DSN. Before opting in, create a disposable `cerebro_test`,
set `CEREBRO_DATABASE_URL` and `CEREBRO_TEST_DATABASE_URL` to that same test DSN, then:
```bash
uv run alembic upgrade head
uv run alembic check
uv run python -m cerebro.jobs.schema
uv run pytest -q
```

The separate synthetic replica profile is safe without Azure:
```bash
docker compose -f deploy/compose.local.yml --profile replica up -d replica --wait
cd api
CEREBRO_TEST_REPLICA_URL=postgresql://cerebro_reader:local-read-only@localhost:5433/monolith_fixture \
  uv run pytest -m integration tests/test_replica_integration.py
```

## Finishing a change

Add regression tests for correctness, permissions, duplicates, interruption and uncertainty.
Run migration/Compose/image/health checks for lifecycle changes, and [evaluations](evaluations.md)
for prompt/tool changes. Update the one relevant topical guide, not several slice-status pages.
Architectural reversals get a superseding ADR. Never commit customer fixtures, screenshots,
tokens, database dumps or production transcripts.

An agent is a loop of model decisions and application tools, not an autonomous permission
boundary. A turn is a model step; a tool invocation is an audited function call. Grounding checks
whether the answer is supported; an evaluation tests it against labeled examples. These distinctions
are why mocked contract tests and live synthetic model tests both matter.
