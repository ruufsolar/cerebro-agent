# External setup checklist

Complete these independently from Phase 0. Never paste secrets into Slack, tickets, this
wiki, commits, or AI chats. The Azure production path stores them in a dedicated Key Vault;
the private VM retrieves them with managed identity and renders root-only runtime files.

## 1. Slack app

1. Go to Slack's app management, choose **Create New App → From an app manifest**, choose
   the Ruuf workspace, and paste/upload the repository `manifest.yaml`.
2. Review without removing the founder-provided scopes/features, then create the app.
3. In **Basic Information → App-Level Tokens**, generate a token named `cerebro-socket` with
   `connections:write`. Save the `xapp-…` value as `CEREBRO_SLACK_APP_TOKEN`.
4. In **OAuth & Permissions**, install/reinstall the app to the workspace. Save the Bot User
   OAuth token `xoxb-…` as `CEREBRO_SLACK_BOT_TOKEN`.
5. Confirm Event Subscriptions contains `app_mention`, `message.channels`, `message.groups`,
   `reaction_added`, and `reaction_removed` (assistant events may remain).
   Confirm OAuth scopes include the existing `files:read`; reinstall if the issued bot token
   predates that grant.
6. Invite `@cerebro` to the private FinOps channel. For V0 it may run in any channel where
   it is installed/invited; there is no user allowlist.
7. Record, as non-secret metadata, workspace/team ID, app ID, bot user ID, and pilot channel
   ID for operations/debugging.
8. Test Slice 4: mention with text, a static PNG/JPEG/WebP screenshot, one partial-invalid
   attachment batch, private-channel thread follow-up, duplicate delivery behavior, 🧀, and 🔌.

Use only one local/deployed consumer with the app-level token during acceptance testing.
Follow [local Slack testing](../getting-started/local-slack-testing.md).

Slack documents that Socket Mode avoids exposing an inbound port and requires a separate
app-level `connections:write` token: [Slack app quickstart](https://docs.slack.dev/quickstart/).

## 2. Azure OpenAI / Microsoft Foundry

1. Ask the Wattson/platform owner which Azure OpenAI resource and region are approved for
   Cerebro. Reusing the resource is fine; identify Cerebro usage through its deployment or
   service identity/config.
2. In the resource/project, confirm a deployed model that supports the Responses API and
   text + image input. Record the **deployment name**, not only the model catalog name.
3. Gather:
   - `CEREBRO_AZURE_OPENAI_ENDPOINT` (resource endpoint, without a deployment path);
   - `CEREBRO_AZURE_OPENAI_API_KEY` for the initial baseline;
   - `CEREBRO_AZURE_DEPLOYMENT_MAIN`;
   - optionally `CEREBRO_AZURE_DEPLOYMENT_SMALL`.
4. Store the key in the approved secret store/Key Vault and VM env. Restrict portal access.
   Plan Microsoft Entra workload identity as the production hardening step.
5. Verify from a secure workstation with one Responses API text call and one image-input
   call. A `400 Model not supported` means the deployment cannot serve Responses; do not
   silently switch Cerebro to a different API without reviewing the Agents SDK adapter.
6. Capture quota/rate-limit ownership and an alert contact.

Azure's v1 endpoint is `<resource>.openai.azure.com/openai/v1/`, and requests pass the
deployment name as `model`: [Azure endpoint guide](https://learn.microsoft.com/en-us/azure/ai-studio/ai-services/concepts/endpoints).

## 3. Monolith read replica

Ask the database/platform owner for:

- replica hostname, port, database, SSL requirements, and CA material;
- dedicated login `cerebro_agent` (or company naming equivalent), never a shared engineer
  or primary credential;
- `CONNECT`, schema `USAGE`, and `SELECT` only on the reviewed scope in
  `knowledge/data-scope.yaml`;
- role/session `default_transaction_read_only=on`, `statement_timeout=15s`, short lock/idle
  transaction timeouts, and a small connection limit;
- confirmation that the hostname cannot promote/reroute to a writer under this credential;
- staging/sanitized access for integration tests if available.

Store the resulting DSN as `CEREBRO_READ_REPLICA_URL`. Have the owner run a negative proof:
`CREATE`, `INSERT`, `UPDATE`, `DELETE`, and `SELECT ... FOR UPDATE` must fail. Do not grant
default privileges to every future table; update the allowlist/grants deliberately.

Before enabling the worker, run `python -m cerebro.replica.check` with the production
environment and DSN. Expected output is `replica-safe=true schema-compatible=true`.
The local synthetic database is intentionally not a physical replica and therefore requires
`CEREBRO_ALLOW_NON_REPLICA_READONLY_DB=true`; the application rejects that exception outside
`local`/`test`.

This access is required to activate Slice 3 against real data, but not for the fake Slack
shell or the synthetic fixture profile.

## 4. GitHub, container registry, and Azure runtime

1. Confirm GitHub Actions can push to this deployment's Azure Container Registry through the
   Terraform-created federated credential and the published repository variables; no
   registry secret is stored in GitHub.
2. Review and apply the [Azure Terraform stack](../../infra/terraform/README.md). It creates
   a dedicated VM rather than placing Cerebro on Wattson's host.
3. Give the Terraform `outbound_public_ip` to the replica owner for allowlisting. No VM
   public IP or inbound application port is created.
4. No registry credential is seeded; the VM pulls with its system-assigned managed identity
   and the approved runtime values, then activate through Azure Run Command.
5. Confirm pilot readiness and preflight while mode is `off`; switch explicitly to `review`
   only when the test channel and operator are ready.
6. Socket Mode needs outbound HTTPS/WebSocket access to Slack and HTTPS to Azure,
   plus network access from Cerebro only to the replica endpoint.

## Values to bring back to engineering

Do not send the values themselves in chat. Confirm only that these secret-store entries
exist: Slack app/bot tokens, Azure endpoint/key/deployment, Cerebro DB password, read-replica
DSN. Also provide non-secret workspace/app/bot/
channel IDs, Azure deployment name, endpoint hostname, quota, replica schema version/source,
and Azure subscription/region, stable outbound IP, VM/resource-group names, and Key Vault
name.

PostHog and external Agents SDK tracing are deliberately absent from V0. See ADR-008.
