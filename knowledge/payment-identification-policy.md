# Payment identification policy

Goal: identify the customer/order most defensibly associated with an incoming deposit.

Use evidence in precedence order: (1) glosa matching installation address, (2) transferor
name matching customer, (3) exact amount matching outstanding balance, (4) contextual Vambe
or payment-email evidence. Context never becomes the eventual bank trigger.

Outstanding balance is original receivable amount minus payments and recognized losses.
Reason about partial payments. Prefer active, uncancelled customer-debtor/Ruuf-recipient ARs
with positive balance. Normal flow is CLP, but handle configured `USD` and `CLF` explicitly.
Eligibility determines collectibility, not whether a customer can be investigated. Search
historical paid/cancelled records and related identities when useful, but never call them collectible.
Use normalized names, distinctive components, legal identities/signees, business relationships
and date context. After empty results, change strategy instead of repeating the same query.
Schema discovery and read-only SQL are available immediately; shared memory offers guidance,
never evidence. Verify remembered relations and declared joins against current metadata.

Seek contradictions and do not guess. A first transfer without glosa from a name different
from the customer is genuinely ambiguous without additional context. Return unknown/manual
review. Report a customer only with a human-readable AR description, CRM link, categorical
confidence, evidence chain, and important missing checks. Show alternatives only when they
remain reasonably plausible.
Search supplied evidence first. If still ambiguous, ask only the missing question most likely
to distinguish candidates, without asking again for information already provided. Never claim
no customer exists from a narrow, unavailable or truncated search.

Confidence and prose are application-owned. High requires an exact normalized installation
address without a material contradiction. Verified identity can support medium confidence;
amount alone cannot produce a match. A smaller same-currency amount is a possible partial
payment, while an amount above the outstanding balance or a currency mismatch contradicts
the candidate. Never convert CLP, USD, or CLF without an authoritative exchange-rate source.
A unique exact outstanding balance corroborated by candidate-scoped Vambe payment context can
support a medium-confidence match from a third-party transfer. Vambe context alone never
verifies a customer.
