# Response contract

Cerebro produces structured data first. The application validates evidence, computes
confidence, builds CRM links, and renders concise Spanish prose.

## Payment outcomes

- `matched`: exactly one verified customer with high or medium confidence. An eligible
  receivable is preferred but may be absent for a robust identity-only match; that absence must
  be explicit and no closed receivable may be presented as collectible.
- `ambiguous`: no recommendation; up to three verified ranked alternatives may be useful.
- `no_customer_found`: a conclusive available search found no eligible customer. This does
  not classify the movement as supplier, refund, or internal transfer.
- `out_of_scope`: retained only for backward compatibility with stored pre-router results.

Technical exhaustion becomes `ambiguous` plus a completion reason. Provider/configuration
failures remain failed runs.

## Grounding

Tools return opaque evidence IDs with source, kind, polarity, strength, and candidate
ownership. The model may select only IDs observed in the current run. Application code
rejects missing, cross-candidate, unverified, contradicted, or non-unique recommendations.
It owns the customer name, optional account-receivable summary, CRM URL, confidence, and prose.

High requires an exact normalized installation address without material contradiction.
Verified identity—including a customer or natural-person contract signee—supports medium.
Amount alone never produces a match. Weak/conflicting signals preserve uncertainty.

## Slack form

- Matched: at most six lines and about 110 words.
- Ambiguous/no customer: at most four lines and 75 words.
- Out of scope: at most two lines and 40 words.
- Up to three alternatives may raise the absolute limit to 130 words.

Empty sections, repeated evidence, raw identifiers, and tool-by-tool narration are omitted.
Partial image failures are folded into the missing-verification line.

Payment replies have no slice, preview, or pilot banner and begin directly with `Resultado`.

## General answers

The router must classify a request as certainly `general` before it can reach this path. The
specialist returns `{answer: string}` and the application preserves complete sentences within an
approximately 180-word limit. It answers in Spanish unless the user clearly uses another
language, leads with the answer, and may use at most one restrained Cerebro flourish. There is no
payment outcome, confidence, candidate, evidence ID, or CRM link contract on this path.

Current Ruuf/customer facts still require successful read tools. General answers may advise but
must not claim a payment, hold, customer contact, or other write happened. Image failure counts are
appended deterministically. Trailing ellipses and mid-sentence clipping are forbidden.
