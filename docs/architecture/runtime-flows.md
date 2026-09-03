# Runtime flows

## V0 mention

1. Slack sends `app_mention` over Socket Mode.
2. The listener acknowledges immediately and inserts `slack_event` by Slack event ID.
3. A control worker resolves `(channel, root thread_ts)` to one `conversation`, stores the
   message and safe file metadata, and enqueues one run on the isolated agent queue.
4. Before any file/model cost, the worker cancels the run if a newer human message exists.
   In `review`/`apply`, it sets native Slack status. For a real image-capable runner, only the
   triggering message's accepted screenshots are resolved, streamed, validated, and placed
   in a private per-run temporary directory; historical screenshots remain placeholders.
5. The Agents SDK runner autonomously calls bounded read tools. Candidate search uses the
   replica; final recommendations and alternatives require deterministic verification.
   Without Azure the fake runner remains available, and without a replica the real runner
   receives explicit source-unavailable observations.
6. Immediately before the model call, validated images become direct Base64 data-URL
   `input_image` content with `detail: high`. The directory is removed on success, partial
   failure, timeout, provider/tool failure, or cancellation. Only counts/categories persist.
7. Tools assign opaque evidence IDs. The model selects IDs; code validates ownership,
   contradictions, ranking, outcome, and confidence, then renders concise Spanish prose.
8. Code inserts `slack_output` with an idempotency key; a control worker sends one reply in
   the original thread using the output UUID as `client_msg_id`.
9. A newer human message cancels an older run before delivery. Successful replies clear
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

- Unsupported/malformed/oversized files: retain no bytes/URLs, continue with valid images
  and text, and state the exact unprocessed count in the final response.
- Tool rejection/timeout: record bounded error, continue if useful, lower confidence.
- Model timeout/budget exhaustion: give FinOps a concise failure/unknown response.
- Slack send failure: retry the same outbox row/idempotency key.
- Worker interruption: Procrastinate retries; durable event/run state prevents duplication.
- Replica unavailable: do not invent results and do not fall back to the primary DB.

## Future automatic bank flow

Bank ingestion will insert a stable movement identity and enqueue the same investigation
core. The difference is trigger and proactive destination channel, not a second matching
algorithm. WhatsApp/email evidence must never create another payment run by itself.
