# Secrets and configuration

## Required by stage

| Variable | Phase/Slice | Secret | Purpose |
|---|---:|---:|---|
| `CEREBRO_DATABASE_URL` | 0 | Yes | Cerebro operational PostgreSQL |
| `CEREBRO_SLACK_APP_TOKEN` | 1 | Yes | Socket Mode `xapp` connection |
| `CEREBRO_SLACK_BOT_TOKEN` | 1 | Yes | Slack Web API `xoxb` token |
| `CEREBRO_AZURE_OPENAI_ENDPOINT` | 2 | No* | Azure resource endpoint |
| `CEREBRO_AZURE_OPENAI_API_KEY` | 2 | Yes | Initial Azure auth |
| `CEREBRO_AZURE_DEPLOYMENT_MAIN` | 2 | No | Exact Azure deployment name |
| `CEREBRO_READ_REPLICA_URL` | 3 | Yes | Dedicated read-only monolith replica |
| `CEREBRO_POSTHOG_API_KEY` | 6 | Yes | Cerebro PostHog project key |
| `CEREBRO_POSTHOG_HOST` | 6 | No | PostHog ingestion host |

*The endpoint is not a credential but keep environment topology within normal internal
configuration channels.

Production also sets `CEREBRO_ENVIRONMENT=production`, explicit budgets, safe global mode,
and both business-write switches false. Rotate a leaked value immediately; never solve a
leak by only deleting the latest commit because Git history and logs may retain it.

`deploy/env.example` contains names and safe defaults only. `/etc/cerebro-agent/env` and
`compose.env` are mode `0600`, excluded from images and backups where secrets are not
required. Prefer Key Vault/managed identity when platform support is ready.
