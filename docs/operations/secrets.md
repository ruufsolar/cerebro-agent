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

*The endpoint is not a credential but keep environment topology within normal internal
configuration channels.

Production also sets `CEREBRO_ENVIRONMENT=production`, explicit budgets, safe global mode,
and both business-write switches false. Rotate a leaked value immediately; never solve a
leak by only deleting the latest commit because Git history and logs may retain it.

`deploy/env.example` contains names and safe defaults only. `/etc/cerebro-agent/env` and
`compose.env` are mode `0600`, excluded from images and backups where secrets are not
required. The [Azure Terraform path](../../infra/terraform/README.md) is now the production
reference: an approved operator seeds Key Vault after apply, and the VM managed identity
renders these files. Secret values do not enter Terraform state.
