#!/bin/bash
set -euo pipefail

command -v az >/dev/null || { echo "Azure CLI is required" >&2; exit 2; }
command -v terraform >/dev/null || { echo "Terraform CLI is required" >&2; exit 2; }

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
TF_DIR=$(cd "$SCRIPT_DIR/.." && pwd)
RESOURCE_GROUP=$(terraform -chdir="$TF_DIR" output -raw resource_group_name)
VM_NAME=$(terraform -chdir="$TF_DIR" output -raw vm_name)

# The remote payload is shared with .github/workflows/deploy.yml; see the comments there
# about Run Command's shell and exit-status behaviour.
result=$(az vm run-command invoke \
  --resource-group "$RESOURCE_GROUP" \
  --name "$VM_NAME" \
  --command-id RunShellScript \
  --scripts "@$SCRIPT_DIR/activate-remote.sh" \
  --query 'value[0].message' \
  --output tsv)

printf '%s\n' "$result"
if ! grep -qF CEREBRO_ACTIVATE_OK <<<"$result"; then
  echo "Cerebro activation did not complete on the VM; see the output above." >&2
  exit 1
fi
echo "Cerebro bootstrap completed and /ready passed on the private VM."
