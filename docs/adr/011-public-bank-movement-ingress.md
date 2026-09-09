# ADR-011: Public HTTPS ingress for monolith bank-movement events

- Status: Accepted
- Date: 2026-09-09
- Amends: [ADR-009](009-dedicated-azure-vm-with-terraform.md)

## Context

ADR-009 provisioned a VM with no public address because Slack Socket Mode needs none, and
recorded that a later webhook would require "a separate threat/network review instead of
exposing the Phase 0 health server by default". This is that review.

The monolith is the system that learns about a bank payment first. It will `POST` each
incoming payment event to Cerebro, which persists and queues it, answers `202 Accepted`, and
investigates asynchronously — the trigger `bank-ingestion.md` has always described as the
eventual real one, replacing the temporary Slack mention.

That is an inbound call, so it needs an address the monolith can reach: a stable hostname,
a certificate that renews itself, and a route to the FastAPI service. Nothing else about
Cerebro should become reachable in the process. The endpoint carries payment data, so it
must be authenticated before any of it is read.

## Decision

Add one public path and keep everything else exactly as private as it is today.

**Address.** A static Standard public IP attached to the existing NIC, at
`cerebro.ruuf.cl`. Not a load balancer: with one VM it adds a failure domain and a monthly
bill without adding availability. The subnet's NAT Gateway keeps precedence for outbound
flows, so the stable egress address the read replica allowlists does not change.

**Certificate.** Caddy in the Compose stack, issuing from Let's Encrypt and renewing on its
own with no operator step and no cron entry. The ACME account and the certificates live on
the retained data disk, so replacing a container never re-issues. The HTTP-01 challenge is
requested explicitly, because TCP 443 may be narrowed to the monolith's egress addresses
and TLS-ALPN would then be unreachable.

**Routing.** Caddy forwards exactly `POST /integrations/bank-movements` to `web:8000`.
Every other method and path answers 404. `/health`, `/ready`, the OpenAPI documents,
PostgreSQL, the workers, and SSH keep no public route at all, and the network security
group refuses their ports by name as well as by default.

**Authentication.** Cerebro validates an Authentik M2M token in the application, the same
identity system Cerebro already uses to reach the shared memory of Ruuf's agents. The proxy
additionally refuses a request that carries no bearer credential at all, so an unauthorized
scanner never reaches that code — a pre-filter, not authentication.

**One switch.** A deployment with no public hostname has no public address, no inbound
rule, no Caddy container, and `bank_ingestion_enabled` false. The Terraform variable and the
Key Vault secret are what turn the ingress on, and the secret seeder refuses a hostname
without the issuer, audience, and authorized client id next to it: a public endpoint whose
tokens cannot be validated must not be able to exist, even briefly.

## Consequences

- Cerebro gains one authenticated public endpoint and no other public surface.
- The monolith can trigger investigations directly, which is what retires the manual Slack
  trigger as the only automatic path.
- Certificate expiry stops being an operational task, and starts being a dependency on
  Let's Encrypt reachability from the VM and on port 80 remaining open.
- The VM now has an inbound attack surface it did not have. It is one path, one method, a
  64 KB body limit, and a credential check, but it is not zero.
- A deploy stops the ingress while work drains, so the monolith sees refused connections for
  the length of an update and must retry. The `202` contract already implies that.
- DNS becomes a production dependency. Where `ruuf.cl` is hosted decides whether Terraform
  manages the record or the zone owner does.
- The endpoint's own logic — idempotency, persistence, queueing, the Slack result — is a
  separate change. This ADR covers only the path to it.
