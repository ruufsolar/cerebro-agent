# Roadmap and deliberate deferrals

The shipped foundation, Slack shell, Azure runner, replica, screenshots, grounding, operational
tooling and conversational routing are described in [product](product.md).
The current cleanup removes unused rollout modes/registry and consolidates docs; it does not
deploy a release or claim a completed live quality assessment.

## Next changes should follow observed failures

Use FinOps 🧀/🔌 feedback and anonymized cases to prioritize retrieval, grounding, formatting,
latency and cost. Keep synthetic regression gates. Quality reports are optional diagnostics,
not an artificial “shell versus live” capability state.

Candidates for separate, measured work:
- Broader deterministic discovery/competitor verification and explicit result-truncation semantics.
- A genuinely validated Vambe payment-confirmation contract; keyword mentions cannot substitute.
- Better independently verified general factual grounding if the risk warrants it.
- Canonical monolith read views/APIs only where replica data is missing or inefficient.
- Further runner/retrieval module splits where tests and boundaries justify them, not a new framework.
- Entra workload identity, availability/backup-restore improvements and a deliberate retention policy.

## Automatic bank processing

The bank movement—not Vambe or email—is the single automatic trigger. The current public ingress
is only infrastructure. Implement JWT validation, event identity/deduplication, durable acceptance,
retry behavior and an approved destination channel before accepting bank events.
Reuse the investigation core rather than inventing a second matching policy.
Vambe/email remain contextual evidence, never duplicate triggers.

## Future payment actions and holds

Desired flow: bank movement → investigate → Slack proposal with evidence → FinOps approves,
corrects customer or explicitly discards non-customer movement → narrow monolith API creates
`AccountReceivablePayment`. Keep partial-payment support, current-state preconditions,
idempotency and reversal/correction. No replica write credentials.

For unpaid due accounts, propose one of: put on hold, review later (possibly incoming/unidentified
payment), or manual FinOps investigation. A proposal to FinOps is separate from notifying a customer.

Before any write implementation, decide:
- What a hold actually stops.
- What removes it after payment, and who owns removal if it is not automatic.
- What happens if the payment association was wrong and later reversed.
- Exact approval identity, scope, expiry, replay defense and repair semantics.
- Explicit non-customer discard and audit requirements.

Customer acknowledgements/hold notices belong to a human or Pinky, not current Cerebro.
No preemptive write flags or placeholder capabilities are retained. Introduce real approval
boundaries together with real write tools, in independently mergeable monolith/Cerebro changes.

PDFs, email ingestion, external telemetry/PostHog, user quotas, new dashboards, web browsing,
and broad customer-facing behavior remain out of scope. Keep private-channel installation and
raw-PII retention as conscious decisions, not accidental claims of anonymization.
