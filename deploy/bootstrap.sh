#!/bin/bash
# One-time setup on an approved Cerebro VM. Run as root from a reviewed checkout or cloud-init.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if ! docker compose version >/dev/null 2>&1; then
  echo "ERROR: Docker with the compose plugin is required" >&2
  exit 1
fi

mkdir -p /etc/cerebro-agent /var/backups/cerebro-agent
install -m 644 "$HERE/compose.yml" /etc/cerebro-agent/compose.yml
install -m 755 "$HERE/cerebro-agent-update.sh" /usr/local/bin/cerebro-agent-update.sh
install -m 755 "$HERE/cerebro-agent-backup.sh" /usr/local/bin/cerebro-agent-backup.sh

[ -f /etc/cerebro-agent/env ] || install -m 600 "$HERE/env.example" /etc/cerebro-agent/env
[ -f /etc/cerebro-agent/compose.env ] || \
  install -m 600 "$HERE/compose.env.example" /etc/cerebro-agent/compose.env

install -m 644 "$HERE"/systemd/cerebro-agent-*.service \
  "$HERE"/systemd/cerebro-agent-*.timer /etc/systemd/system/
systemctl daemon-reload
if [ "${CEREBRO_BOOTSTRAP_DEFER_TIMERS:-false}" != "true" ]; then
  systemctl enable --now cerebro-agent-update.timer cerebro-agent-backup.timer
fi

echo "Bootstrap complete. Fill /etc/cerebro-agent/env and compose.env, authenticate the registry,"
echo "then run /usr/local/bin/cerebro-agent-update.sh and curl localhost:8010/ready."
