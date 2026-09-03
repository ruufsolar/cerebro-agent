# Response contract

Cerebro produces structured data first. The application validates evidence, computes
confidence, builds CRM links, and renders concise Spanish prose.

## Outcomes

- `matched`: exactly one verified customer/receivable with high or medium confidence.
- `ambiguous`: no recommendation; up to three verified ranked alternatives may be useful.
- `no_customer_found`: a conclusive available search found no eligible customer. This does
  not classify the movement as supplier, refund, or internal transfer.
- `out_of_scope`: the request is not incoming-payment identification.

Technical exhaustion becomes `ambiguous` plus a completion reason. Provider/configuration
failures remain failed runs.

## Grounding

Tools return opaque evidence IDs with source, kind, polarity, strength, and candidate
ownership. The model may select only IDs observed in the current run. Application code
rejects missing, cross-candidate, unverified, contradicted, or non-unique recommendations.
It owns the customer name, account-receivable summary, CRM URL, confidence, and prose.

High requires an exact normalized installation address without material contradiction.
Verified identity supports medium. Amount alone never produces a match. Weak/conflicting
signals preserve uncertainty.

## Slack form

- Matched: at most six lines and about 110 words.
- Ambiguous/no customer: at most four lines and 75 words.
- Out of scope: at most two lines and 40 words.
- Up to three alternatives may raise the absolute limit to 130 words.

Empty sections, repeated evidence, raw identifiers, and tool-by-tool narration are omitted.
Partial image failures are folded into the missing-verification line.
