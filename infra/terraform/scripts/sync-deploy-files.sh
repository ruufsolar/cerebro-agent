#!/bin/bash
# Install this checkout's deployment files on the production VM through Azure Run Command.
#
# cloud-init only delivers deploy/ and the bootstrap templates when the VM is created, and
# custom_data is immutable, so without this step a change to any deployment script would
# need a VM replacement to reach production. activate.sh and the deploy workflow run this
# first, so the VM always executes the scripts from the revision being deployed.
#
# Usage: sync-deploy-files.sh [--resource-group RG --name VM]
# Without flags the resource group and VM name come from Terraform outputs.
set -euo pipefail

command -v az >/dev/null || { echo "Azure CLI is required" >&2; exit 2; }

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
TF_DIR=$(cd "$SCRIPT_DIR/.." && pwd)
REPO_ROOT=$(cd "$TF_DIR/../.." && pwd)

RESOURCE_GROUP=${CEREBRO_RESOURCE_GROUP:-}
VM_NAME=${CEREBRO_VM_NAME:-}
while [ "$#" -gt 0 ]; do
  case "$1" in
    --resource-group) RESOURCE_GROUP=${2:-}; shift 2 ;;
    --name) VM_NAME=${2:-}; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
if [ -z "$RESOURCE_GROUP" ] || [ -z "$VM_NAME" ]; then
  command -v terraform >/dev/null || { echo "Terraform CLI is required" >&2; exit 2; }
  RESOURCE_GROUP=$(terraform -chdir="$TF_DIR" output -raw resource_group_name)
  VM_NAME=$(terraform -chdir="$TF_DIR" output -raw vm_name)
fi

# Same file set cloud-init writes, shipped as one base64 tarball inside the payload.
payload=$(tar -C "$REPO_ROOT" -czf - \
  deploy \
  infra/terraform/templates/vm-bootstrap.sh \
  infra/terraform/templates/cerebro-registry-login.sh \
  infra/terraform/templates/cerebro-agent-bootstrap.service | base64 | tr -d '\n')

remote=$(mktemp)
trap 'rm -f "$remote"' EXIT
{
  echo '#!/bin/sh'
  echo 'set -eu'
  printf 'PAYLOAD=%s\n' "$payload"
  cat <<'REMOTE'
tmp=$(mktemp -d)
printf '%s' "$PAYLOAD" | base64 -d | tar -xzf - -C "$tmp"
install -d -m 0755 /opt/cerebro-agent/deploy/systemd
cp -a "$tmp/deploy/." /opt/cerebro-agent/deploy/
install -m 0750 "$tmp/infra/terraform/templates/vm-bootstrap.sh" /usr/local/sbin/cerebro-vm-bootstrap.sh
install -m 0750 "$tmp/infra/terraform/templates/cerebro-registry-login.sh" /usr/local/sbin/cerebro-registry-login.sh
install -m 0644 "$tmp/infra/terraform/templates/cerebro-agent-bootstrap.service" /etc/systemd/system/cerebro-agent-bootstrap.service
rm -rf "$tmp"
# Installs the update/backup scripts, compose.yml, and timer units from /opt, then reloads systemd.
CEREBRO_BOOTSTRAP_DEFER_TIMERS=true /opt/cerebro-agent/deploy/bootstrap.sh >/dev/null
systemctl daemon-reload
echo CEREBRO_SYNC_OK
REMOTE
} > "$remote"

result=$(az vm run-command invoke \
  --resource-group "$RESOURCE_GROUP" \
  --name "$VM_NAME" \
  --command-id RunShellScript \
  --scripts "@$remote" \
  --query 'value[0].message' \
  --output tsv)

if ! grep -qF CEREBRO_SYNC_OK <<<"$result"; then
  printf '%s\n' "$result"
  echo "Deployment files were not installed on the VM; see the output above." >&2
  exit 1
fi
echo "Deployment files from this checkout are installed on $VM_NAME."
