# Product requirements

## Product direction

Cerebro will grow into FinOps' internal back-office agent for payment reception,
reconciliation, collection decisions, and holds. It is a separate service so its tools,
memory, permissions, and release cycle can evolve independently from the monolith.

The intended production flow is eventually:

1. A movement reaches the bank statement and triggers Cerebro.
2. Cerebro investigates who paid.
3. Cerebro proposes a match to FinOps in Slack with evidence and confidence.
4. FinOps approves, corrects the customer, or marks it as not a customer payment.
5. Cerebro creates the `AccountReceivablePayment` through an approved write API.

## V0 scope

V0 supports exactly one task. Any member can mention `@cerebro` in a channel where the app
is installed and ask, in natural language, which customer an incoming deposit belongs to.
The message may contain a transcription, screenshots, or both. Cerebro investigates and
answers in the same Slack thread, in Spanish by default.

V0 may:

- read mention text and supported image attachments;
- read thread follow-ups;
- query explicitly scoped monolith data through a read-only replica;
- search stored Vambe messages;
- read curated domain knowledge;
- post a Slack thread reply and temporary native Slack status;
- record runs, tool calls, delivery attempts, and reactions in Cerebro's own database;
- emit metadata-only operational analytics to Cerebro's PostHog project.

V0 may not:

- register or reverse payments;
- create, remove, or alter holds;
- message a customer;
- treat WhatsApp or email as a payment trigger;
- ingest PDFs;
- run on automatic bank movements;
- mutate the replica or call an unrestricted write endpoint;
- answer unrelated general-purpose tasks.

If the request is not payment identification, Cerebro should briefly state its current
scope and remain in the thread.

## Identification heuristic

Investigate in this precedence order. Later evidence can reduce confidence but should not
silently outrank a stronger verified signal.

1. **Transfer description/glosa.** Match an installation address supplied by the customer.
2. **Transferor name.** Match the person or business name to a customer.
3. **Exact outstanding balance.** Compare the deposit to what remains unpaid, particularly
   the second transfer completing the initial 70% or the final 30%.
4. **Context evidence.** Search Vambe/WhatsApp and, when a generic email source exists,
   messages to `pagos@ruuf.solar`. Context supports a conclusion but is not a trigger.

The current monolith stores Vambe text and message metadata. The webhook does not preserve
a generally usable Vambe attachment URL, so V0 can use stored text saying that a receipt
was sent but cannot inspect that historical receipt image.

There is no generic persisted `pagos@ruuf.solar` mailbox today; the existing inbound email
path is specialized. Email search therefore remains unavailable until a read API or
normalized storage source is added.

## Candidate universe

Start with customer-debtor, Ruuf-recipient receivables that are not cancelled, have a
positive outstanding balance, use CLP in the normal flow, and belong to an active/relevant
installation. Calculate outstanding as original amount minus registered payments and
losses. Do not assume every AR is CLP: the currency enum also supports USD and CLF (UF).

This is a configurable starting filter, not hidden prompt text. The exact tables and rules
live in `knowledge/data-scope.yaml` and can be reviewed manually.

## Expected reply

The reply must include:

- recommended customer and FinOps CRM URL, or an explicit “no encontré un cliente”;
- one-line human description of the likely AR, never merely its database ID;
- categorical confidence;
- a concise paragraph explaining what tied the payment to the candidate and what could not
  be verified;
- contradictory evidence where relevant;
- alternative candidates only when they remain reasonably plausible, ranked best first.

If the first transfer has no glosa and a different transferor name, Cerebro must not guess.
It should say it does not know and leave the case for manual review.

## Feedback flavor

- 🧀 on Cerebro's reply means correct/useful.
- 🔌 means incorrect/unhelpful. Cerebro records negative feedback and replies once in the
  same thread with a short in-character pain reaction such as `Arrrrgghhh ⚡️☠️`.
- Removing a reaction deactivates that feedback record.

No emoji changes business data.

## Future capabilities

- Bank statement ingestion as the sole automatic detection trigger.
- FinOps confirmation/correction/non-customer disposition.
- Approval-gated `AccountReceivablePayment` creation and correction.
- Due-date investigations with verdicts: `poner hold`, `revisar más tarde`, or
  `no tengo idea, que revise FinOps`.
- Approval-gated hold creation and automatic/specified reversal.
- Proactive reports to a configured FinOps channel.
- Broader FinOps back-office tasks added one explicit capability at a time.

Customer acknowledgements remain another agent's responsibility; humans send them in V1.

## Unresolved product decisions

- What a hold blocks operationally.
- What event reverses a hold and whether reversal is automatic after payment registration.
- How a hold is repaired when its payment association was later found wrong.
- Generic payment-email ingestion/storage contract.
- Bank movement source contract and stable idempotency key.
- Final retention periods for screenshots, raw Slack payloads, and tool results.
