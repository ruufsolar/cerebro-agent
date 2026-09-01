#!/bin/bash
set -euo pipefail

COMPOSE=(docker compose -f /etc/cerebro-agent/compose.yml --env-file /etc/cerebro-agent/compose.env)
BACKUP_DIR=/var/backups/cerebro-agent

mkdir -p "$BACKUP_DIR"
stamp=$(date +%Y%m%d-%H%M)
"${COMPOSE[@]}" exec -T db pg_dump -U cerebro -Fc cerebro \
  > "${BACKUP_DIR}/cerebro-agent-${stamp}.dump"
find "$BACKUP_DIR" -name 'cerebro-agent-*.dump' -mtime +14 -delete
echo "cerebro-agent: backup written cerebro-agent-${stamp}.dump"
