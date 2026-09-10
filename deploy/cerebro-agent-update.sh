#!/bin/bash
set -euo pipefail

LOCK_WAIT_S=${CEREBRO_DEPLOY_LOCK_WAIT_SECONDS:-300}
exec 9>/run/lock/cerebro-agent-update.lock
if ! flock -w "$LOCK_WAIT_S" 9; then
  echo "cerebro-agent: another deployment still holds the update lock" >&2
  exit 1
fi

COMPOSE=(docker compose -f /etc/cerebro-agent/compose.yml --env-file /etc/cerebro-agent/compose.env)
IMAGE_TAG=$(grep -E '^IMAGE_TAG=' /etc/cerebro-agent/compose.env | cut -d= -f2 || true)
IMAGE_REPOSITORY=$(grep -E '^CEREBRO_IMAGE_REPOSITORY=' /etc/cerebro-agent/compose.env | cut -d= -f2 || true)
IMAGE="${IMAGE_REPOSITORY:-cerebro-agent}:${IMAGE_TAG:-main}"
ROLLBACK_TAG="${IMAGE_REPOSITORY:-cerebro-agent}:last-good"

# ACR refresh tokens expire well inside this timer's lifetime, so re-authenticate on
# every run rather than relying on the login performed during bootstrap.
if [ -x /usr/local/sbin/cerebro-registry-login.sh ]; then
  /usr/local/sbin/cerebro-registry-login.sh || \
    echo "cerebro-agent: registry login failed; relying on local images" >&2
fi
DRAIN_TIMEOUT_S=240
HEALTH_TIMEOUT_S=120
FORCE_DEPLOY=${CEREBRO_FORCE_DEPLOY:-0}

# Everything that can create new work. Slack ingestion always; the public bank-movements
# ingress too, on a deployment that has one. Stopping both is what makes the drain below
# converge instead of racing an event that arrives while the workers are being replaced.
# When ingress is off the caddy service is not in the project and this stays just slack.
INGRESS=(slack)
if "${COMPOSE[@]}" config --services 2>/dev/null | grep -qx caddy; then
  INGRESS+=(caddy)
fi

# docker image inspect can print a blank line before failing on a missing image, so strip
# whitespace and treat empty as absent rather than trusting its exit status alone.
image_id() {
  docker image inspect "$1" --format '{{.Id}}' 2>/dev/null | tr -d '[:space:]' || true
}
before=$(image_id "$IMAGE")
before=${before:-none}
"${COMPOSE[@]}" pull --quiet || echo "cerebro-agent: pull failed; keeping local images"
after=$(image_id "$IMAGE")
after=${after:-none}

if [ "$before" == "$after" ] && [ "$after" != "none" ] && [ "$FORCE_DEPLOY" != "1" ] \
  && curl -fsS --max-time 3 http://127.0.0.1:8010/ready >/dev/null 2>&1; then
  exit 0
fi

# Count only in-flight jobs that a live worker is actually running. A job whose worker
# died without finishing it (worker_id null, or a heartbeat older than the worker's own
# stall timeout) is orphaned: nothing will ever complete it, so waiting on it would block
# every deploy until someone fixed the row by hand. Workers heartbeat every 10s.
running_jobs() {
  "${COMPOSE[@]}" exec -T db psql -U cerebro -d cerebro -tA -c "
    SELECT count(*) FROM procrastinate_jobs j
      JOIN procrastinate_workers w ON w.id = j.worker_id
     WHERE j.status = 'doing' AND w.last_heartbeat > now() - interval '60 seconds'" 2>/dev/null \
    | tr -d '[:space:]'
}

orphaned_jobs() {
  "${COMPOSE[@]}" exec -T db psql -U cerebro -d cerebro -tA -c "
    SELECT count(*) FROM procrastinate_jobs j
      LEFT JOIN procrastinate_workers w ON w.id = j.worker_id
     WHERE j.status = 'doing'
       AND (w.id IS NULL OR w.last_heartbeat <= now() - interval '60 seconds')" 2>/dev/null \
    | tr -d '[:space:]' || echo 0
}

orphans=$(orphaned_jobs)
if [ -n "$orphans" ] && [ "$orphans" != "0" ]; then
  echo "cerebro-agent: ignoring $orphans orphaned job(s) left in 'doing' by a dead worker" >&2
fi

# Stop new ingestion first. Existing control/agent workers stay alive while the
# already-accepted work drains, so the update never deliberately cancels an investigation.
# A bank event sent during this window is refused at the TCP level rather than accepted and
# then abandoned, which is the answer a client retrying a 202 contract can act on.
"${COMPOSE[@]}" stop --timeout "$DRAIN_TIMEOUT_S" "${INGRESS[@]}"

# Failure to read the queue is not proof that it is empty. Resume the old services
# on any drain error, without changing the senior-maintained activation/CD flow.
resume_on_drain_error() {
  echo "cerebro-agent: drain failed; resuming existing services" >&2
  "${COMPOSE[@]}" start control-worker agent-worker "${INGRESS[@]}" || true
}
trap resume_on_drain_error ERR
checked_running_jobs() {
  local count
  count=$(running_jobs) || return 1
  [[ "$count" =~ ^[0-9]+$ ]] || return 1
  printf '%s' "$count"
}

waited=0
while [ "$waited" -lt "$DRAIN_TIMEOUT_S" ]; do
  busy=$(checked_running_jobs)
  if [ "$busy" == "0" ]; then
    break
  fi
  echo "cerebro-agent: waiting for $busy in-flight job(s) (${waited}s)"
  sleep 10
  waited=$((waited + 10))
done

busy=$(checked_running_jobs)
if [ -n "$busy" ] && [ "$busy" != "0" ]; then
  echo "cerebro-agent: aborting deploy with $busy in-flight job(s) after ${DRAIN_TIMEOUT_S}s" >&2
  "${COMPOSE[@]}" start "${INGRESS[@]}"
  exit 1
fi

# No job is in flight now. Stop both consumers before replacing containers, closing the
# race between the final drain check and Compose recreation. Queued jobs remain durable.
"${COMPOSE[@]}" stop --timeout "$DRAIN_TIMEOUT_S" control-worker agent-worker

busy=$(checked_running_jobs)
if [ -n "$busy" ] && [ "$busy" != "0" ]; then
  echo "cerebro-agent: aborting deploy because work restarted during worker drain" >&2
  "${COMPOSE[@]}" start control-worker agent-worker "${INGRESS[@]}"
  exit 1
fi

# last-good must be the image production is running now, not an earlier local copy of the
trap - ERR
# tag being deployed; on a normal deploy of a new tag the latter does not exist yet.
running=$(docker inspect --format '{{.Image}}' cerebro-agent-web-1 2>/dev/null | tr -d '[:space:]' || true)
if [ -n "$running" ]; then
  docker tag "$running" "$ROLLBACK_TAG"
fi

"${COMPOSE[@]}" up -d --remove-orphans

waited=0
until curl -fsS --max-time 3 http://127.0.0.1:8010/ready >/dev/null 2>&1; do
  if [ "$waited" -ge "$HEALTH_TIMEOUT_S" ]; then
    echo "cerebro-agent: unhealthy after deploy; use IMAGE_TAG=last-good to roll back" >&2
    exit 1
  fi
  sleep 5
  waited=$((waited + 5))
done

docker image prune -f >/dev/null
echo "cerebro-agent: deploy complete ($after)"
