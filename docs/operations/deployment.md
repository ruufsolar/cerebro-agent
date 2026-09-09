# Deployment

The preferred production-environment path is the reviewed
[Azure Terraform stack](../../infra/terraform/README.md). It creates a dedicated private VM,
stable NAT egress, Key Vault identity boundary, and retained managed disk, then runs the
existing registry + Docker Compose baseline. The scripts in this directory remain the runtime
deployment mechanism and can still be installed manually on an already approved VM.

## Topology

- image: `<registry>.azurecr.io/cerebro-agent:{main|sha}`, pulled with the VM managed identity;
- compose project/path: `cerebro-agent`, `/etc/cerebro-agent`;
- services: `web`, `control-worker`, `agent-worker`, `slack`, `db`, and `caddy` under the
  `ingress` profile on a deployment with a public hostname;
- liveness/readiness: `127.0.0.1:8010/health`, `127.0.0.1:8010/ready`, never public;
- database volume: compose-managed `pgdata`;
- backups: `/var/backups/cerebro-agent`, 14-day initial rotation;
- update check: systemd timer every five minutes;
- environment: `/etc/cerebro-agent/env` and interpolation-only `compose.env`.

Production must explicitly set `CEREBRO_ENVIRONMENT=production` and
`CEREBRO_READINESS_PROFILE=pilot`; the checked-in environment template keeps local-safe
foundation defaults.

The web command migrates Cerebro tables and initializes Procrastinate before serving.
The two workers and Slack wait for web liveness. Control jobs use the `control` queue;
investigations use `agent`; each worker has concurrency two and a 240-second graceful stop.
Update pulls the image, stops every source of new work — Slack ingestion, and the public
ingress where there is one — and leaves both workers running for up to
240 seconds while accepted jobs drain. A bank event sent during that window is refused at
the TCP level rather than accepted and abandoned, which is what a caller retrying a `202`
contract can act on. If work is still in flight it restarts Slack on the
old version and aborts. Otherwise it stops both idle workers, preserves the outgoing image
as `last-good`, rolls services, and gates success on `/ready`. Queued jobs stay durable.
Backups include Cerebro's own database only, never the replica.

Socket Mode itself requires no DNS or proxy. The monolith's bank-movement events do, and
that path — one hostname, one method, one route, an Authentik token, and no other public
surface — is [ADR-011](../adr/011-public-bank-movement-ingress.md) and
[public ingress](ingress.md). Anything further still needs its own review rather than
exposing an existing operational endpoint.

Without a configured public hostname the Terraform VM has no public IP and no inbound NSG
rule; with one it has exactly TCP 443 from the approved sources and TCP 80 for certificate
renewal. Use Azure Run Command for routine
status, preflight, activation, and rollback. Runtime secrets are seeded into Key Vault after
Terraform apply and read by the VM's managed identity; they are never Terraform inputs.

## Rollback

Removing the public ingress is a separate, smaller rollback: reseed with an empty
`CEREBRO_PUBLIC_HOSTNAME` and activate. See [public ingress](ingress.md).

Set `IMAGE_TAG=last-good` in `/etc/cerebro-agent/compose.env` and run the compose update.
Schema migrations must remain backward-compatible with the previous image for one release;
destructive cleanup is a later migration after rollback safety expires.

For the pilot drill, record only the image SHA, readiness result, and operator role. Switch
to `last-good`, run the update, confirm `/ready`, then restore the reviewed SHA and confirm
readiness again. Do not include environment values or customer data in the record.
