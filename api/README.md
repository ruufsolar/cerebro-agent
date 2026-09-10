# Cerebro API

The package contains Slack ingestion, routed Azure agents, replica tools, workflow state,
control/agent workers, and health/readiness endpoints. See the [repository guide](../README.md)
and [development instructions](../docs/development.md) for setup and safe tests.

Commands:

```bash
uv sync
uv run alembic upgrade head
uv run uvicorn cerebro.main:app --reload
uv run python -m cerebro.worker --role control
uv run python -m cerebro.worker --role agent
```
