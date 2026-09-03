# ADR-009: Dedicated Azure VM with Terraform for the V0 production pilot

- Status: Accepted
- Date: 2026-09-03

## Context

Cerebro has five cooperating, long-running Compose services, a durable job queue, local
PostgreSQL state, per-conversation serialization, 240-second agent drains, and Slack Socket
Mode. It needs outbound access to Slack, Azure OpenAI, GHCR, and the monolith read replica,
but it requires no inbound public application endpoint.

The existing Wattson deployment proves the VM + GHCR + Compose operational shape. The next
step is to make Cerebro's production environment reproducible and isolated without also
redesigning process orchestration during the controlled FinOps pilot.

## Decision

Provision a dedicated Azure Linux VM with Terraform and run the existing Compose stack on
it. Provision a private VNet/subnet, no VM public IP, no custom inbound NSG rules, a Standard NAT
Gateway with one stable outbound IP, a separately retained managed data disk, and a
deployment-specific Key Vault.

The VM uses a system-assigned managed identity with `Key Vault Secrets User`. A named Entra
operator receives vault-scoped `Key Vault Secrets Officer`. Runtime credentials are seeded
after Terraform and never enter Terraform configuration, plan, or state. Azure Run Command
is the default administrative path. GHCR remains the image registry and the existing
drain/readiness/`last-good` scripts remain the application deployment mechanism.

Production is created in mode `off`; enabling `review` is a separate explicit secret
rotation after readiness and replica allowlisting.

## Consequences

- Cerebro is isolated from Wattson while reusing its proven deployment semantics.
- Socket Mode avoids a load balancer, public DNS, TLS termination, and inbound firewall
  exposure.
- The NAT IP gives the database owner an explicit replica allowlist target.
- Secrets remain outside Terraform state and are retrieved through managed identity.
- Terraform can replace the VM without intentionally deleting Cerebro data; the data disk
  has `prevent_destroy`.
- The pilot is not highly available. The VM and containerized PostgreSQL are single-instance,
  and backups remain on the retained disk until off-disk backup is prioritized.
- Container Apps, Kubernetes, and managed PostgreSQL remain future options if scale,
  availability, or business-write requirements justify their migration cost.

## Amendment

The image registry moved from GHCR to this deployment's Azure Container Registry. The VM
pulls with its system-assigned managed identity and GitHub Actions pushes through a
federated OIDC credential, which removes the long-lived registry token this ADR originally
assumed would be stored in Key Vault. The runtime shape is otherwise unchanged.
