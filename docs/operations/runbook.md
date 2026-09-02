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

Run the fail-closed preflight from the same image/environment as the worker:

```bash
cd /app/api
python -m cerebro.replica.check
```

It verifies session read-only state, physical recovery, role flags/write privileges, and the
versioned schema catalog. Do not set `CEREBRO_ALLOW_NON_REPLICA_READONLY_DB=true` in staging
or production; the code refuses that exception outside local/test. A schema mismatch should
be fixed by reviewing the catalog/query or by a deliberate monolith read view/API—not by
removing the check or granting broader access.

For a local-only reproduction with synthetic data:

```bash
docker compose -f deploy/compose.local.yml --profile replica up -d replica --wait
```

The fixture role has `SELECT` only and `default_transaction_read_only=on`.

## Azure errors/cost spike

Turn `CEREBRO_GLOBAL_MODE=off`, check deployment name versus model ID, quota/rate limits,
Responses support, and turn/tool counts. Do not enable external content tracing as a quick
debugging shortcut.

The worker intentionally refuses partial Azure configuration. Set both endpoint and API
key, or leave both empty to use the deterministic fake. Timeout, turn/tool exhaustion,
refusal, and invalid structured output are successful `unknown` investigations with a
`completion_reason`; authentication, quota, provider, and networking failures are failed
runs. Use the error category and Azure request metadata, never prompt/customer content, for
diagnosis.

## Screenshot unavailable or image cleanup alert

Confirm the installed Slack bot token includes `files:read`, the file is Slack-hosted static
PNG/JPEG/WebP, and the configured count/byte/pixel/time limits were not exceeded. Use only the
categorical failure reason in `agent_run.input_snapshot`/steps; never print a private URL,
data URL, screenshot path, bytes, or extracted PII to logs.

The worker sweeps abandoned `run-*` directories under `/tmp/cerebro-images` at startup. After
an investigation, that directory should contain no run directories. If a hard crash leaves
one behind, stop the worker, preserve no screenshot content, restart it to run the bounded
sweep, and verify cleanup before resuming `review`/`shadow` mode.

## Restore Cerebro state

Stop web/worker, create an empty Cerebro DB, and use `pg_restore` from a known backup. This
does not restore monolith data. Validate Alembic head and `/health`, then reconnect surfaces.

## Security incident

Disable mode, revoke affected Slack/Azure/DB/PostHog/GHCR credentials, preserve access-controlled
logs, identify potentially exposed customer data, and follow company incident process. A
credential in Git requires history-aware remediation and rotation.
