# Local Slack testing

The Slack surface uses Socket Mode: Cerebro opens an outbound WebSocket to Slack. You do not
need a public URL, port forwarding, ngrok, or Tailscale. Tailscale will become relevant only
if a later slice reaches a private replica/network endpoint from your laptop.

With Azure credentials and a verified replica DSN, Cerebro can route payment investigations and
general FinOps conversation from text or static PNG/JPEG/WebP screenshots. Without the replica,
tools explicitly report unavailable. Without Azure, the deterministic payment fake runs and
intentionally does not download screenshots.

## Before starting

1. Confirm the existing Cerebro app is installed in the Ruuf workspace and invited to a
   safe test channel.
2. Retrieve the existing app-level `xapp-…` token and bot `xoxb-…` token from the approved
   secret store. Do not paste either into chat, docs, or Git.
   Confirm the installed bot grant includes `files:read`; reinstall the app only if its token
   predates that scope.
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
   CEREBRO_READINESS_PROFILE=pilot
   ```

Azure and replica credentials can remain empty for Slack-shell testing. To test real model
reasoning, set both Azure endpoint and API key; setting only one makes the worker fail fast.
To test real data, also set the dedicated `CEREBRO_READ_REPLICA_URL`. Production/staging
must point to a physical replica using SSL; never substitute the primary DSN.
Set `CEREBRO_AZURE_DEPLOYMENT_MAIN` to the Azure deployment serving GPT-5.6 Sol.
Set `CEREBRO_AZURE_DEPLOYMENT_SMALL` to the approved routing deployment; it may currently name the
same Sol deployment. Leaving either deployment empty fails pilot readiness.

## Start Cerebro

From the repository root:

```bash
docker compose -f deploy/compose.local.yml --profile slack up --build
```

The profile starts five services: PostgreSQL, web/migrations, isolated control and agent
workers, and outbound Slack Socket Mode. Without `--profile slack`, set readiness to
`foundation`; the other four services start without Slack credentials.

In a second terminal:

```bash
curl -fsS http://localhost:8000/health
curl -fsS http://localhost:8000/ready
docker compose -f deploy/compose.local.yml --profile slack ps
docker compose -f deploy/compose.local.yml --profile slack logs -f slack control-worker agent-worker
```

Health should report `"phase":"payment-identification-pilot"`; Slack logs should show a connected Socket
Mode session, readiness should show all three runtime components `ok`, and worker logs
should show no failed jobs.

## Acceptance script

1. Mention `@cerebro` in the invited private channel with a Spanish
   payment-identification question.
   You may attach a PNG/JPEG screenshot.
2. Confirm Cerebro shows native thread status and posts exactly one reply in that thread.
3. Without a replica, confirm it reports unavailable sources and returns `unknown`. With
   Azure + replica, confirm any recommendation links to a CRM order returned by the
   verification tool. Confirm the reply begins with `Resultado` and contains no slice/pilot banner.
4. Reply as a human in the same thread. Confirm a new investigation replies in that
   thread. A message in an unrelated thread must not trigger Cerebro.
5. Start a separate thread with a clearly general question such as `@cerebro, ¿qué diferencia
   hay entre conciliación y cobranza?`. Confirm the concise answer has no payment result fields.
6. Add 🧀 to either a payment or general response. There should be no flavor reply.
7. Add 🔌 to either response. Cerebro should reply once with
   `Arrrrgghhh ⚡️☠️` in the same thread. Adding 🔌 to that flavor reply must do nothing.
8. Remove a supported reaction; its feedback row should become inactive.
9. Inspect the database if needed. Stored file JSON must contain only bounded image
   metadata (`id`, `name`, `mimetype`, `size`) and categorical ingestion counts, never
   `url_private`, thumbnails, local paths, Base64, or bytes.
10. Attach one valid image plus a PDF, GIF, HEIC, oversized, or corrupt image. The valid image
   should still be analyzed and the concise response must state how many were not processed.
11. In the agent-worker container, confirm no run directories remain after both success and failure:

   ```bash
   docker compose -f deploy/compose.local.yml --profile slack exec agent-worker \
     find /tmp/cerebro-images -mindepth 1 -maxdepth 1 -type d -print
   ```

## Mode checks

- `off`: events are acknowledged and marked ignored; no conversation, run, status, or reply.
- `shadow`: events/messages/runs are durable and the configured runner executes; no status/reply.
- `review`: status and the structured result are posted.
- `apply`: currently identical to `review`; it grants no business write capability.

Restart the stack after changing `.env`. Keep `payment_writes_enabled` and
`hold_writes_enabled` false.

## Troubleshooting

- No event at all: verify Socket Mode, `xapp` token, app installation, channel invitation,
  event subscriptions, and that another consumer is not running.
- Database is healthy but web reports `failed to resolve host 'db'`: recreate only the
  Compose containers/network while preserving the database volume, then start again:

  ```bash
  docker compose -f deploy/compose.local.yml down --remove-orphans
  docker compose -f deploy/compose.local.yml --profile slack up --build
  ```

- Event arrives but no answer: inspect both worker logs and the `slack_event.disposition`,
  `agent_run.status`, and `slack_output.status` rows.
- 🔌 produces no reply: react to Cerebro's investigation message, not the human root message;
  then search `slack` and `control-worker` logs for `slack_feedback_recorded` or
  `slack_feedback_ignored`. If neither appears, verify the installed app has the
  `reaction_added`/`reaction_removed` subscriptions and `reactions:read`, restart after `.env`
  changes, and eliminate competing Socket Mode consumers.
- Duplicate-looking behavior: check for competing consumers first, then verify the Slack
  event IDs/message timestamps; Cerebro has database uniqueness constraints at every stage.
- Status API failure: the investigation should still finish. Check `assistant:write` and
  `chat:write` scopes before reinstalling.
- Image appears ignored: confirm `files:read`, app reinstall timing, a Slack-hosted static
  PNG/JPEG/WebP, the four-file/8 MiB limits, Azure configuration, and agent-worker logs. PDFs,
  GIFs, HEIC, external files, animated/corrupt images, and images above 25 MP are rejected.

Do not paste the output of `docker compose config` into chat or tickets: Compose expands
values from `.env`, including credentials. If a token appears in logs or shared diagnostic
output, revoke it immediately and recreate every service after updating `.env`.

Stop with `Ctrl-C`. Compose preserves the local PostgreSQL volume for restart testing. Use
`docker compose -f deploy/compose.local.yml --profile slack down` to stop detached services.
