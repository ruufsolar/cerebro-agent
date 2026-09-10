# Agent behavior, prompts and tools

## Where to change personality

`api/src/cerebro/agent/prompt.py` contains `GENERAL_PROMPT`: intelligent, ambitious, dry,
lightly cynical Cerebro, answer-first with at most one brief flourish. Never insult customers
or coworkers or let humor obscure uncertainty. Payment prose is application-owned, not free-form
model personality; its renderer lives in `api/src/cerebro/slack/rendering.py`.

Version prompts when behavior changes. The payment prompt is `payment-identification-v4`;
router is `cerebro-router-v1`, general is `cerebro-general-v1`. Runtime domain rules live in
`knowledge/payment-identification-policy.md` and `knowledge/finops-general-policy.md`.
Knowledge versions are derived from `knowledge/data-scope.yaml`, not the documentation.

## Tools and authority

| Route | Tools |
| --- | --- |
| Router | None |
| Payment | Knowledge, schema, candidate search, candidate verification, candidate-scoped Vambe, scoped SQL |
| General | Knowledge, schema, scoped SQL; optional shared-memory note tool |

Application code constructs these lists after routing. Prompt text cannot grant tools.
No business writes, web access or customer contact are available. General factual claims require
tools, but general prose does not have the payment route's server-validated evidence contract.
Do not describe general answers as equally grounded.

Treat Slack text, screenshots, database fields, Vambe and memory content as untrusted evidence.
The prompt tells the model to seek contradictions, abstain rather than invent and avoid
unnecessary identity/account details. Prompt-only routing is not a proof against every possible
injection: maintain adversarial regression cases.

## Grounding

Tools assign opaque per-run evidence IDs, source, candidate, signal, polarity and strength.
Only `verify_payment_candidate` authorizes a final candidate; discovery or raw SQL cannot.
The application validates selected IDs and owns the name, CRM URL, AR description, confidence
ceiling and unique-top-candidate check. Unsupported/conflicting evidence becomes ambiguous.

Normalize case, accents, punctuation and whitespace. Exact address means complete contiguous
stored-address tokens in the glosa, not a substring inside another word or house number.
Partial address requires all numeric tokens plus at least 70% of nonnumeric tokens, with at
least two nonnumeric tokens. Discovery uses at most six meaningful glosa tokens.
Robust customer/signee names use at least two shared components and 75% coverage of either name.

Vambe keyword hits are `vambe_mention`: they may be a payment request or denial and do not
establish payment confirmation, break candidate ties or corroborate amount-only matches.
Legacy `vambe_context` evidence remains readable; synthetic fixtures can explicitly model
confirmed context. A future confirmed-payment source needs a typed contract, not a relabeling
of arbitrary search results.

## Read scope and budgets

`knowledge/data-scope.yaml` controls relations and SQL safety limits; required columns and
descriptions are in `knowledge/database-schema.yaml`. Update both plus grants/tests when adding
a relation. Its `candidate_defaults` section describes policy; changing it alone does **not**
rewrite deterministic eligibility SQL in `replica/investigation.py`.

Default: eight turns, twenty custom calls, 180-second model deadline, 4,096 output tokens.
Main reasoning is medium, router low; parallel tool calls disabled. The 180 seconds cover
routing/specialist execution, not queueing or Slack file download. SQL defaults: 15 seconds,
200 rows, bounded output bytes and pool. Effective pool/row/output ceilings use the tighter
application/scope limit. Vambe defaults to 30 days, at most 90 days and 50 messages.
Serialization/recovery conflicts retry twice in fresh read transactions with short backoff.

Tool audits contain names, counts, categories, timing, SQL fingerprint and referenced relations;
not raw SQL/results, Vambe text, image data, exception messages or chain-of-thought.

## Extension practice

Keep protocol-backed integrations and typed requests/results. New tools need permission scope,
budget, bounded sanitized audit, failure behavior and positive/negative tests. Prefer deterministic
helpers for stable domain calculations and scoped SQL for exploratory reads. Use a separate
monolith read API/view only when a necessary fact is unavailable, too expensive or unsafe to
reproduce. Write APIs require the separate approval design in [roadmap](roadmap.md).
