#!/bin/bash
set -euo pipefail

COMPOSE=(docker compose -f /etc/cerebro-agent/compose.yml --env-file /etc/cerebro-agent/compose.env)
IMAGE_TAG=$(grep -E '^IMAGE_TAG=' /etc/cerebro-agent/compose.env | cut -d= -f2 || true)
IMAGE="ghcr.io/ruufsolar/cerebro-agent:${IMAGE_TAG:-main}"
ROLLBACK_TAG="ghcr.io/ruufsolar/cerebro-agent:last-good"
DRAIN_TIMEOUT_S=180
HEALTH_TIMEOUT_S=120

before=$(docker image inspect "$IMAGE" --format '{{.Id}}' 2>/dev/null || echo none)
"${COMPOSE[@]}" pull --quiet || echo "cerebro-agent: pull failed; keeping local images"
after=$(docker image inspect "$IMAGE" --format '{{.Id}}' 2>/dev/null || echo none)

if [ "$before" == "$after" ]; then
  exit 0
fi

running_jobs() {
  "${COMPOSE[@]}" exec -T db psql -U cerebro -d cerebro -tA \
    -c "SELECT count(*) FROM procrastinate_jobs WHERE status = 'doing'" 2>/dev/null \
    | tr -d '[:space:]' || echo 0
}

waited=0
while [ "$waited" -lt "$DRAIN_TIMEOUT_S" ]; do
  busy=$(running_jobs)
  if [ -z "$busy" ] || [ "$busy" == "0" ]; then
    break
  fi
  echo "cerebro-agent: waiting for $busy in-flight job(s) (${waited}s)"
  sleep 10
  waited=$((waited + 10))
done

if [ "$before" != "none" ]; then
  docker tag "$before" "$ROLLBACK_TAG"
fi

"${COMPOSE[@]}" up -d --remove-orphans

waited=0
until curl -fsS --max-time 3 http://127.0.0.1:8010/health >/dev/null 2>&1; do
  if [ "$waited" -ge "$HEALTH_TIMEOUT_S" ]; then
    echo "cerebro-agent: unhealthy after deploy; use IMAGE_TAG=last-good to roll back" >&2
    exit 1
  fi
  sleep 5
  waited=$((waited + 5))
done

docker image prune -f >/dev/null
echo "cerebro-agent: deploy complete ($after)"
