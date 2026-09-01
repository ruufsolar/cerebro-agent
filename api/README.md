# Cerebro API

The API package contains the service runtime, durable state, background worker, and agent
ports. Phase 0 exposes only `GET /health`; Slack and live agent adapters arrive in later
vertical slices.

Commands:

```bash
uv sync
uv run alembic upgrade head
uv run uvicorn cerebro.main:app --reload
uv run python -m cerebro.worker
```
