#!/bin/bash
set -euo pipefail

COMPOSE=(docker compose -f /etc/cerebro-agent/compose.yml --env-file /etc/cerebro-agent/compose.env)
BACKUP_DIR=/var/backups/cerebro-agent

mkdir -p "$BACKUP_DIR"
stamp=$(date +%Y%m%d-%H%M)
target="${BACKUP_DIR}/cerebro-agent-${stamp}.dump"
partial="${target}.part"

# Dump to a .part file and rename only on success, so a failed or interrupted run can
# never leave a truncated file that looks like a restorable backup to the runbook.
trap 'rm -f "$partial"' EXIT
"${COMPOSE[@]}" exec -T db pg_dump -U cerebro -Fc cerebro > "$partial"
[ -s "$partial" ] || { echo "cerebro-agent: pg_dump produced an empty backup" >&2; exit 1; }
mv "$partial" "$target"

find "$BACKUP_DIR" -name 'cerebro-agent-*.dump' -mtime +14 -delete
find "$BACKUP_DIR" -name 'cerebro-agent-*.dump.part' -mtime +1 -delete
echo "cerebro-agent: backup written cerebro-agent-${stamp}.dump"
