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
echo CEREBRO_ACTIVATE_OK
