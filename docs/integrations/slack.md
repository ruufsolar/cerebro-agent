# Slack integration

## Surface contract

- Socket Mode; no inbound public webhook.
- Trigger only on explicit `@cerebro` mention in an installed/invited channel.
- Any workspace member may ask; no channel/user allowlist in V0.
- Replies and follow-ups stay in the originating thread.
- Spanish by default; honor a clear language request.
- Native status communicates investigation progress.
- Up to four images, 8 MiB each by initial recommendation; no PDF.
- 🧀 positive and 🔌 negative feedback on Cerebro messages.

## Manifest

`manifest.yaml` is founder-controlled source material. Changes should be additive unless
explicitly authorized. Phase 0 retained all supplied scopes/events and added:

- `message.groups` for private-channel thread follow-ups;
- `reaction_added` and `reaction_removed` for feedback.

Existing `groups:history` and `reactions:read` scopes cover these events. Socket Mode also
requires an app-level `connections:write` token created outside the manifest.

## Event rules

- Use Slack envelope `event_id` as ingestion idempotency identity.
- Ignore bot/subtype loops and messages outside known Cerebro threads.
- Resolve `thread_ts` to root `ts` when the mention starts a thread.
- Acknowledge first; perform slow work in a durable job.
- Store only bounded image metadata (`id`, `name`, `mimetype`, `size`). Slice 1 does not
  retain private URLs, download bytes, or populate `image_paths`.
- Treat Slack text/files as untrusted evidence.
- Use one Slack output idempotency key per run/render version and the output UUID as
  `chat.postMessage.client_msg_id`.

## Current mode behavior

- `off`: acknowledge and durably mark supported events ignored; emit nothing.
- `shadow`: store/process events and execute the fake runner; emit nothing.
- `review`: set native status and deliver the fake result in-thread.
- `apply`: identical to `review` until approval-gated write capabilities exist.

Only investigation outputs accept feedback. 🧀 records positive feedback. 🔌 records
negative feedback and creates one idempotent same-thread `Arrrrgghhh ⚡️☠️`; flavor and
error outputs cannot recursively trigger it. Reaction removal deactivates an existing row.

See [local Slack testing](../getting-started/local-slack-testing.md). Socket Mode is outbound,
so this slice does not need Tailscale or an inbound tunnel.

Reference: [Slack app quickstart and Socket Mode](https://docs.slack.dev/quickstart/),
[reaction event](https://docs.slack.dev/reference/events/reaction_added/), and
[native assistant status](https://docs.slack.dev/reference/methods/assistant.threads.setStatus/).
