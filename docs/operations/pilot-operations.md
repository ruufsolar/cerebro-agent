# Pilot operations

Slice 6A provides local operational controls for the controlled FinOps pilot. It does not
send telemetry or alerts to PostHog, Slack, or another external service.

## Readiness profiles

`/health` proves only that the web process can answer. `/ready` verifies local operational
dependencies without calling Slack, Azure, or the replica on every probe.

- `foundation`: Cerebro PostgreSQL, Alembic head, and the Procrastinate schema.
- `pilot`: foundation plus complete Slack/Azure/replica settings, disabled business writes
  and external tracing, and heartbeats from `slack`, `control-worker`, and `agent-worker`.

Processes write a heartbeat every 15 seconds and are stale after 45 seconds. `off` is a
ready mode because it is the kill switch. Production uses `CEREBRO_READINESS_PROFILE=pilot`;
the credential-free local/CI foundation uses `foundation`.

## Operator commands

Run commands inside the image or from `api/` with `uv run`:

```bash
uv run python -m cerebro.ops.preflight --profile pilot
uv run python -m cerebro.ops.status --hours 24
uv run python -m cerebro.ops.status --hours 24 --json
uv run python -m cerebro.ops.pilot_gate \
  --channel C0123456789 \
  --since 2026-09-02T09:00:00-04:00 \
  --until 2026-09-02T18:00:00-04:00
```

Preflight checks the local schemas, replica safety/schema, temporary-image storage, and
Slack authentication. Add `--live-provider` only when an explicit synthetic Azure smoke
call and its cost are intended. It uses no real customer data.

Status reports aggregate active queue depth, failures, outcomes, feedback, latency,
token/tool usage, image failures, and runtime components. The pilot gate labels rows only `case_01` through
`case_10`; neither command prints customer, order, message, screenshot, or SQL content.

## Hard ten-case gate

The selected channel/time range must contain exactly ten triggering runs. Passing requires:

- ten successful, singly delivered investigations and at least four screenshot cases;
- a resolved 🧀/🔌 label for each case, at least nine positive, and no negative
  high-confidence result;
- valid structured results, successful source tools for every cited customer/evidence
  reference, and Slice 5 response-length compliance;
- zero timeouts or delivery failures;
- median end-to-end latency at most 60 seconds and nearest-rank p95 at most 120 seconds;
- average input/output use at most 50,000/1,000 tokens and per-run maxima of
  100,000/2,000 tokens.

Multiple 🧀 reactions remain one positive label. Any active 🔌 makes the case negative. An
active 🧀 and 🔌 on the same answer is a conflict and must be resolved before rerunning the
gate. FinOps signoff remains a separate manual release decision.

## Structured logs and watchdog

JSON logs contain allowlisted lifecycle categories, safe internal IDs, statuses, outcome,
confidence, versions, durations, counts, and categorical error types. Arbitrary log
messages and exception strings are discarded. Customer data, Slack payload/text, Vambe
content, SQL/results, image data/paths, URLs, and credentials are forbidden.

Every five minutes the control queue logs aggregate warnings for events/outputs older than
two minutes, queued runs older than five minutes, running runs older than 240 seconds,
recent failures, and stale component rows. There is no external alert destination in V0.

## Retained data and manual cleanup

Cerebro retains sanitized Slack event envelopes, transcript text and attachment metadata,
run inputs/results, selected customer/order evidence, safe tool audits, rendered outputs,
feedback, and job state in its own access-controlled PostgreSQL database. Runtime
heartbeats contain no customer data. Screenshot bytes remain ephemeral under
`/tmp/cerebro-images` and must not survive a run.

There is deliberately no automatic V0 retention job. For an approved cutoff, take the
normal Cerebro backup, run a count-only dry run, and then delete the workflow graph in one
transaction. Never apply this to the monolith replica.

```sql
BEGIN;

CREATE TEMP TABLE purge_conversations ON COMMIT DROP AS
SELECT id FROM conversation WHERE created_at < TIMESTAMPTZ 'approved-cutoff';

CREATE TEMP TABLE purge_runs ON COMMIT DROP AS
SELECT id FROM agent_run WHERE conversation_id IN (SELECT id FROM purge_conversations);

DELETE FROM feedback WHERE conversation_id IN (SELECT id FROM purge_conversations);
DELETE FROM slack_output WHERE conversation_id IN (SELECT id FROM purge_conversations);
DELETE FROM tool_call WHERE agent_run_id IN (SELECT id FROM purge_runs);
DELETE FROM agent_run WHERE id IN (SELECT id FROM purge_runs);
DELETE FROM message WHERE conversation_id IN (SELECT id FROM purge_conversations);
DELETE FROM conversation WHERE id IN (SELECT id FROM purge_conversations);
DELETE FROM slack_event WHERE received_at < TIMESTAMPTZ 'approved-cutoff';

COMMIT;
```

Replace `approved-cutoff` with an explicitly reviewed timestamp. First run the corresponding
`SELECT count(*)` queries, verify the backup, and keep the terminal output aggregate. A
failed statement rolls the transaction back; do not use `TRUNCATE`, cascade deletion, or an
unbounded cutoff.
