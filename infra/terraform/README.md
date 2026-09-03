# Azure production infrastructure

This directory is the reviewed production-environment path for Cerebro. It provisions a
dedicated, private Azure VM that runs the existing Docker Compose topology, plus the Azure
network, stable outbound address, managed data disk, managed identity, and Key Vault needed
to operate it. It does **not** deploy automatically and it does not promote Cerebro beyond
its current controlled-pilot capability state.

The design intentionally keeps the runtime close to the proven Wattson baseline. Moving
five stateful/long-running processes to Kubernetes or Container Apps in the same change
would add a second migration problem without improving the pilot.

## Architecture

```text
Slack Socket Mode ──outbound──┐
Azure OpenAI ───────outbound──┼── NAT Gateway / stable IP ── private Azure VM
Read replica ───────outbound──┘                               ├─ web
                                                             ├─ control-worker
GitHub Actions ──push── GHCR ──pull───────────────────────────├─ agent-worker
                                                             ├─ slack
Azure Key Vault ──managed identity───────────────────────────└─ PostgreSQL
                                                                    │
                                                              managed data disk
```

- The VM has no public IP and the network security group adds no custom inbound rules.
- Slack Socket Mode means Cerebro needs no webhook, DNS name, TLS certificate, or load
  balancer.
- A Standard NAT Gateway gives all outbound traffic a stable address. Give
  `terraform output -raw outbound_public_ip` to the replica owner for allowlisting.
- The system-assigned VM identity can read only this deployment's Key Vault secrets.
- An explicit operator receives `Key Vault Secrets Officer` at this vault only.
- Slack, Azure OpenAI, replica, PostgreSQL, and GHCR credentials are seeded after
  provisioning. They never enter Terraform variables, plans, or state.
- Docker data, Cerebro PostgreSQL, and the 14-day local backup rotation live on a dedicated
  Standard SSD. Terraform protects that disk from accidental destroy.
- The image update timer retains the last running image as `last-good`, serializes updates
  with a host lock, drains work for up to 240 seconds, and requires `/ready` before declaring
  success.

## Senior review decisions

Approve these choices before applying:

1. Azure subscription, region, naming/tags, and cost center.
2. `Standard_B2ms` and a 64-GiB Standard SSD as the initial pilot size.
3. The stable NAT IP as an allowed source at the production read replica.
4. The Entra object ID that may seed/rotate this vault's secrets.
5. The GHCR machine user/token with `read:packages` only.
6. Initial mode. Use `off` for provisioning, then explicitly seed `review` for the pilot.
7. Acceptance of the pilot's availability boundary: one VM, one local PostgreSQL, and
   backups on the same managed disk. This is recoverable infrastructure, not HA/GA.

No payment writes, holds, public ingress, SSH ingress, or customer communication are
enabled by this stack.

## Required operator access

The person applying Terraform needs:

- an Azure CLI login in the target tenant/subscription;
- permission to create the resource group and its resources;
- `Owner` or `User Access Administrator` plus `Contributor` at the target scope, because
  Terraform creates two RBAC assignments;
- permission to create the separately managed Terraform-state resource group/storage;
- Terraform 1.9+ and Azure CLI;
- the reviewed repository checkout and an existing GHCR image.

Find the current user's Entra object ID with:

```bash
az ad signed-in-user show --query id --output tsv
```

Generate or select an approved emergency SSH public key. The key is placed on the VM, but
there is no public route or NSG rule for SSH. Normal administration uses Azure Run Command.

## One-time deployment

Run all commands from `infra/terraform`.

### 1. Create the remote state backend

Pick a globally unique lowercase storage account name. The script uses Microsoft Entra
authentication, requires HTTPS, disables public blob access, enables blob versioning and
30-day soft deletion, and writes the ignored `backend.hcl` file.

```bash
az login
./scripts/bootstrap-state.sh \
  --subscription 00000000-0000-0000-0000-000000000000 \
  --location eastus2 \
  --resource-group rg-cerebro-tfstate \
  --storage-account globallyuniquecerebrotf
```

The state backend is deliberately outside this Terraform root so destroying the runtime
cannot destroy its own state. Azure Blob provides state locking. Microsoft Entra auth is
used instead of storage access keys.

### 2. Review and apply infrastructure

```bash
cp terraform.tfvars.example terraform.tfvars
# Fill subscription, region, SSH public key, operator object ID, and tags.
terraform init -backend-config=backend.hcl
terraform fmt -check -recursive
terraform validate
terraform plan -out=cerebro-prod.tfplan
terraform apply cerebro-prod.tfplan
```

Do not use `-auto-approve`. Review the plan for one VM, one retained managed disk, one NAT
Gateway/public egress IP, no VM public IP or custom inbound rule, the dedicated network,
Key Vault, and exactly two
vault-scoped role assignments.

After apply:

```bash
terraform output
terraform output -raw outbound_public_ip
```

Have the replica owner allowlist that outbound IP before activation. The VM bootstrap
service will retry safely while secrets or replica connectivity are unavailable.

### 3. Seed secrets without Terraform

The seeder reads the existing approved Cerebro `.env` as plain data; it never sources it.
It sends secret values via temporary mode-`0600` files so they do not appear in command
arguments. Export a dedicated GHCR read credential in the current shell:

```bash
export CEREBRO_GHCR_USERNAME='approved-machine-user'
read -r -s CEREBRO_GHCR_TOKEN
export CEREBRO_GHCR_TOKEN

./scripts/seed-secrets.sh \
  --vault-name "$(terraform output -raw key_vault_name)" \
  --env-file ../../.env \
  --mode off \
  --image-tag main
unset CEREBRO_GHCR_TOKEN
```

The env file must contain the Slack app/bot tokens, Azure OpenAI endpoint/key/deployment,
and production replica DSN. The script generates a safe Cerebro PostgreSQL password unless
`CEREBRO_DB_PASSWORD` is exported. It does not print any value.

The resulting vault contract is explicit and intentionally small:

| Key Vault secret | Source |
|---|---|
| `slack-app-token`, `slack-bot-token` | approved Cerebro `.env` |
| `azure-openai-endpoint`, `azure-openai-api-key`, `azure-deployment-main` | approved Cerebro `.env` |
| `read-replica-url` | approved Cerebro `.env` |
| `cerebro-db-password` | generated, or explicit operator environment override |
| `ghcr-username`, `ghcr-token` | explicit operator environment |
| `global-mode`, `image-tag` | seeder flags |

If a role assignment has not propagated, wait a few minutes and rerun the exact seeding
command. Re-running creates new Key Vault secret versions and is safe.

### 4. Activate and verify

```bash
./scripts/activate.sh
```

Activation uses Azure Run Command, not SSH. On the VM it:

1. waits for and mounts the durable disk;
2. retrieves secrets with the VM managed identity;
3. writes root-only Compose environment files;
4. logs into GHCR via standard input;
5. starts the Compose stack and timers;
6. waits for pilot `/ready` to pass.

Keep production `off` until preflight, the rollback drill, and the pilot channel are ready.
To enter review mode, reseed with `--mode review` and run `activate.sh` again. Secret or mode
changes force the same safe drain/recreate path even when the image digest is unchanged.

## Operations

Use Azure Run Command for private-VM diagnostics:

```bash
RESOURCE_GROUP=$(terraform output -raw resource_group_name)
VM_NAME=$(terraform output -raw vm_name)

az vm run-command invoke --resource-group "$RESOURCE_GROUP" --name "$VM_NAME" \
  --command-id RunShellScript \
  --scripts 'curl -fsS http://127.0.0.1:8010/ready'

az vm run-command invoke --resource-group "$RESOURCE_GROUP" --name "$VM_NAME" \
  --command-id RunShellScript \
  --scripts 'cd /etc/cerebro-agent && docker compose --env-file compose.env exec -T web python -m cerebro.ops.status --hours 24'
```

Run preflight inside the web container before switching from `off`:

```bash
az vm run-command invoke --resource-group "$RESOURCE_GROUP" --name "$VM_NAME" \
  --command-id RunShellScript \
  --scripts 'cd /etc/cerebro-agent && docker compose --env-file compose.env exec -T web python -m cerebro.ops.preflight --profile pilot'
```

The checked-in deployment runbook covers drain, rollback, backup, and pilot-gate commands.
Never include `docker inspect`, environment files, raw container logs, or Key Vault values
in a ticket.

## Rotation, update, rollback, and recovery

- **Rotate secrets:** rerun `seed-secrets.sh`, then `activate.sh`. Old Key Vault versions
  remain recoverable under vault policy, while only current values reach the VM.
- **Deploy an image:** publish the reviewed SHA to GHCR, seed that immutable SHA as
  `--image-tag`, and activate. The five-minute timer also follows the configured tag.
- **Rollback:** seed `--image-tag last-good` only after confirming the local tag exists,
  activate, and confirm `/ready`; then restore a reviewed immutable SHA.
- **Recover a VM:** Terraform may replace the VM. The managed disk is separately retained,
  reattached at LUN 0, and remounted by bootstrap. Review the plan before replacement.
- **Recover PostgreSQL:** use the latest dump in `/var/backups/cerebro-agent` according to
  the operations runbook. The replica is never backed up by Cerebro.

`terraform destroy` intentionally stops at the data disk's `prevent_destroy` lifecycle.
Deleting production state requires a separate reviewed change that removes this guard and
documents backup/recovery. Purge-protected Key Vault deletion also remains recoverable for
its retention period.

## Known limitations and next hardening

This is a pragmatic controlled-pilot runtime, not a highly available platform:

- one VM is an availability and maintenance-domain dependency;
- Cerebro PostgreSQL is containerized, not Azure Database for PostgreSQL;
- backups are on the retained data disk but are not yet copied to a separate account/region;
- Key Vault uses its public data-plane endpoint with Entra RBAC; secrets are not public, but
  a future private-endpoint design would further narrow network exposure;
- operational findings remain local logs by V0 policy, with no external alert sink;
- Terraform apply remains a reviewed operator action rather than CI automation.

Before GA or business writes, decide whether to add off-disk backups and monitoring or move
stateful components to managed services. Do not conceal these tradeoffs by calling the
pilot HA.

## Primary references

- [Terraform AzureRM backend](https://developer.hashicorp.com/terraform/language/backend/azurerm)
- [Azure Key Vault RBAC guidance](https://learn.microsoft.com/en-us/azure/key-vault/general/rbac-guide)
- [Secure Azure Key Vault access](https://learn.microsoft.com/en-us/azure/key-vault/general/secure-key-vault)
- [Managed identities on Azure VMs](https://learn.microsoft.com/en-us/entra/identity/managed-identities-azure-resources/how-managed-identities-work-vm)
- [Cloud-init on Azure Linux VMs](https://learn.microsoft.com/en-us/azure/virtual-machines/linux/using-cloud-init)
- [Explicit outbound connectivity](https://learn.microsoft.com/en-us/azure/virtual-network/ip-services/default-outbound-access)
- [Azure NAT Gateway](https://learn.microsoft.com/en-us/azure/nat-gateway/)
- [Azure managed disks](https://learn.microsoft.com/en-us/azure/virtual-machines/managed-disks-overview)
- [Azure Run Command](https://learn.microsoft.com/en-us/azure/virtual-machines/linux/run-command-managed)
