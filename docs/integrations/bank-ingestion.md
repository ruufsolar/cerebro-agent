# Bank ingestion

Bank ingestion is the only automatic payment-detection trigger. WhatsApp, email, or
screenshots are contextual evidence and must not independently create runs, preventing
duplicates.

The transport now exists; the endpoint and its event-processing logic do not yet. The path
the monolith calls, its authentication, and how to operate it are in
[public ingress](../operations/ingress.md) and [ADR-011](../adr/011-public-bank-movement-ingress.md).

## The integration contract

| | |
|---|---|
| URL | `POST https://cerebro.ruuf.cl/integrations/bank-movements` |
| Authentication | `Authorization: Bearer <Authentik M2M access token>`, minted by the monolith's own client at `https://auth.ruuf.solar/application/o/token/` with `grant_type=client_credentials` |
| Content type | `application/json` |
| Body limit | 64 KB; a larger body is refused with `413` at the proxy |
| Success | `202 Accepted` once the event is persisted and queued. The investigation is asynchronous and its result goes to Slack, never to the response |
| No credential | `401`, refused at the proxy before anything reads the body |
| Bad credential | `401` from the application, after checking signature, `iss`, `aud`, `azp`, and expiry |
| Wrong method or path | `404`. Nothing else on the host is reachable |
| Unavailable | Refused connections during a deployment's drain window. The caller retries |

Cerebro checks that the token is signed by the configured Authentik issuer, that `aud`
matches `CEREBRO_BANK_INGESTION_AUDIENCE`, and that the authorized party is exactly
`CEREBRO_BANK_INGESTION_CLIENT_ID` — one named client, not any valid Ruuf token. The
`Authorization` header and the event body are never written to a log, at the proxy or in
the application.

The future contract needs:

- stable bank/account/movement identity for idempotency;
- booked/value timestamps and source timezone;
- signed amount, currency, transferor name/identifier/account when available;
- glosa/raw bank text;
- direction and coarse classification (customer candidate vs supplier/refund/internal);
- correction/reversal events;
- replay/backfill semantics;
- configured proactive FinOps channel.

Feed the movement into the same investigation capability as the Slack V0 trigger. Preserve
the original bank payload separately from normalized fields and never use a contextual
message as a second trigger.
