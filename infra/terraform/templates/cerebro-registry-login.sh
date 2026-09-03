#!/bin/bash
# Authenticate Docker to Azure Container Registry using the VM's managed identity.
# ACR refresh tokens are short lived, so this runs before every pull rather than once
# at bootstrap. No registry password exists on the host or in Key Vault.
set -euo pipefail
umask 077

readonly AZURE_ENV=/etc/cerebro-agent/azure.env

fail() {
  printf 'cerebro-registry-login: ERROR: %s\n' "$1" >&2
  exit 1
}

[ -r "$AZURE_ENV" ] || fail "Azure bootstrap configuration is missing"
# shellcheck disable=SC1090
source "$AZURE_ENV"
[ -n "${CEREBRO_REGISTRY_LOGIN_SERVER:-}" ] || fail "registry login server is missing"
[ -n "${CEREBRO_AZURE_TENANT_ID:-}" ] || fail "tenant id is missing"

readonly IMDS_URL='http://169.254.169.254/metadata/identity/oauth2/token?api-version=2018-02-01&resource=https%3A%2F%2Fmanagement.azure.com%2F'
access_token=$(curl --fail --silent --show-error --noproxy '*' \
  -H 'Metadata: true' "$IMDS_URL" | jq -er '.access_token') ||
  fail "managed-identity token was unavailable"

# Exchange the Entra token for an ACR refresh token. The null GUID is the documented
# username for this flow; the refresh token is the password.
refresh_token=$(curl --fail --silent --show-error \
  -X POST "https://${CEREBRO_REGISTRY_LOGIN_SERVER}/oauth2/exchange" \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  --data-urlencode 'grant_type=access_token' \
  --data-urlencode "service=${CEREBRO_REGISTRY_LOGIN_SERVER}" \
  --data-urlencode "tenant=${CEREBRO_AZURE_TENANT_ID}" \
  --data-urlencode "access_token=${access_token}" | jq -er '.refresh_token') ||
  fail "registry token exchange failed"

printf '%s' "$refresh_token" | docker login "$CEREBRO_REGISTRY_LOGIN_SERVER" \
  --username 00000000-0000-0000-0000-000000000000 --password-stdin >/dev/null ||
  fail "docker login to the registry failed"
