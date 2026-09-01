# Runtime flows

## V0 mention

1. Slack sends `app_mention` over Socket Mode.
2. The listener acknowledges immediately and inserts `slack_event` by Slack event ID.
3. It resolves `(channel, root thread_ts)` to one `conversation`, stores the message and
   safe file metadata, and enqueues one run.
4. In `review`/`apply`, the worker sets native Slack status. It builds typed input from the
   ordered stored transcript; accepted image attachments are metadata/counts only and
   `image_paths` is empty.
5. The Agents SDK runner autonomously calls bounded read tools. Candidate search uses the
   replica; final recommendations require a separate deterministic verification call.
   Without Azure the fake runner remains available, and without a replica the real runner
   receives explicit source-unavailable observations.
6. Code renders Spanish test prose, inserts `slack_output` with an idempotency key, and
   sends one reply in the original thread using the output UUID as `client_msg_id`.
7. A newer human message cancels an older run before delivery. Successful replies clear
   native status naturally; cancellation/failure clears it explicitly.

Repeated Slack delivery does not create a second event, message, run, or output.

## Thread follow-up

`message.channels` or `message.groups` is accepted only when it belongs to a known Cerebro
thread and is from a human. It is appended to the conversation and may enqueue a new run.
It never answers in the channel root or creates a new surface.

## Feedback

On `reaction_added`, only reactions to a known Cerebro output count. 🧀 records positive
feedback. 🔌 records negative feedback and posts at most one in-character reply for that
feedback identity. `reaction_removed` deactivates the row.

## Failure

- Unsupported/malformed files: retain no bytes/URLs and continue with accepted metadata.
- Tool rejection/timeout: record bounded error, continue if useful, lower confidence.
- Model timeout/budget exhaustion: give FinOps a concise failure/unknown response.
- Slack send failure: retry the same outbox row/idempotency key.
- Worker interruption: Procrastinate retries; durable event/run state prevents duplication.
- Replica unavailable: do not invent results and do not fall back to the primary DB.

## Future automatic bank flow

Bank ingestion will insert a stable movement identity and enqueue the same investigation
core. The difference is trigger and proactive destination channel, not a second matching
algorithm. WhatsApp/email evidence must never create another payment run by itself.
