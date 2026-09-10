# Integrations and external setup

## Slack

Use the existing founder-controlled [manifest](../manifest.yaml); don't remove permissions/events
without approval. Socket Mode requires an app-level `xapp` token with `connections:write`
and bot `xoxb` token in `CEREBRO_SLACK_APP_TOKEN`/`CEREBRO_SLACK_BOT_TOKEN`.
Install the app, enable Socket Mode and invite it to a private FinOps channel.

Required behavior uses `app_mention`, `message.channels`, `message.groups`,
`reaction_added`, `reaction_removed`, and existing `files:read`.
Reinstall only if the issued bot token predates required grants. DMs, bot loops, assistant-panel
events, unsupported subtypes and unrelated threads are ignored. A generic message containing
the bot mention isn't processed again after `app_mention`.
Keep one Socket Mode consumer per app token during local acceptance.

Private files are resolved at run time by ID with `files.info`; authenticated downloads accept
only validated HTTPS Slack origins, manually validate redirects, enforce size/time limits,
check MIME/signature and reject animated/malformed/decompression-bomb images. Default per-file
15s, batch30s. Private per-run directory0700, files0600, generated names, cleanup on every path.
No Files API upload, stored private URL, image bytes, OCR dump or historical image resend.

## Azure

Cerebro uses OpenAI Agents SDK in-process, not a persisted Foundry agent. Ask platform for the
approved endpoint/key and **Azure deployment names**:
`CEREBRO_AZURE_OPENAI_ENDPOINT`, `CEREBRO_AZURE_OPENAI_API_KEY`,
`CEREBRO_AZURE_DEPLOYMENT_MAIN`, `CEREBRO_AZURE_DEPLOYMENT_SMALL`.

Current code defaults both deployments to `gpt-5-6-sol`; Luna was an earlier decision.
Preserve the configured Azure name rather than substituting a catalog model ID.
The adapter normalizes the endpoint to `/openai/v1/`, defaults to Responses, disables
storage/external SDK tracing/sensitive logging, and sends validated Base64 image data URLs
with high detail. `CEREBRO_AZURE_OPENAI_USE_RESPONSES=false` retains the existing Chat
Completions compatibility path; Responses-only reasoning/store settings are omitted there.

Endpoint/key both absent selects fake only in local/test. Partial configuration fails startup;
production missing Azure fails startup. Missing replica means explicit source-unavailable tools.
Do not silently change provider/model when the configured deployment is missing.
Ask platform for quota, region, owner and rotation procedure. Entra identity migration is future
work; this cleanup keeps the current approved API-key contract.

## Monolith replica

Ask the owner for host, database, port, username/password, SSL/CA requirements, network route,
and confirmation it is a dedicated read-only replica role. DSN:
`postgresql://USER:PERCENT_ENCODED_PASSWORD@HOST:PORT/DATABASE?sslmode=require`.
Percent-encode username/password components, not the entire URI; follow stricter TLS/CA settings
required by platform. Store as `CEREBRO_READ_REPLICA_URL`.

Allow CONNECT, USAGE on each application schema, and SELECT on all application tables/views the
role should expose. This role is now the access boundary for **both** specialists; review it
accordingly. Do not grant PostgreSQL catalog roles or any business writes. Default transaction read-only,
small connection limit and short statement/lock/idle timeouts. Startup verifies no unsafe role
privileges, physical recovery mode, readable relations, and the order identity anchor. Optional
shortcut dependencies missing from the replica report source-unavailable instead of blocking
exploratory SQL. A local synthetic DB is intentionally
not a replica: `CEREBRO_ALLOW_NON_REPLICA_READONLY_DB=true` is permitted only in local/test.
Run `python -m cerebro.replica.check`; expected safety/schema checks must pass.
Give platform Terraform's stable NAT `outbound_public_ip` for source allowlisting.

An operator must apply grants through the writer's approved administration workflow (never
through Cerebro or a read replica). Example placeholders, reviewed for each application schema:

```sql
GRANT CONNECT ON DATABASE application_db TO cerebro_reader;
GRANT USAGE ON SCHEMA application_schema TO cerebro_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA application_schema TO cerebro_reader;
ALTER DEFAULT PRIVILEGES FOR ROLE table_owner IN SCHEMA application_schema
  GRANT SELECT ON TABLES TO cerebro_reader;
```

Default privileges apply only to objects subsequently created by that owner; repeat for every
owner and arrange USAGE/default grants for future schemas. No grant is changed by this code.
Live discovery refreshes its metadata cache after 60 seconds. Specialized identity helpers
still use monolith `public` relations; exploratory SQL supports any readable application schema.

Vambe text is stored in `vambe_message`; historical media is unavailable. There is no implemented
generic payment mailbox source. `pagos@ruuf.cl` and `pagos@ruuf.solar` are aliases;
code convention is the latter. CRM links are built from verified order IDs at
`https://tutu.ruuf.cl/account-receivables/crm-finops/<orderId>`.

## Shared agent memory

Optional brief/targeted recall on both routes uses the shared Ruuf agent service and Authentik M2M.
See `api/src/cerebro/agent/shared_memory.py` for configuration/cache/failure handling.
The generated `memory_client.py` belongs to the upstream agent platform; change that source
upstream, not manually here. Shared memories are untrusted context, not payment evidence or
permission to write business records. Malformed/unavailable memory doesn't break investigation.
Only general keeps the existing note-writing tool; payment gets no new write capability.
Synthetic evals/preflight explicitly disable memory reads **and writes**.

## Public bank ingress: infrastructure only

Preserve the senior's Terraform/Caddy/Authentik scaffolding, but do not confuse it with a
working bank integration. **The application has no bank-movement endpoint/JWT verification yet.**
A bearer-shaped request can pass Caddy and receive application404, not202. The future authenticated,
idempotent business handler remains [roadmap](roadmap.md) work. Never enable real bank sending
on the strength of proxy/preflight checks.

A deployment without a hostname is private/outbound-only. For preparatory infrastructure,
align three values: Terraform `ingress_hostname`, runtime `CEREBRO_PUBLIC_HOSTNAME`
(Key Vault `public-hostname`), and DNS A record. Terraform optionally manages Azure DNS via
`dns_zone_name`/`dns_zone_resource_group_name`; otherwise give the zone owner
`terraform output -raw ingress_public_ip`.

Ask platform for a **separate monolith M2M client**, not the memory client. Obtain decoded
issuer/audience/authorized client-id metadata (`iss`, `aud`, `azp`) without sharing tokens.
Configure `CEREBRO_BANK_INGESTION_ISSUER`, `..._AUDIENCE`, `..._CLIENT_ID` and
`CEREBRO_ACME_EMAIL`. Confirm actual issuer mode/audience rather than deriving them.
Use `ingress_allowed_source_ranges` for known monolith egress; avoid unrestricted sources
where possible. NAT outbound address remains unchanged.

After reviewing Terraform plan/apply, confirm DNS resolves; then use the existing
`scripts/seed-secrets.sh` and `scripts/activate.sh` from
[the Terraform guide](../infra/terraform/README.md).
The seeder requires hostname/ACME/issuer/audience/client together. NSG permits443 from approved
sources and80 for ACME, not SSH/DB/health. Caddy routes only POST
`/integrations/bank-movements`; no bearer yields401, other paths/methods404. Verify certificate
hostname/expiry, closed operational ports, and preflight's optional JWKS-connectivity check.
These are infrastructure checks, not proof of authenticated payment acceptance.

Rollback listener: reseed with empty `CEREBRO_PUBLIC_HOSTNAME`, activate, confirm Caddy is gone.
Optional subsequent Terraform change empties `ingress_hostname`, removing IP/rules/managed DNS;
re-enabling may allocate a new IP. Keep certificate volumes on the retained disk.
Renewal needs DNS and port80; one VM/proxy has no failover. Future callers need a retry contract.
