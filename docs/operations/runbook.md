# Runbook

## Basic checks

```bash
curl -fsS http://127.0.0.1:8010/health
docker compose -f /etc/cerebro-agent/compose.yml --env-file /etc/cerebro-agent/compose.env ps
docker compose -f /etc/cerebro-agent/compose.yml --env-file /etc/cerebro-agent/compose.env logs --tail=200 web worker slack
systemctl status cerebro-agent-update.timer cerebro-agent-backup.timer
```

## Slack disconnected

Check `slack` service logs, `CEREBRO_SLACK_APP_TOKEN` starts with `xapp-`, Socket Mode remains enabled,
and outbound WebSocket access works. Reinstall only if manifest scopes changed. Do not rotate
both Slack tokens simultaneously without a controlled restart.

Ensure no developer or second deployment is connected with the same app-level token while
testing. Competing Socket Mode consumers can split event delivery and make runs appear lost.

## Runs stuck/duplicated

Inspect Procrastinate doing/failed jobs and Cerebro `slack_event`, `agent_run`, and
`slack_output` identities. Do not manually resend a Slack message before checking the outbox
idempotency key. A deploy should wait for active jobs where practical; jobs must remain
retry-safe.

## Replica unhealthy

Disable live capability/global mode, preserve Slack acknowledgement, and return an explicit
temporary inability to investigate. Never change the DSN to a primary endpoint. Escalate to
the database owner with SQL fingerprint/duration/error, not customer row data.

## Azure errors/cost spike

Turn `CEREBRO_GLOBAL_MODE=off`, check deployment name versus model ID, quota/rate limits,
Responses support, and turn/tool counts. Do not enable external content tracing as a quick
debugging shortcut.

## Restore Cerebro state

Stop web/worker, create an empty Cerebro DB, and use `pg_restore` from a known backup. This
does not restore monolith data. Validate Alembic head and `/health`, then reconnect surfaces.

## Security incident

Disable mode, revoke affected Slack/Azure/DB/PostHog/GHCR credentials, preserve access-controlled
logs, identify potentially exposed customer data, and follow company incident process. A
credential in Git requires history-aware remediation and rotation.
