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

log "waiting for the managed data disk"
for _attempt in $(seq 1 120); do
  [ -e "$DATA_LINK" ] && break
  sleep 5
done
[ -e "$DATA_LINK" ] || fail "managed data disk was not attached at LUN 0"
DATA_DEVICE=$(readlink -f "$DATA_LINK")
[ -b "$DATA_DEVICE" ] || fail "managed data disk is not a block device"

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
mkdir -p "$DATA_MOUNT/docker" "$DATA_MOUNT/backups/cerebro-agent"
chmod 0700 "$DATA_MOUNT/backups/cerebro-agent"

if [ -e /var/backups/cerebro-agent ] && [ ! -L /var/backups/cerebro-agent ]; then
  rmdir /var/backups/cerebro-agent 2>/dev/null || \
    fail "/var/backups/cerebro-agent contains unexpected local data"
fi
ln -sfn "$DATA_MOUNT/backups/cerebro-agent" /var/backups/cerebro-agent
systemctl restart docker.service

CEREBRO_BOOTSTRAP_DEFER_TIMERS=true "$DEPLOY_ROOT/bootstrap.sh" >/dev/null

IMDS_URL='http://169.254.169.254/metadata/identity/oauth2/token?api-version=2018-02-01&resource=https%3A%2F%2Fvault.azure.net'
ACCESS_TOKEN=$(curl --fail --silent --show-error --noproxy '*' \
  -H 'Metadata: true' "$IMDS_URL" | jq -er '.access_token')
[ -n "$ACCESS_TOKEN" ] || fail "managed-identity token was unavailable"

vault_secret() {
  local name=$1
  local value
  value=$(curl --fail --silent --show-error \
    -H "Authorization: Bearer $ACCESS_TOKEN" \
    "https://${CEREBRO_KEY_VAULT_NAME}.vault.azure.net/secrets/${name}?api-version=7.4" \
    | jq -er '.value') || fail "required Key Vault secret is unavailable: $name"
  case "$value" in
    *$'\n'*|*$'\r'*) fail "Key Vault secret contains a forbidden newline: $name" ;;
  esac
  printf '%s' "$value"
}

dotenv_value() {
  local escaped=${1//\\/\\\\}
  escaped=${escaped//\'/\\\'}
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
GHCR_USERNAME=$(vault_secret ghcr-username)
GHCR_TOKEN=$(vault_secret ghcr-token)
GLOBAL_MODE=$(vault_secret global-mode)
IMAGE_TAG=$(vault_secret image-tag)

[[ "$DB_PASSWORD" =~ ^[A-Za-z0-9]+$ ]] || fail "database password must be alphanumeric"
[[ "$GLOBAL_MODE" =~ ^(off|shadow|review|apply)$ ]] || fail "global mode is invalid"
[[ "$IMAGE_TAG" =~ ^[A-Za-z0-9._-]+$ ]] || fail "image tag is invalid"

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
  write_env_value CEREBRO_AZURE_MAX_OUTPUT_TOKENS 4096
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
  write_env_value CEREBRO_PUBLIC_URL http://127.0.0.1:8000
} > "$runtime_tmp"
chmod 0600 "$runtime_tmp"
mv "$runtime_tmp" "$RUNTIME_ENV"

compose_tmp=$(mktemp /etc/cerebro-agent/compose.env.XXXXXX)
{
  printf 'IMAGE_TAG=%s\n' "$IMAGE_TAG"
  printf 'CEREBRO_DB_PASSWORD=%s\n' "$DB_PASSWORD"
  printf 'CEREBRO_WEB_MEM=512m\n'
  printf 'CEREBRO_CONTROL_WORKER_MEM=512m\n'
  printf 'CEREBRO_AGENT_WORKER_MEM=1536m\n'
  printf 'CEREBRO_SLACK_MEM=384m\n'
  printf 'CEREBRO_DB_MEM=1024m\n'
} > "$compose_tmp"
chmod 0600 "$compose_tmp"
mv "$compose_tmp" "$COMPOSE_ENV"

new_hash=$(sha256sum "$RUNTIME_ENV" "$COMPOSE_ENV" | sha256sum | cut -d' ' -f1)
printf '%s' "$GHCR_TOKEN" | docker login ghcr.io --username "$GHCR_USERNAME" --password-stdin >/dev/null
systemctl enable --now cerebro-agent-update.timer cerebro-agent-backup.timer >/dev/null

if [ "$old_hash" != "$new_hash" ]; then
  log "configuration changed; performing a drained Compose update"
  CEREBRO_FORCE_DEPLOY=1 /usr/local/bin/cerebro-agent-update.sh
else
  log "configuration unchanged; checking the reviewed image"
  /usr/local/bin/cerebro-agent-update.sh
fi

log "runtime is ready"
