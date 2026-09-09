#!/bin/bash
set -euo pipefail
umask 077

readonly AZURE_ENV=/etc/cerebro-agent/azure.env
readonly DEPLOY_ROOT=/opt/cerebro-agent/deploy
readonly DATA_LINK=/dev/disk/azure/scsi1/lun0
readonly DATA_MOUNT=/srv/cerebro
readonly RUNTIME_ENV=/etc/cerebro-agent/env
readonly COMPOSE_ENV=/etc/cerebro-agent/compose.env

log() {
  printf 'cerebro-bootstrap: %s\n' "$1"
}

fail() {
  printf 'cerebro-bootstrap: ERROR: %s\n' "$1" >&2
  exit 1
}

[ -r "$AZURE_ENV" ] || fail "Azure bootstrap configuration is missing"
# shellcheck disable=SC1090
source "$AZURE_ENV"
[ -n "${CEREBRO_KEY_VAULT_NAME:-}" ] || fail "Key Vault name is missing"
[ -n "${CEREBRO_IMAGE_REPOSITORY:-}" ] || fail "image repository is missing"

log "waiting for the managed data disk"
for _attempt in $(seq 1 120); do
  [ -e "$DATA_LINK" ] && break
  sleep 5
done
[ -e "$DATA_LINK" ] || fail "managed data disk was not attached at LUN 0"
DATA_DEVICE=$(readlink -f "$DATA_LINK")
[ -b "$DATA_DEVICE" ] || fail "managed data disk is not a block device"

# Keep the update timer from racing this activation: its run takes the same lock the
# forced update below needs, and an activation that loses that race fails. Wait for a run
# already in progress rather than killing it mid-drain. The timer is re-enabled below.
systemctl stop cerebro-agent-update.timer >/dev/null 2>&1 || true
for _attempt in $(seq 1 90); do
  systemctl is-active --quiet cerebro-agent-update.service || break
  sleep 5
done

# Stopping Docker to move its data-root is a first-boot operation. On a live VM it kills
# every container, including PostgreSQL and any agent run in flight, before the drained
# update below has had a chance to let that work finish; a job killed this way is left in
# "doing" with no worker. Only touch Docker when the disk is not yet serving it.
if mountpoint -q "$DATA_MOUNT" && systemctl is-active --quiet docker.service &&
  [ "$(docker info --format '{{.DockerRootDir}}' 2>/dev/null)" = "$DATA_MOUNT/docker" ]; then
  log "data disk already mounted and serving Docker; leaving the running stack alone"
else
  systemctl stop docker.service docker.socket >/dev/null 2>&1 || true
  if ! blkid "$DATA_DEVICE" >/dev/null 2>&1; then
    log "formatting the new managed data disk"
    mkfs.ext4 -F "$DATA_DEVICE" >/dev/null
  fi
  DATA_UUID=$(blkid -s UUID -o value "$DATA_DEVICE")
  [ -n "$DATA_UUID" ] || fail "managed data disk has no filesystem UUID"
  mkdir -p "$DATA_MOUNT"
  if ! grep -qF "UUID=$DATA_UUID $DATA_MOUNT " /etc/fstab; then
    printf 'UUID=%s %s ext4 defaults,nofail 0 2\n' "$DATA_UUID" "$DATA_MOUNT" >> /etc/fstab
  fi
  mountpoint -q "$DATA_MOUNT" || mount "$DATA_MOUNT"
  mkdir -p "$DATA_MOUNT/docker"
  systemctl restart docker.service
fi
mkdir -p "$DATA_MOUNT/backups/cerebro-agent"
chmod 0700 "$DATA_MOUNT/backups/cerebro-agent"

if [ -e /var/backups/cerebro-agent ] && [ ! -L /var/backups/cerebro-agent ]; then
  rmdir /var/backups/cerebro-agent 2>/dev/null || \
    fail "/var/backups/cerebro-agent contains unexpected local data"
fi
ln -sfn "$DATA_MOUNT/backups/cerebro-agent" /var/backups/cerebro-agent

CEREBRO_BOOTSTRAP_DEFER_TIMERS=true "$DEPLOY_ROOT/bootstrap.sh" >/dev/null

IMDS_URL='http://169.254.169.254/metadata/identity/oauth2/token?api-version=2018-02-01&resource=https%3A%2F%2Fvault.azure.net'
ACCESS_TOKEN=$(curl --fail --silent --show-error --noproxy '*' \
  -H 'Metadata: true' "$IMDS_URL" | jq -er '.access_token')
[ -n "$ACCESS_TOKEN" ] || fail "managed-identity token was unavailable"

check_env_encoding() {
  local name=$1
  local value=$2
  case "$value" in
    *$'\n'*|*$'\r'*) fail "Key Vault secret contains a forbidden newline: $name" ;;
  esac
  if [[ "$value" == *"\\'"* || "$value" == *"\\" ]]; then
    fail "Key Vault secret has no lossless env-file encoding: $name"
  fi
}

vault_secret() {
  local name=$1
  local value
  value=$(curl --fail --silent --show-error \
    -H "Authorization: Bearer $ACCESS_TOKEN" \
    "https://${CEREBRO_KEY_VAULT_NAME}.vault.azure.net/secrets/${name}?api-version=7.4" \
    | jq -er '.value') || fail "required Key Vault secret is unavailable: $name"
  check_env_encoding "$name" "$value"
  printf '%s' "$value"
}

# A secret the vault may not hold yet. Only "not found" and the value "none" mean unset
# (Key Vault cannot store an empty value, so the seeder writes "none" for one); any other
# failure is a failure, so an outage cannot quietly switch a feature off.
optional_vault_secret() {
  local name=$1
  local response status body value
  response=$(curl --silent --show-error --write-out '\n%{http_code}' \
    -H "Authorization: Bearer $ACCESS_TOKEN" \
    "https://${CEREBRO_KEY_VAULT_NAME}.vault.azure.net/secrets/${name}?api-version=7.4") \
    || fail "Key Vault was unreachable while reading: $name"
  status=${response##*$'\n'}
  body=${response%$'\n'*}
  case "$status" in
    200) ;;
    404) return 0 ;;
    *) fail "Key Vault answered HTTP $status for: $name" ;;
  esac
  value=$(printf '%s' "$body" | jq -er '.value') || fail "Key Vault secret is unreadable: $name"
  [ "$value" != none ] || return 0
  check_env_encoding "$name" "$value"
  printf '%s' "$value"
}

# Compose reads a single-quoted env-file value literally and resolves only \' to a
# quote, so escaping backslashes here would double them inside the container. Escape
# quotes only; vault_secret rejects the two forms this cannot represent (a backslash
# immediately before a quote, and a trailing backslash).
dotenv_value() {
  local escaped=${1//\'/\\\'}
  printf "'%s'" "$escaped"
}

write_env_value() {
  printf '%s=%s\n' "$1" "$(dotenv_value "$2")"
}

SLACK_APP_TOKEN=$(vault_secret slack-app-token)
SLACK_BOT_TOKEN=$(vault_secret slack-bot-token)
AZURE_OPENAI_ENDPOINT=$(vault_secret azure-openai-endpoint)
AZURE_OPENAI_API_KEY=$(vault_secret azure-openai-api-key)
AZURE_DEPLOYMENT_MAIN=$(vault_secret azure-deployment-main)
READ_REPLICA_URL=$(vault_secret read-replica-url)
DB_PASSWORD=$(vault_secret cerebro-db-password)
GLOBAL_MODE=$(vault_secret global-mode)
IMAGE_TAG=$(vault_secret image-tag)
# The shared memory of Ruuf's agents (ruufsolar/gru): off until the seeder stores a URL.
# With the URL absent from the runtime env, Cerebro runs exactly as it did before.
RUUF_AGENTS_URL=$(optional_vault_secret ruuf-agents-url)
RUUF_AGENTS_M2M_CLIENT_ID=
RUUF_AGENTS_M2M_CLIENT_SECRET=
RUUF_AGENTS_M2M_SCOPE=
if [ -n "$RUUF_AGENTS_URL" ]; then
  RUUF_AGENTS_M2M_CLIENT_ID=$(vault_secret ruuf-agents-m2m-client-id)
  RUUF_AGENTS_M2M_CLIENT_SECRET=$(vault_secret ruuf-agents-m2m-client-secret)
  RUUF_AGENTS_M2M_SCOPE=$(optional_vault_secret ruuf-agents-m2m-scope)
fi
# Public HTTPS ingress for the monolith's bank-payment events. Absent hostname, no ingress:
# the Compose profile stays empty, Caddy is not part of the project, and the VM keeps the
# private shape it had before. The Authentik values below are what lets Cerebro validate the
# monolith's token, so they are required whenever the hostname is set: opening a public
# listener without them would publish an endpoint nothing can authenticate.
PUBLIC_HOSTNAME=$(optional_vault_secret public-hostname)
ACME_EMAIL=
BANK_INGESTION_ISSUER=
BANK_INGESTION_AUDIENCE=
BANK_INGESTION_CLIENT_ID=
# Deliberately not named COMPOSE_PROFILES: a shell variable of that name would take
# precedence over the env file for any `docker compose` this script goes on to invoke.
INGRESS_PROFILE=
if [ -n "$PUBLIC_HOSTNAME" ]; then
  ACME_EMAIL=$(vault_secret acme-contact-email)
  BANK_INGESTION_ISSUER=$(vault_secret bank-ingestion-issuer)
  BANK_INGESTION_AUDIENCE=$(vault_secret bank-ingestion-audience)
  BANK_INGESTION_CLIENT_ID=$(vault_secret bank-ingestion-client-id)
  INGRESS_PROFILE=ingress
fi

[[ "$DB_PASSWORD" =~ ^[A-Za-z0-9]+$ ]] || fail "database password must be alphanumeric"
[[ "$GLOBAL_MODE" =~ ^(off|shadow|review|apply)$ ]] || fail "global mode is invalid"
[[ "$IMAGE_TAG" =~ ^[A-Za-z0-9._-]+$ ]] || fail "image tag is invalid"
[ -z "$RUUF_AGENTS_URL" ] || [[ "$RUUF_AGENTS_URL" =~ ^https://[^[:space:]/]+$ ]] || \
  fail "shared memory URL must be https://<host> with no path"
if [ -n "$PUBLIC_HOSTNAME" ]; then
  # Caddy asks a public certificate authority for exactly this name, and the name reaches
  # Caddy through Compose interpolation. Refuse anything that is not a plain hostname.
  [[ "$PUBLIC_HOSTNAME" =~ ^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$ ]] || \
    fail "public hostname must be a lowercase fully qualified domain name"
  [[ "$ACME_EMAIL" =~ ^[^[:space:]@]+@[^[:space:]@]+\.[^[:space:]@]+$ ]] || \
    fail "ACME contact email is invalid"
  # Authentik issues tokens whose "iss" is the provider URL, ending in a slash.
  [[ "$BANK_INGESTION_ISSUER" =~ ^https://[^[:space:]]+/$ ]] || \
    fail "bank ingestion issuer must be an https URL ending in /"
  [ -n "$BANK_INGESTION_AUDIENCE" ] || fail "bank ingestion audience is missing"
  [ -n "$BANK_INGESTION_CLIENT_ID" ] || fail "bank ingestion client id is missing"
fi

old_hash=missing
if [ -r "$RUNTIME_ENV" ] && [ -r "$COMPOSE_ENV" ]; then
  old_hash=$(sha256sum "$RUNTIME_ENV" "$COMPOSE_ENV" | sha256sum | cut -d' ' -f1)
fi

runtime_tmp=$(mktemp /etc/cerebro-agent/env.XXXXXX)
{
  write_env_value CEREBRO_ENVIRONMENT production
  write_env_value CEREBRO_LOG_LEVEL INFO
  write_env_value CEREBRO_LOG_FORMAT json
  write_env_value CEREBRO_DATABASE_URL "postgresql://cerebro:${DB_PASSWORD}@db:5432/cerebro"
  write_env_value CEREBRO_READ_REPLICA_URL "$READ_REPLICA_URL"
  write_env_value CEREBRO_ALLOW_NON_REPLICA_READONLY_DB false
  write_env_value CEREBRO_SQL_MAX_CONNECTIONS 5
  write_env_value CEREBRO_SQL_MAX_OUTPUT_BYTES 65536
  write_env_value CEREBRO_SLACK_APP_TOKEN "$SLACK_APP_TOKEN"
  write_env_value CEREBRO_SLACK_BOT_TOKEN "$SLACK_BOT_TOKEN"
  write_env_value CEREBRO_AZURE_OPENAI_ENDPOINT "$AZURE_OPENAI_ENDPOINT"
  write_env_value CEREBRO_AZURE_OPENAI_API_KEY "$AZURE_OPENAI_API_KEY"
  write_env_value CEREBRO_AZURE_DEPLOYMENT_MAIN "$AZURE_DEPLOYMENT_MAIN"
  write_env_value CEREBRO_AZURE_DEPLOYMENT_SMALL "$AZURE_DEPLOYMENT_MAIN"
  write_env_value CEREBRO_AZURE_OPENAI_USE_RESPONSES true
  write_env_value CEREBRO_AZURE_REASONING_EFFORT medium
  write_env_value CEREBRO_ROUTER_REASONING_EFFORT low
  write_env_value CEREBRO_AZURE_MAX_OUTPUT_TOKENS 4096
  write_env_value CEREBRO_GENERAL_MAX_WORDS 180
  write_env_value OPENAI_AGENTS_DONT_LOG_MODEL_DATA 1
  write_env_value OPENAI_AGENTS_DONT_LOG_TOOL_DATA 1
  write_env_value CEREBRO_GLOBAL_MODE "$GLOBAL_MODE"
  write_env_value CEREBRO_PAYMENT_WRITES_ENABLED false
  write_env_value CEREBRO_HOLD_WRITES_ENABLED false
  write_env_value CEREBRO_EXTERNAL_TRACING_ENABLED false
  write_env_value CEREBRO_MAX_AGENT_TURNS 8
  write_env_value CEREBRO_MAX_TOOL_CALLS 20
  write_env_value CEREBRO_AGENT_TIMEOUT_SECONDS 180
  write_env_value CEREBRO_SQL_STATEMENT_TIMEOUT_SECONDS 15
  write_env_value CEREBRO_SQL_MAX_ROWS 200
  write_env_value CEREBRO_MAX_IMAGES 4
  write_env_value CEREBRO_MAX_IMAGE_BYTES 8388608
  write_env_value CEREBRO_MAX_IMAGE_PIXELS 25000000
  write_env_value CEREBRO_SLACK_FILE_TIMEOUT_SECONDS 15
  write_env_value CEREBRO_SLACK_IMAGE_BATCH_TIMEOUT_SECONDS 30
  write_env_value CEREBRO_IMAGE_TEMP_ROOT /tmp/cerebro-images
  write_env_value CEREBRO_SLACK_DELIVERY_MAX_ATTEMPTS 3
  write_env_value CEREBRO_READINESS_PROFILE pilot
  write_env_value CEREBRO_WORKER_CONCURRENCY 2
  write_env_value CEREBRO_RUNTIME_HEARTBEAT_SECONDS 15
  write_env_value CEREBRO_RUNTIME_STALE_SECONDS 45
  if [ -n "$PUBLIC_HOSTNAME" ]; then
    write_env_value CEREBRO_PUBLIC_URL "https://$PUBLIC_HOSTNAME"
    # Cerebro validates the monolith's Authentik token itself. Caddy only refuses requests
    # with no bearer credential at all; it cannot check a signature, issuer, or audience.
    write_env_value CEREBRO_BANK_INGESTION_ENABLED true
    write_env_value CEREBRO_BANK_INGESTION_ISSUER "$BANK_INGESTION_ISSUER"
    write_env_value CEREBRO_BANK_INGESTION_AUDIENCE "$BANK_INGESTION_AUDIENCE"
    write_env_value CEREBRO_BANK_INGESTION_CLIENT_ID "$BANK_INGESTION_CLIENT_ID"
  else
    write_env_value CEREBRO_PUBLIC_URL http://127.0.0.1:8000
    write_env_value CEREBRO_BANK_INGESTION_ENABLED false
  fi
  if [ -n "$RUUF_AGENTS_URL" ]; then
    write_env_value RUUF_AGENTS_URL "$RUUF_AGENTS_URL"
    write_env_value RUUF_AGENTS_M2M_CLIENT_ID "$RUUF_AGENTS_M2M_CLIENT_ID"
    write_env_value RUUF_AGENTS_M2M_CLIENT_SECRET "$RUUF_AGENTS_M2M_CLIENT_SECRET"
    if [ -n "$RUUF_AGENTS_M2M_SCOPE" ]; then
      write_env_value RUUF_AGENTS_M2M_SCOPE "$RUUF_AGENTS_M2M_SCOPE"
    fi
  fi
} > "$runtime_tmp"
chmod 0600 "$runtime_tmp"
mv "$runtime_tmp" "$RUNTIME_ENV"

compose_tmp=$(mktemp /etc/cerebro-agent/compose.env.XXXXXX)
{
  printf 'CEREBRO_IMAGE_REPOSITORY=%s\n' "$CEREBRO_IMAGE_REPOSITORY"
  printf 'IMAGE_TAG=%s\n' "$IMAGE_TAG"
  printf 'CEREBRO_DB_PASSWORD=%s\n' "$DB_PASSWORD"
  printf 'CEREBRO_WEB_MEM=512m\n'
  printf 'CEREBRO_CONTROL_WORKER_MEM=512m\n'
  printf 'CEREBRO_AGENT_WORKER_MEM=1536m\n'
  printf 'CEREBRO_SLACK_MEM=384m\n'
  printf 'CEREBRO_DB_MEM=1024m\n'
  printf 'CEREBRO_CADDY_MEM=256m\n'
  # Empty unless a hostname was seeded, which is what keeps the caddy service out of the
  # Compose project entirely on a private deployment.
  printf 'COMPOSE_PROFILES=%s\n' "$INGRESS_PROFILE"
  printf 'CEREBRO_PUBLIC_HOSTNAME=%s\n' "$PUBLIC_HOSTNAME"
  printf 'CEREBRO_ACME_EMAIL=%s\n' "$ACME_EMAIL"
} > "$compose_tmp"
chmod 0600 "$compose_tmp"
mv "$compose_tmp" "$COMPOSE_ENV"

new_hash=$(sha256sum "$RUNTIME_ENV" "$COMPOSE_ENV" | sha256sum | cut -d' ' -f1)
/usr/local/sbin/cerebro-registry-login.sh
systemctl enable --now cerebro-agent-backup.timer >/dev/null

if [ "$old_hash" != "$new_hash" ]; then
  log "configuration changed; performing a drained Compose update"
  CEREBRO_FORCE_DEPLOY=1 /usr/local/bin/cerebro-agent-update.sh
else
  log "configuration unchanged; checking the reviewed image"
  /usr/local/bin/cerebro-agent-update.sh
fi

# Only now let the timer follow the configured tag again.
systemctl enable --now cerebro-agent-update.timer >/dev/null
log "runtime is ready"
