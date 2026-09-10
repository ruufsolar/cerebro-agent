# Product and current state

Cerebro is an independent Python back-office agent for internal FinOps. It is already used
in production; this describes implemented behavior, not a claim that a formal accuracy
certification or pilot has passed.

## Available now

- Slack mentions and human follow-ups in known threads; replies stay in the same thread.
- Grounded incoming-payment identification against the monolith read replica, including
  candidate-scoped Vambe text and triggering screenshots.
- General conversation and read-only FinOps questions, with Cerebro's restrained personality.
- Native progress status, durable jobs/outbox, 🧀/🔌 feedback, local operational reports.
- Azure VM/Compose deployment with the existing senior-maintained automatic delivery.
- Optional shared agent memory for general conversation. This is an external side effect,
  unlike replica reads; it does not authorize payment or hold changes.

## Operating modes

`CEREBRO_GLOBAL_MODE=enabled` accepts work and replies. `off` is the kill switch:
acknowledge supported events but ignore them, cancel queued investigations and pending outputs.
It is checked at ingestion, processing, execution, and delivery. A process restart is required
after changing configuration; this is not an instantaneous distributed cancellation switch.
An already in-flight network request may finish.

`review` remains an alias for `enabled`, so existing deployment secrets continue to work.
`shadow` and `apply` are retired and rejected at startup. There is no write mode or
capability registry: the tools actually provided by the application define authority.
No payment/hold write tools exist.

## Payment contract

Evidence precedence: installation address in the glosa, customer/transferor identity,
exact outstanding amount, then contextual Vambe evidence. Contradictions override optimism.

- `matched`: one verified customer, high or medium confidence. Prefer an eligible receivable;
  a robust unique identity can match without one, but say the receivable could not be verified.
- `ambiguous`: no recommendation, optionally up to three verified plausible alternatives.
- `no_customer_found`: an available, conclusive identity search found no eligible candidate.
  This does not mean supplier payment, refund, or internal transfer. Amount-only searches
  cannot establish this conclusively.
- Legacy stored `out_of_scope` results still decode; general requests now have their own route.

High requires a complete normalized installation address, including complete numeric tokens,
without contradiction. Verified identity supports medium; a single name fragment or amount alone
does not. A Vambe keyword hit is only a mention, not confirmation of payment.

Outstanding balance subtracts active same-currency payments and recognized losses. Prefer
uncancelled client-debtor/Ruuf-recipient ARs tied to eligible installations with a positive balance.
Smaller amounts may be partial payments; larger amounts or currency mismatches contradict that AR.
CLP, USD and CLF (UF) are distinct. No FX conversion or global scan of all larger ARs.
The first transfer without a glosa and from a third-party name may correctly remain “no sé”.

## Slack response and privacy

Payment replies start with `Resultado`, with no banner. Include a verified customer/CRM link
when available, a readable AR description, categorical confidence, a short “Por qué” and
important missing checks. No raw database identifiers or tool-by-tool narration.

- Match: at most six nonempty lines and about 110 Spanish words.
- Ambiguous/no customer: at most four lines and 75 words; alternatives may raise the word cap to 130.
- Legacy out-of-scope: two lines/40 words.
- General: approximately 180 words, complete sentences, Spanish by default; follow a clear
  language request. At most one restrained character flourish.

Install Cerebro only in private internal channels. There is no code-enforced channel/member
allowlist or PII masking. General answers may expose approved customer data; Slack and stored
transcripts consequently retain it. Logs must not.

Only static PNG/JPEG/WebP screenshots on the triggering message are analyzed: four files,
8 MiB each, 25 megapixels by default. Historical images are placeholders. Partial failures
are explicit. No PDFs, GIF/HEIC, animated images, customer contact, email retrieval, payment
registration, holds, or automatic bank processing are implemented.

Use [agent behavior](agent-behavior.md) for grounding and personality,
[integrations](integrations.md) for setup, and [roadmap](roadmap.md) for deferred scope.
