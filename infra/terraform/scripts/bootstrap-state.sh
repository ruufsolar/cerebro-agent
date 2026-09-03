#!/bin/bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: bootstrap-state.sh --subscription ID --location REGION \
  --resource-group NAME --storage-account GLOBALLY_UNIQUE_NAME

Creates the separately managed Azure Storage backend and writes ../backend.hcl.
EOF
}

SUBSCRIPTION=
LOCATION=
RESOURCE_GROUP=
STORAGE_ACCOUNT=
CONTAINER=tfstate

while [ "$#" -gt 0 ]; do
  case "$1" in
    --subscription) SUBSCRIPTION=${2:-}; shift 2 ;;
    --location) LOCATION=${2:-}; shift 2 ;;
    --resource-group) RESOURCE_GROUP=${2:-}; shift 2 ;;
    --storage-account) STORAGE_ACCOUNT=${2:-}; shift 2 ;;
    --help|-h) usage; exit 0 ;;
    *) printf 'Unknown argument: %s\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
done

if [ -z "$SUBSCRIPTION" ] || [ -z "$LOCATION" ] || [ -z "$RESOURCE_GROUP" ] ||
  [ -z "$STORAGE_ACCOUNT" ]; then
  usage >&2
  exit 2
fi
[[ "$STORAGE_ACCOUNT" =~ ^[a-z0-9]{3,24}$ ]] || {
  echo "storage-account must contain 3-24 lowercase letters and digits" >&2
  exit 2
}

command -v az >/dev/null || { echo "Azure CLI is required" >&2; exit 2; }
az account show --output none 2>/dev/null || {
  echo "Run 'az login' before bootstrapping Terraform state" >&2
  exit 2
}
az account set --subscription "$SUBSCRIPTION"

OPERATOR_ID=$(az ad signed-in-user show --query id --output tsv)
[ -n "$OPERATOR_ID" ] || { echo "Could not resolve the signed-in Entra user" >&2; exit 2; }

az group create --name "$RESOURCE_GROUP" --location "$LOCATION" --output none
az storage account create \
  --name "$STORAGE_ACCOUNT" \
  --resource-group "$RESOURCE_GROUP" \
  --location "$LOCATION" \
  --sku Standard_LRS \
  --kind StorageV2 \
  --min-tls-version TLS1_2 \
  --allow-blob-public-access false \
  --https-only true \
  --output none
az storage account blob-service-properties update \
  --account-name "$STORAGE_ACCOUNT" \
  --resource-group "$RESOURCE_GROUP" \
  --enable-versioning true \
  --enable-delete-retention true \
  --delete-retention-days 30 \
  --output none

STORAGE_ID=$(az storage account show \
  --name "$STORAGE_ACCOUNT" \
  --resource-group "$RESOURCE_GROUP" \
  --query id --output tsv)
az role assignment create \
  --assignee-object-id "$OPERATOR_ID" \
  --assignee-principal-type User \
  --role "Storage Blob Data Contributor" \
  --scope "$STORAGE_ID" \
  --output none >/dev/null

created=false
for _attempt in $(seq 1 18); do
  if az storage container create \
    --name "$CONTAINER" \
    --account-name "$STORAGE_ACCOUNT" \
    --auth-mode login \
    --output none 2>/dev/null; then
    created=true
    break
  fi
  sleep 10
done
[ "$created" = true ] || {
  echo "The RBAC assignment did not become usable; retry this script in a few minutes" >&2
  exit 1
}

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
BACKEND_FILE="$SCRIPT_DIR/../backend.hcl"
umask 077
{
  printf 'resource_group_name  = "%s"\n' "$RESOURCE_GROUP"
  printf 'storage_account_name = "%s"\n' "$STORAGE_ACCOUNT"
  printf 'container_name       = "%s"\n' "$CONTAINER"
  printf 'key                  = "cerebro-prod.tfstate"\n'
  printf 'use_azuread_auth     = true\n'
  printf 'use_cli              = true\n'
} > "$BACKEND_FILE"

echo "Terraform backend created. Next: terraform init -backend-config=backend.hcl"
