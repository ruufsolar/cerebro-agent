# Local Slack testing

Slice 1 uses Slack Socket Mode: Cerebro opens an outbound WebSocket to Slack. You do not
need a public URL, port forwarding, ngrok, or Tailscale. Tailscale will become relevant only
if a later slice reaches a private replica/network endpoint from your laptop.

The response is deliberately fake. This test proves event routing, durability, threading,
status, and feedback—not customer identification.

## Before starting

1. Confirm the existing Cerebro app is installed in the Ruuf workspace and invited to a
   safe test channel.
2. Retrieve the existing app-level `xapp-…` token and bot `xoxb-…` token from the approved
   secret store. Do not paste either into chat, docs, or Git.
3. Stop or coordinate any deployed/local process using the same Socket Mode app token.
   Run only one consumer during this acceptance test so Slack does not distribute events
   to a different process.
4. Copy the environment template and restrict its permissions:

   ```bash
   cp deploy/env.example .env
   chmod 600 .env
   ```

5. Set these values in `.env`:

   ```dotenv
   CEREBRO_SLACK_APP_TOKEN=xapp-your-secret
   CEREBRO_SLACK_BOT_TOKEN=xoxb-your-secret
   CEREBRO_GLOBAL_MODE=review
   ```

Azure and replica credentials can remain empty in Slice 1.

## Start Cerebro

From the repository root:

```bash
docker compose -f deploy/compose.local.yml --profile slack up --build
```

The profile starts four services: PostgreSQL, the health/migration service, the durable
worker, and the outbound Slack Socket Mode process. Without `--profile slack`, the first
three still start and no Slack credentials are required.

In a second terminal:

```bash
curl -fsS http://localhost:8000/health
docker compose -f deploy/compose.local.yml --profile slack ps
docker compose -f deploy/compose.local.yml --profile slack logs -f slack worker
```

Health should report `"phase":"slack-shell"`; Slack logs should show a connected Socket
Mode session, and worker logs should show no failed jobs.

## Acceptance script

1. Mention `@cerebro` in the invited channel with a Spanish payment-identification question.
   You may attach a PNG/JPEG screenshot.
2. Confirm Cerebro shows native thread status and posts exactly one reply in that thread.
3. Confirm the reply says it is a test response and that live data investigation is not
   enabled. It must not claim a real customer match.
4. Reply as a human in the same thread. Confirm a new fake investigation replies in that
   thread. A message in an unrelated thread must not trigger Cerebro.
5. Add 🧀 to an investigation response. There should be no flavor reply.
6. Add 🔌 to an investigation response. Cerebro should reply once with
   `Arrrrgghhh ⚡️☠️` in the same thread. Adding 🔌 to that flavor reply must do nothing.
7. Remove a supported reaction; its feedback row should become inactive.
8. Inspect the database if needed. Stored file JSON must contain only bounded image
   metadata (`id`, `name`, `mimetype`, `size`), never `url_private`, thumbnails, or bytes.

## Mode checks

- `off`: events are acknowledged and marked ignored; no conversation, run, status, or reply.
- `shadow`: events/messages/runs are durable and the fake runner executes; no status/reply.
- `review`: status and fake result are posted.
- `apply`: currently identical to `review`; it grants no business write capability.

Restart the stack after changing `.env`. Keep `payment_writes_enabled` and
`hold_writes_enabled` false.

## Troubleshooting

- No event at all: verify Socket Mode, `xapp` token, app installation, channel invitation,
  event subscriptions, and that another consumer is not running.
- Event arrives but no answer: inspect worker logs and the `slack_event.disposition`,
  `agent_run.status`, and `slack_output.status` rows.
- Duplicate-looking behavior: check for competing consumers first, then verify the Slack
  event IDs/message timestamps; Cerebro has database uniqueness constraints at every stage.
- Status API failure: the investigation should still finish. Check `assistant:write` and
  `chat:write` scopes before reinstalling.
- Image appears ignored: only image MIME types within configured count/size limits are
  retained as metadata. Slice 1 never downloads or reads the image.

Stop with `Ctrl-C`. Compose preserves the local PostgreSQL volume for restart testing. Use
`docker compose -f deploy/compose.local.yml --profile slack down` to stop detached services.
