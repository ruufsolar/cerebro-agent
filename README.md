# cerebro-agent

Cerebro is FinOps' internal back-office agent. Its first capability investigates an
incoming payment from a Slack mention (text and/or screenshots), searches Ruuf's
read-only operational data, and replies in the same thread with a customer candidate,
evidence, uncertainty, and a FinOps CRM link.

This repository is intentionally independent from the monolith. V0 is read-only with
respect to business data: the only external side effect is a Slack thread reply. Future
payment registration and hold actions will use approval-gated monolith APIs.

## Current state

Slice 3 is implemented: the bounded Agents SDK investigator can use a dedicated monolith
read replica through six audited tools for policy/schema lookup, candidate search,
candidate verification, Vambe context, and allowlisted SQL. A recommendation is accepted
only after deterministic candidate verification. Without Azure credentials, the
deterministic fake runner remains available; replica preflight and integration tests can
still run independently with the synthetic profile.

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

To enable real model reasoning, also configure the Azure endpoint/key/deployment described
in [Azure OpenAI setup](docs/integrations/azure-openai.md). Validate the synthetic corpus
without calling Azure from `api/` with `uv run python -m cerebro.evals.run`; add `--live`
only when approved credentials are present.

To test the Slice 3 data boundary without Azure or Slack:

```bash
docker compose -f deploy/compose.local.yml --profile replica up -d replica --wait
cd api
CEREBRO_TEST_REPLICA_URL=postgresql://cerebro_reader:local-read-only@localhost:5433/monolith_fixture \
  uv run pytest -m integration tests/test_replica_integration.py
```

For Python-only development, install `uv`, then run from `api/`:

```bash
uv sync
uv run ruff check src tests
uv run pyright src tests
uv run pytest
```

See [AGENTS.md](AGENTS.md) before changing the repository.
