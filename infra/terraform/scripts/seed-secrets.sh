#!/bin/bash
set -euo pipefail
umask 077

usage() {
  cat <<'EOF'
Usage: seed-secrets.sh --vault-name NAME --env-file PATH [--mode MODE] [--image-tag TAG]

Reads approved runtime values without sourcing the env file and uploads them to Key Vault.
CEREBRO_GHCR_USERNAME and CEREBRO_GHCR_TOKEN must be exported in the current shell.
Production mode defaults to "off" and must be changed explicitly.
EOF
}

VAULT_NAME=
ENV_FILE=
GLOBAL_MODE=off
IMAGE_TAG=main

while [ "$#" -gt 0 ]; do
  case "$1" in
    --vault-name) VAULT_NAME=${2:-}; shift 2 ;;
    --env-file) ENV_FILE=${2:-}; shift 2 ;;
    --mode) GLOBAL_MODE=${2:-}; shift 2 ;;
    --image-tag) IMAGE_TAG=${2:-}; shift 2 ;;
    --help|-h) usage; exit 0 ;;
    *) printf 'Unknown argument: %s\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
done

[ -n "$VAULT_NAME" ] && [ -n "$ENV_FILE" ] || { usage >&2; exit 2; }
[ -r "$ENV_FILE" ] || { echo "env file is not readable" >&2; exit 2; }
[[ "$GLOBAL_MODE" =~ ^(off|shadow|review|apply)$ ]] || {
  echo "mode must be off, shadow, review, or apply" >&2
  exit 2
}
[[ "$IMAGE_TAG" =~ ^[A-Za-z0-9._-]+$ ]] || { echo "image tag is invalid" >&2; exit 2; }
command -v az >/dev/null || { echo "Azure CLI is required" >&2; exit 2; }
command -v openssl >/dev/null || { echo "OpenSSL is required" >&2; exit 2; }
az account show --output none 2>/dev/null || { echo "Run 'az login' first" >&2; exit 2; }

env_value() {
  local key=$1
  local line value first last
  line=$(grep -m 1 -E "^${key}=" "$ENV_FILE" || true)
  value=${line#*=}
  value=${value%$'\r'}
  if [ "${#value}" -ge 2 ]; then
    first=${value:0:1}
    last=${value: -1}
    if { [ "$first" = '"' ] && [ "$last" = '"' ]; } || \
      { [ "$first" = "'" ] && [ "$last" = "'" ]; }; then
      value=${value:1:${#value}-2}
    fi
  fi
  printf '%s' "$value"
}

require_value() {
  local name=$1
  local value=$2
  [ -n "$value" ] || { echo "Required value is missing: $name" >&2; exit 2; }
  case "$value" in
    *$'\n'*|*$'\r'*) echo "Value contains a forbidden newline: $name" >&2; exit 2 ;;
  esac
}

SLACK_APP_TOKEN=$(env_value CEREBRO_SLACK_APP_TOKEN)
SLACK_BOT_TOKEN=$(env_value CEREBRO_SLACK_BOT_TOKEN)
AZURE_OPENAI_ENDPOINT=$(env_value CEREBRO_AZURE_OPENAI_ENDPOINT)
AZURE_OPENAI_API_KEY=$(env_value CEREBRO_AZURE_OPENAI_API_KEY)
AZURE_DEPLOYMENT_MAIN=$(env_value CEREBRO_AZURE_DEPLOYMENT_MAIN)
READ_REPLICA_URL=$(env_value CEREBRO_READ_REPLICA_URL)
GHCR_USERNAME=${CEREBRO_GHCR_USERNAME:-}
GHCR_TOKEN=${CEREBRO_GHCR_TOKEN:-}
DB_PASSWORD=${CEREBRO_DB_PASSWORD:-$(openssl rand -hex 32)}

require_value CEREBRO_SLACK_APP_TOKEN "$SLACK_APP_TOKEN"
require_value CEREBRO_SLACK_BOT_TOKEN "$SLACK_BOT_TOKEN"
require_value CEREBRO_AZURE_OPENAI_ENDPOINT "$AZURE_OPENAI_ENDPOINT"
require_value CEREBRO_AZURE_OPENAI_API_KEY "$AZURE_OPENAI_API_KEY"
require_value CEREBRO_AZURE_DEPLOYMENT_MAIN "$AZURE_DEPLOYMENT_MAIN"
require_value CEREBRO_READ_REPLICA_URL "$READ_REPLICA_URL"
require_value CEREBRO_GHCR_USERNAME "$GHCR_USERNAME"
require_value CEREBRO_GHCR_TOKEN "$GHCR_TOKEN"
[[ "$DB_PASSWORD" =~ ^[A-Za-z0-9]+$ ]] || {
  echo "CEREBRO_DB_PASSWORD must be alphanumeric so the internal DSN remains unambiguous" >&2
  exit 2
}

TMP_DIR=$(mktemp -d)
cleanup() {
  find "$TMP_DIR" -type f -delete
  rmdir "$TMP_DIR"
}
trap cleanup EXIT

put_secret() {
  local name=$1
  local value=$2
  local path="$TMP_DIR/$name"
  printf '%s' "$value" > "$path"
  chmod 0600 "$path"
  az keyvault secret set \
    --vault-name "$VAULT_NAME" \
    --name "$name" \
    --file "$path" \
    --only-show-errors \
    --output none
}

put_secret slack-app-token "$SLACK_APP_TOKEN"
put_secret slack-bot-token "$SLACK_BOT_TOKEN"
put_secret azure-openai-endpoint "$AZURE_OPENAI_ENDPOINT"
put_secret azure-openai-api-key "$AZURE_OPENAI_API_KEY"
put_secret azure-deployment-main "$AZURE_DEPLOYMENT_MAIN"
put_secret read-replica-url "$READ_REPLICA_URL"
put_secret cerebro-db-password "$DB_PASSWORD"
put_secret ghcr-username "$GHCR_USERNAME"
put_secret ghcr-token "$GHCR_TOKEN"
put_secret global-mode "$GLOBAL_MODE"
put_secret image-tag "$IMAGE_TAG"

echo "Required Cerebro secrets were seeded without printing their values."
echo "Production mode is '$GLOBAL_MODE'. Run scripts/activate.sh when the replica firewall is ready."
