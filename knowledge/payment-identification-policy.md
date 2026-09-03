# Payment identification policy

Goal: identify the customer/order most defensibly associated with an incoming deposit.

Use evidence in precedence order: (1) glosa matching installation address, (2) transferor
name matching customer, (3) exact amount matching outstanding balance, (4) contextual Vambe
or payment-email evidence. Context never becomes the eventual bank trigger.

Outstanding balance is original receivable amount minus payments and recognized losses.
Reason about partial payments. Prefer active, uncancelled customer-debtor/Ruuf-recipient ARs
with positive balance. Normal flow is CLP, but handle configured `USD` and `CLF` explicitly.

Seek contradictions and do not guess. A first transfer without glosa from a name different
from the customer is genuinely ambiguous without additional context. Return unknown/manual
review. Report a customer only with a human-readable AR description, CRM link, categorical
confidence, evidence chain, and important missing checks. Show alternatives only when they
remain reasonably plausible.

Confidence and prose are application-owned. High requires an exact normalized installation
address without a material contradiction. Verified identity can support medium confidence;
amount alone cannot produce a match. A smaller same-currency amount is a possible partial
payment, while an amount above the outstanding balance or a currency mismatch contradicts
the candidate. Never convert CLP, USD, or CLF without an authoritative exchange-rate source.
A unique exact outstanding balance corroborated by candidate-scoped Vambe payment context can
support a medium-confidence match from a third-party transfer. Vambe context alone never
verifies a customer.
