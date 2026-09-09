#!/bin/sh
# Executed on the VM through Azure Run Command by activate.sh and by the scheduled deploy
# workflow. Run Command uses /bin/sh (dash on Ubuntu), so this must stay POSIX: no pipefail,
# no bash arrays. Run Command reports success regardless of this script's exit status, so
# callers detect success only by the sentinel printed after /ready passed.
set -eu
if ! systemctl restart cerebro-agent-bootstrap.service; then
  echo "bootstrap service failed; recent journal follows" >&2
  journalctl -u cerebro-agent-bootstrap.service --no-pager -n 40 -o cat >&2
  exit 1
fi
timeout 1200 sh -c 'until curl -fsS --max-time 3 http://127.0.0.1:8010/ready >/dev/null; do sleep 10; done'
systemctl is-active --quiet cerebro-agent-bootstrap.service
curl -fsS http://127.0.0.1:8010/ready
echo

# On a deployment with public ingress, confirm Caddy is actually serving before declaring
# success. Port 80 answers 404 for anything that is not an ACME challenge, so a 404 here is
# the proof that the listener is up; a connection failure is not. Certificate issuance
# happens on the first HTTPS request and is checked separately, from outside the VM.
COMPOSE='docker compose -f /etc/cerebro-agent/compose.yml --env-file /etc/cerebro-agent/compose.env'
if $COMPOSE config --services 2>/dev/null | grep -qx caddy; then
  timeout 120 sh -c 'until curl -sS --max-time 3 -o /dev/null http://127.0.0.1:80/ >/dev/null 2>&1; do sleep 5; done' || {
    echo "public ingress is enabled but nothing answers on port 80; recent caddy logs follow" >&2
    $COMPOSE logs --no-color --tail 40 caddy >&2 || true
    exit 1
  }
  echo "ingress=listening"
fi
echo CEREBRO_ACTIVATE_OK
