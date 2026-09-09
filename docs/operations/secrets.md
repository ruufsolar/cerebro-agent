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
| `RUUF_AGENTS_URL` | memory | No | The shared memory of Ruuf's agents; unset leaves the bridge off |
| `RUUF_AGENTS_M2M_CLIENT_ID` | memory | No | Cerebro's Authentik M2M client (`agents-cerebro`) |
| `RUUF_AGENTS_M2M_CLIENT_SECRET` | memory | Yes | Its client secret; never in the platform's config |
| `CEREBRO_PUBLIC_HOSTNAME` | ingress | No | Public name for bank movements; empty leaves Cerebro with no public listener |
| `CEREBRO_ACME_EMAIL` | ingress | No | Certificate-authority contact; required with a hostname |
| `CEREBRO_BANK_INGESTION_ISSUER` | ingress | No | Authentik provider URL the token's `iss` must equal |
| `CEREBRO_BANK_INGESTION_AUDIENCE` | ingress | No | Audience the token's `aud` must carry |
| `CEREBRO_BANK_INGESTION_CLIENT_ID` | ingress | No | The one Authentik client allowed to post payments |

*The endpoint is not a credential but keep environment topology within normal internal
configuration channels. The ingress values are not credentials either, but they decide who
may send Cerebro a payment event, so they change only through the reviewed seeding path.
None of them may be set without the others: see [public ingress](ingress.md).

Production also sets `CEREBRO_ENVIRONMENT=production`, explicit budgets, safe global mode,
and both business-write switches false. Rotate a leaked value immediately; never solve a
leak by only deleting the latest commit because Git history and logs may retain it.

`deploy/env.example` contains names and safe defaults only. `/etc/cerebro-agent/env` and
`compose.env` are mode `0600`, excluded from images and backups where secrets are not
required. The [Azure Terraform path](../../infra/terraform/README.md) is now the production
reference: an approved operator seeds Key Vault after apply, and the VM managed identity
renders these files. Secret values do not enter Terraform state.
