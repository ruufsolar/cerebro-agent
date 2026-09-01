# Future bank ingestion

Bank ingestion does not exist yet and is outside V0. Its eventual movement event is the only
automatic payment-detection trigger. WhatsApp, email, or screenshots are contextual evidence
and must not independently create runs, preventing duplicates.

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
