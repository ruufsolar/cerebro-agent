# Cerebro

FinOps' independent Python back-office agent: grounded payment identification and in-character
general conversation in Slack, with Azure reasoning, screenshots and a read-only monolith replica.
Cerebro is used in production. No business writes or automatic bank processing are implemented.

## Start here

- [Product and current behavior](docs/product.md)
- [Development and local testing](docs/development.md)
- [Architecture and recovery](docs/architecture.md)
- [Agent behavior, personality and tools](docs/agent-behavior.md)
- [Integrations and credentials](docs/integrations.md)
- [Operations, CD and rollback](docs/operations.md)
- [Evaluations and feedback](docs/evaluations.md)
- [Roadmap and unresolved decisions](docs/roadmap.md)

[Azure Terraform deployment](infra/terraform/README.md) is the canonical infrastructure guide.
[ADRs](docs/adr/012-operational-simplification.md) preserve decision history.

## Quick start

Create a private `.env` from `deploy/env.example` if one does not exist. Never overwrite existing
credentials. Then:

```bash
docker compose -f deploy/compose.local.yml up --build
curl http://localhost:8000/health
curl http://localhost:8000/ready
```

This starts the foundation without Slack. Follow the development guide before enabling real
connections. `enabled` responds; `off` disables new work/output; existing `review` is an
alias for `enabled`. Retired `shadow`/`apply` values fail explicitly.

Tests never require production access. Destructive DB fixtures require a separate
`CEREBRO_TEST_DATABASE_URL` whose database name ends in `_test`.
Read [AGENTS.md](AGENTS.md) before changing code.
