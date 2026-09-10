#!/bin/bash
set -euo pipefail
umask 077

usage() {
  cat <<'EOF'
Usage: seed-secrets.sh --vault-name NAME --env-file PATH [--mode MODE] [--image-tag TAG]

Reads approved runtime values without sourcing the env file and uploads them to Key Vault.
The Cerebro database password is reused from the vault on reseed; export CEREBRO_DB_PASSWORD
only for a deliberate database password rotation, which also requires an ALTER ROLE on the VM.
The VM pulls images with its managed identity, so no registry credential is seeded.
--mode and --image-tag likewise default to the vault's current values, so a reseed to rotate
a credential never changes what production runs. On the first seed they default to "off"
and "main". Pass them explicitly to change mode or deploy a different image.
The shared memory of Ruuf's agents (RUUF_AGENTS_*) is seeded only when the env file has a
RUUF_AGENTS_URL line: a URL turns the bridge on and needs the M2M client id and secret next
to it; an empty value turns it off; no line at all leaves the vault as it is.
The public HTTPS ingress works the same way, keyed on CEREBRO_PUBLIC_HOSTNAME: a hostname
turns it on and requires the ACME contact address and the Authentik issuer, audience, and
authorized monolith client id next to it, because a public endpoint whose token cannot be
validated must never exist; an empty value turns the ingress off and leaves Cerebro private.
EOF
}

VAULT_NAME=
ENV_FILE=
GLOBAL_MODE=""
IMAGE_TAG=""

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

if [ -z "$VAULT_NAME" ] || [ -z "$ENV_FILE" ]; then
  usage >&2
  exit 2
fi
[ -r "$ENV_FILE" ] || { echo "env file is not readable" >&2; exit 2; }
command -v az >/dev/null || { echo "Azure CLI is required" >&2; exit 2; }
az account show --output none 2>/dev/null || { echo "Run 'az login' first" >&2; exit 2; }

# A reseed must not change what production runs. Reuse the vault's current mode and image
# tag unless the operator passes them; only a first seed falls back to the safe defaults.
vault_value() {
  az keyvault secret show --vault-name "$VAULT_NAME" --name "$1" \
    --query value --output tsv 2>/dev/null | tr -d '\r\n' || true
}
if [ -z "$GLOBAL_MODE" ]; then
  GLOBAL_MODE=$(vault_value global-mode)
  [ -n "$GLOBAL_MODE" ] || GLOBAL_MODE=off
fi
if [ -z "$IMAGE_TAG" ]; then
  IMAGE_TAG=$(vault_value image-tag)
  [ -n "$IMAGE_TAG" ] || IMAGE_TAG=main
fi
[[ "$GLOBAL_MODE" =~ ^(off|enabled|review)$ ]] || {
  echo "mode must be off or enabled (review is a compatibility alias)" >&2
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

env_has_key() {
  grep -q -E "^$1=" "$ENV_FILE"
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
# The shared memory of Ruuf's agents (ruufsolar/gru). Key Vault cannot hold an empty
# value, so "none" stands for one: a URL of "none" means the bridge is off, and a scope of
# "none" means the client sends no scope. Without a RUUF_AGENTS_URL line in the env file
# nothing here is touched, so a reseed to rotate a Slack token never changes the bridge.
SEED_RUUF_AGENTS=false
RUUF_AGENTS_URL=none
RUUF_AGENTS_M2M_CLIENT_ID=
RUUF_AGENTS_M2M_CLIENT_SECRET=
RUUF_AGENTS_M2M_SCOPE=none
if env_has_key RUUF_AGENTS_URL; then
  SEED_RUUF_AGENTS=true
  RUUF_AGENTS_URL=$(env_value RUUF_AGENTS_URL)
  if [ -n "$RUUF_AGENTS_URL" ]; then
    RUUF_AGENTS_M2M_CLIENT_ID=$(env_value RUUF_AGENTS_M2M_CLIENT_ID)
    RUUF_AGENTS_M2M_CLIENT_SECRET=$(env_value RUUF_AGENTS_M2M_CLIENT_SECRET)
    RUUF_AGENTS_M2M_SCOPE=$(env_value RUUF_AGENTS_M2M_SCOPE)
    [ -n "$RUUF_AGENTS_M2M_SCOPE" ] || RUUF_AGENTS_M2M_SCOPE=none
  else
    RUUF_AGENTS_URL=none
  fi
fi
# Public HTTPS ingress for the monolith's bank-payment events. Same convention as above:
# "none" stands for the empty value Key Vault cannot store, and a file with no
# CEREBRO_PUBLIC_HOSTNAME line leaves the vault's current ingress configuration alone.
SEED_INGRESS=false
PUBLIC_HOSTNAME=none
ACME_CONTACT_EMAIL=
BANK_INGESTION_ISSUER=
BANK_INGESTION_AUDIENCE=
BANK_INGESTION_CLIENT_ID=
if env_has_key CEREBRO_PUBLIC_HOSTNAME; then
  SEED_INGRESS=true
  PUBLIC_HOSTNAME=$(env_value CEREBRO_PUBLIC_HOSTNAME)
  if [ -n "$PUBLIC_HOSTNAME" ]; then
    ACME_CONTACT_EMAIL=$(env_value CEREBRO_ACME_EMAIL)
    BANK_INGESTION_ISSUER=$(env_value CEREBRO_BANK_INGESTION_ISSUER)
    BANK_INGESTION_AUDIENCE=$(env_value CEREBRO_BANK_INGESTION_AUDIENCE)
    BANK_INGESTION_CLIENT_ID=$(env_value CEREBRO_BANK_INGESTION_CLIENT_ID)
  else
    PUBLIC_HOSTNAME=none
  fi
fi

# The local PostgreSQL keeps whatever password it was initialised with on the retained data
# disk, so a reseed must reuse the current vault value. Generate a new password only when the
# vault has none yet, or when the operator explicitly overrides it.
existing_db_password() {
  az keyvault secret show \
    --vault-name "$VAULT_NAME" \
    --name cerebro-db-password \
    --query value \
    --output tsv 2>/dev/null | tr -d '\r\n' || true
}
DB_PASSWORD=${CEREBRO_DB_PASSWORD:-$(existing_db_password)}
if [ -z "$DB_PASSWORD" ]; then
  DB_PASSWORD=$(openssl rand -hex 32)
  echo "No cerebro-db-password exists in the vault yet; generating one."
fi

require_value CEREBRO_SLACK_APP_TOKEN "$SLACK_APP_TOKEN"
require_value CEREBRO_SLACK_BOT_TOKEN "$SLACK_BOT_TOKEN"
require_value CEREBRO_AZURE_OPENAI_ENDPOINT "$AZURE_OPENAI_ENDPOINT"
require_value CEREBRO_AZURE_OPENAI_API_KEY "$AZURE_OPENAI_API_KEY"
require_value CEREBRO_AZURE_DEPLOYMENT_MAIN "$AZURE_DEPLOYMENT_MAIN"
require_value CEREBRO_READ_REPLICA_URL "$READ_REPLICA_URL"
if [ "$RUUF_AGENTS_URL" != none ]; then
  [[ "$RUUF_AGENTS_URL" =~ ^https://[^[:space:]/]+$ ]] || {
    echo "RUUF_AGENTS_URL must be https://<host> with no path" >&2
    exit 2
  }
  require_value RUUF_AGENTS_M2M_CLIENT_ID "$RUUF_AGENTS_M2M_CLIENT_ID"
  require_value RUUF_AGENTS_M2M_CLIENT_SECRET "$RUUF_AGENTS_M2M_CLIENT_SECRET"
  require_value RUUF_AGENTS_M2M_SCOPE "$RUUF_AGENTS_M2M_SCOPE"
fi
if [ "$PUBLIC_HOSTNAME" != none ]; then
  [[ "$PUBLIC_HOSTNAME" =~ ^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$ ]] || {
    echo "CEREBRO_PUBLIC_HOSTNAME must be a lowercase fully qualified domain name" >&2
    exit 2
  }
  [[ "$ACME_CONTACT_EMAIL" =~ ^[^[:space:]@]+@[^[:space:]@]+\.[^[:space:]@]+$ ]] || {
    echo "CEREBRO_ACME_EMAIL must be an address the certificate authority can reach" >&2
    exit 2
  }
  # Authentik's "iss" is the provider URL and ends in a slash; Cerebro compares it exactly.
  [[ "$BANK_INGESTION_ISSUER" =~ ^https://[^[:space:]]+/$ ]] || {
    echo "CEREBRO_BANK_INGESTION_ISSUER must be an https URL ending in /" >&2
    exit 2
  }
  require_value CEREBRO_BANK_INGESTION_AUDIENCE "$BANK_INGESTION_AUDIENCE"
  require_value CEREBRO_BANK_INGESTION_CLIENT_ID "$BANK_INGESTION_CLIENT_ID"
fi
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
put_secret global-mode "$GLOBAL_MODE"
put_secret image-tag "$IMAGE_TAG"
if [ "$SEED_INGRESS" = true ]; then
  put_secret public-hostname "$PUBLIC_HOSTNAME"
  if [ "$PUBLIC_HOSTNAME" != none ]; then
    put_secret acme-contact-email "$ACME_CONTACT_EMAIL"
    put_secret bank-ingestion-issuer "$BANK_INGESTION_ISSUER"
    put_secret bank-ingestion-audience "$BANK_INGESTION_AUDIENCE"
    put_secret bank-ingestion-client-id "$BANK_INGESTION_CLIENT_ID"
  fi
fi
if [ "$SEED_RUUF_AGENTS" = true ]; then
  put_secret ruuf-agents-url "$RUUF_AGENTS_URL"
  if [ "$RUUF_AGENTS_URL" != none ]; then
    put_secret ruuf-agents-m2m-client-id "$RUUF_AGENTS_M2M_CLIENT_ID"
    put_secret ruuf-agents-m2m-client-secret "$RUUF_AGENTS_M2M_CLIENT_SECRET"
    put_secret ruuf-agents-m2m-scope "$RUUF_AGENTS_M2M_SCOPE"
  fi
fi

echo "Required Cerebro secrets were seeded without printing their values."
if [ "$SEED_RUUF_AGENTS" = true ]; then
  if [ "$RUUF_AGENTS_URL" != none ]; then
    echo "The shared memory of Ruuf's agents is on, at $RUUF_AGENTS_URL."
  else
    echo "The shared memory of Ruuf's agents is off."
  fi
fi
if [ "$SEED_INGRESS" = true ]; then
  if [ "$PUBLIC_HOSTNAME" != none ]; then
    echo "Public ingress is on, at https://$PUBLIC_HOSTNAME."
  else
    echo "Public ingress is off; Cerebro keeps no public listener."
  fi
fi
echo "Production mode is '$GLOBAL_MODE'. Run scripts/activate.sh when the replica firewall is ready."
