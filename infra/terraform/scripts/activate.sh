#!/bin/bash
set -euo pipefail

command -v az >/dev/null || { echo "Azure CLI is required" >&2; exit 2; }
command -v terraform >/dev/null || { echo "Terraform CLI is required" >&2; exit 2; }

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
TF_DIR=$(cd "$SCRIPT_DIR/.." && pwd)
RESOURCE_GROUP=$(terraform -chdir="$TF_DIR" output -raw resource_group_name)
VM_NAME=$(terraform -chdir="$TF_DIR" output -raw vm_name)

az vm run-command invoke \
  --resource-group "$RESOURCE_GROUP" \
  --name "$VM_NAME" \
  --command-id RunShellScript \
  --scripts '
set -euo pipefail
systemctl restart cerebro-agent-bootstrap.service
timeout 1200 bash -c '\''until curl -fsS --max-time 3 http://127.0.0.1:8010/ready >/dev/null; do sleep 10; done'\''
systemctl is-active --quiet cerebro-agent-bootstrap.service
curl -fsS http://127.0.0.1:8010/ready
' \
  --output json

echo "Cerebro bootstrap completed and /ready passed on the private VM."
