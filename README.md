# cerebro-agent

Cerebro is FinOps' internal back-office agent. Its first capability investigates an
incoming payment from a Slack mention (text and/or screenshots), searches Ruuf's
read-only operational data, and replies in the same thread with a customer candidate,
evidence, uncertainty, and a FinOps CRM link.

This repository is intentionally independent from the monolith. V0 is read-only with
respect to business data: the only external side effect is a Slack thread reply. Future
payment registration and hold actions will use approval-gated monolith APIs.

## Current state

Slice 1 (Slack shell) is implemented on top of Phase 0: Socket Mode ingestion, durable
events/runs/outbox, same-thread fake responses, native status, and 🧀/🔌 feedback. The
runner is intentionally fake: no Azure OpenAI, read-replica, image download, or business
write integration is enabled yet.

Start with:

- [Wiki index](docs/README.md)
- [Quickstart](docs/getting-started/quickstart.md)
- [Current state](docs/product/current-state.md)
- [External setup checklist](docs/operations/external-setup.md)
- [Delivery plan](docs/delivery/vertical-slices.md)

## Local smoke test

```bash
cp deploy/env.example .env
docker compose -f deploy/compose.local.yml up --build
curl http://localhost:8000/health
```

To connect the existing Slack app, add its `xapp`/`xoxb` tokens to `.env`, set
`CEREBRO_GLOBAL_MODE=review`, ensure no other process is using those Socket Mode
credentials, and opt into the Slack profile:

```bash
docker compose -f deploy/compose.local.yml --profile slack up --build
```

See [local Slack testing](docs/getting-started/local-slack-testing.md) before doing this.

For Python-only development, install `uv`, then run from `api/`:

```bash
uv sync
uv run ruff check src tests
uv run pyright src tests
uv run pytest
```

See [AGENTS.md](AGENTS.md) before changing the repository.
