# Operations and production delivery

The canonical provisioning/credentials/CD instructions are
[infra/terraform/README.md](../infra/terraform/README.md). Preserve the senior-maintained
GitHub OIDC → ACR → Key Vault/Run Command → Compose path. Terraform applies remain reviewed
operator actions; a code cleanup is not permission to deploy.

## Runtime and readiness

Production: dedicated Azure VM, retained data disk, NAT egress and managed identity. Runtime
lives at `/etc/cerebro-agent`, image `<registry>/cerebro-agent:<sha>`, services web/control/agent/
Slack/DB, optional Caddy. No shared Wattson host or publicly exposed operational endpoints.

`/health` is dependency-free liveness. `/ready` checks:
- `foundation`: Cerebro DB, current Alembic head and Procrastinate schema.
- `pilot`: foundation, complete Slack/Azure/replica configuration, external tracing disabled,
  fresh Slack/control/agent heartbeats. The name remains for deployment compatibility, not a
  product launch gate.

Heartbeats default to every 15s, stale after 45s. Readiness does not repeatedly call external
providers. `off` is a valid ready state. Production explicitly sets environment=production and
readiness_profile=pilot; local foundation needs no external credentials.

```bash
# In the image, or prefix with uv run from api/
python -m cerebro.ops.preflight --profile pilot
python -m cerebro.ops.status --hours 24 --json
```

Preflight actively checks schemas, replica safety, temporary storage and Slack authentication.
Only explicit `--live-provider` makes a synthetic Azure smoke call; it cannot access shared
memory or production customer tools. Status is aggregate: queues/failures, payment/general
volumes, outcomes, feedback, latency, usage, image failures and component health.
See [evaluations](evaluations.md) for optional quality reporting.

## Updating, drain and rollback

The existing workflow builds/pushes immutable images, synchronizes runtime scripts, activates,
checks readiness and restores previous configuration on activation failure. The VM's systemd
timer also checks updates every five minutes. Secret changes require reseeding and activation.

Update acquires the deployment lock, stops Slack and optional Caddy ingress, and allows up to
240 seconds for existing work to finish. A DB queue-check failure is **not** an empty queue:
abort and resume old services. Busy jobs also abort the update. Stop workers, tag the running
image `last-good`, recreate services and wait up to 120 seconds for `/ready`.
The `off` configuration is process-cached; restart all runtime components for a coordinated stop.

Rollback drill: record the current immutable SHA, back up Cerebro DB, select the previous SHA
through the existing deployment workflow (or set `IMAGE_TAG=last-good` in the VM's
`compose.env` and invoke the update script). Confirm `/ready` and component status, then
restore the approved SHA and recheck. Record only SHA, readiness and operator role.
Keep migrations compatible with the previous image. Do not rollback by deleting volumes.
The update script's post-deploy readiness failure reports failure; use the activation/workflow
rollback path or manual rollback, not an assumption that every script failure self-rolls back.

Backups cover Cerebro DB only, under `/var/backups/cerebro-agent`, with initial 14-day rotation.
One VM/local PostgreSQL is not HA. Verify restore separately; do not treat a backup file as proof.

## Troubleshooting

- No reply: check mode, one Socket Mode consumer, invitation/events/scopes, Slack heartbeat,
  control queue, agent startup and pending outbox in that order.
- Authentication/model failure: verify exact Azure deployment and rotated credentials.
  Never silently switch to another model/provider.
- SQL source unavailable: preflight/schema/role/replica recovery, SSL and NAT allowlist.
  Never substitute the writer DSN.
- Interrupted run: recovery marks it failed rather than replaying uncertain memory writes.
  Ask Cerebro again after restoring health.
- No 🔌 response: react to a stored Cerebro answer; inspect safe feedback dispositions and
  outbox, not raw Slack event dumps.

The five-minute watchdog logs aggregate warnings for pending events/outputs >2min, queued runs
>5min, recent failures and stale components. Running investigations over 240s are informational,
not stalled solely because of age. Heartbeats and delivery failures still signal unhealthy work.
No external alerts/PostHog.
JSON logs allow lifecycle IDs/categories/counts/versions only; optional local text format keeps
the same privacy boundary. Never log exception messages, secrets, text, SQL/results or images.

Adaptive rollout: explicitly set `CEREBRO_MAX_AGENT_TURNS=14` if the runtime file still overrides
the old default with 8. Replace obsolete `CEREBRO_AGENT_TIMEOUT_SECONDS`,
`CEREBRO_MAX_TOOL_CALLS`, and `CEREBRO_AZURE_MAX_OUTPUT_TOKENS` with
`CEREBRO_PROVIDER_REQUEST_TIMEOUT_SECONDS=180` (per request). Keep configured deployments and
reasoning unchanged. There is no overall time/token cap; monitor usage and queue latency.
The senior-maintained update script still drains for 240 seconds and aborts on unfinished work;
longer healthy investigations can therefore postpone an update. Do not force-stop them to deploy.

## Secrets and retained data

Use Key Vault and root-only runtime files; locally use an ignored mode-0600 `.env`.
No secrets in Terraform variables/state inputs, GitHub logs, tickets or chat.
Expanded `docker compose config` can contain secrets: don't paste it. Rotate keys/tokens after
exposure and restart affected consumers. Shared memory has separate Authentik credentials.

Cerebro DB retains sanitized envelopes, text/transcript snapshots, safe attachment metadata,
selected customer/evidence results, outputs, feedback, tool audits and job/heartbeat state.
Raw PII may exist in transcripts and general replies. Screenshot bytes/URLs/paths are ephemeral.
No automatic data retention/deletion job exists.

For an approved manual purge: stop ingestion and drain workers; take/verify a backup; choose
closed conversations older than a reviewed cutoff with no pending/running jobs. Dry-run counts.
In **one transaction**, materialize the approved conversation/run IDs in temporary tables, then
delete feedback, outputs, tool calls, runs, messages and conversations in FK order. Delete only
their terminal event/job records after checking job references; rollback on any mismatch/error.
Commit only after checking affected counts. Restart services and verify readiness.
Never use TRUNCATE, broad cascade, or apply this procedure to the replica. Backups may retain
purged content until their separate retention expires.
