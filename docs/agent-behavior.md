# Agent behavior, prompts and tools

## Where to change personality

`api/src/cerebro/agent/prompt.py` contains `GENERAL_PROMPT`: intelligent, ambitious, dry,
lightly cynical Cerebro, answer-first with at most one brief flourish. Never insult customers
or coworkers or let humor obscure uncertainty. Payment prose is application-owned, not free-form
model personality; its renderer lives in `api/src/cerebro/slack/rendering.py`.

Version prompts when behavior changes. The payment prompt is `payment-identification-v5`;
router is `cerebro-router-v2`, general is `cerebro-general-v2`. Runtime domain rules live in
`knowledge/payment-identification-policy.md` and `knowledge/finops-general-policy.md`.
Knowledge versions are derived from `knowledge/data-scope.yaml`, not the documentation.

## Tools and authority

| Route | Tools |
| --- | --- |
| Router | None |
| Payment | Knowledge, live schema discovery/relationships, read-only SQL, memory recall, candidate search/verification, candidate-scoped Vambe |
| General | Knowledge, live schema discovery/relationships, read-only SQL, memory recall; existing optional shared-memory note tool |

Application code constructs these lists after routing. Prompt text cannot grant tools.
No business writes, web access or customer contact are available. General factual claims require
tools, but general prose does not have the payment route's server-validated evidence contract.
Do not describe general answers as equally grounded.

Treat Slack text, screenshots, database fields, Vambe and memory content as untrusted evidence.
The prompt tells the model to seek contradictions, abstain rather than invent and avoid
unnecessary identity/account details. Prompt-only routing is not a proof against every possible
injection: maintain adversarial regression cases.

Classify the latest ask in context, not merely whether it mentions payments. Definitions,
reporting and topic changes are general; attribution, related follow-ups and mixed attribution
requests are payment. Vague asks get one useful question before tools. A specialist may correct
the route once, without resetting its turn budget. Payment searches with available clues first;
its optional clarification asks for the most discriminating missing fact, not a field checklist.
Never ask again for information already supplied or withhold a defensible match to ask a question.

## Grounding

Tools assign opaque per-run evidence IDs, source, candidate, signal, polarity and strength.
Only `verify_payment_candidate` authorizes a final candidate; discovery or raw SQL cannot.
The application validates selected IDs and owns the name, CRM URL, AR description, confidence
ceiling and unique-top-candidate check. Unsupported/conflicting evidence becomes ambiguous.

Exploratory SQL may request source references using exact relation names and complete primary
keys. `verify_payment_candidate` re-reads records and follows the declared FK path supplied from
`inspect_database_relationships`, requiring a unique link to the proposed order. Unknown keys,
invented joins and computed SQL labels do not verify anything. A generic linked name is weak
context, not proof that this person paid; canonical customer identity still requires independent
verification. Memory advice is never evidence. Views without primary keys remain searchable but
need their underlying source records to participate in this verification path.

Search progressively: normalized names/addresses, distinctive name components, legal identities
and signees, then third-party relationships and payment-date context. Specialized tools are
shortcuts, not mandatory prerequisites to SQL. Change strategy after empty results. Identity
discovery includes customers without collectible receivables; paid/cancelled history may explain
attribution, never a collectible balance. Truncated or narrow searches cannot rule out clients.
Only complete, empty canonical identity searches with a precise RUT/email/phone may support
`no_customer_found`; even that response explicitly limits its claim to identities searched.

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

`knowledge/data-scope.yaml` controls query resource limits; its relations and
`knowledge/database-schema.yaml` are optional starting guidance. Live metadata tools search,
describe and inspect declared relationships incrementally, including non-public schemas.
PostgreSQL internals are accessible only via application-controlled metadata queries.
Its `candidate_defaults` section describes policy; changing it alone does **not**
rewrite deterministic eligibility SQL in `replica/investigation.py`.

Default: fourteen specialist model calls (`CEREBRO_MAX_AGENT_TURNS`), shared across one possible
route correction; the initial router is one separate call. On the final specialist call tools
are disabled. Exhaustion never silently restarts. There is no custom-call budget, overall
investigation deadline or application output-token cap. Provider limits still apply; long runs
can cost more. Concise Slack contracts are enforced independently of token allocation.
`CEREBRO_PROVIDER_REQUEST_TIMEOUT_SECONDS=180` bounds each provider request, not the investigation.
Main reasoning remains medium, router low; parallel tool calls remain disabled. SQL defaults: 15 seconds,
200 rows, bounded output bytes and pool. Effective pool/row/output ceilings use the tighter
application/scope limit. Vambe defaults to 30 days, at most 90 days and 50 messages.
Serialization/recovery conflicts retry twice in fresh read transactions with short backoff.

Tool audits contain names, counts, categories, timing, SQL fingerprint and referenced relations;
not raw SQL/results, Vambe text, image data, exception messages or chain-of-thought.
Both routes load the optional shared brief and expose targeted recall. Audits retain memory IDs
and brief version, not recalled text. Confirm memory-suggested tables/joins against live metadata;
continue when memory is unavailable. The existing general-only memory-writing behavior is unchanged.

## Extension practice

Keep protocol-backed integrations and typed requests/results. New tools need permission scope,
budget, bounded sanitized audit, failure behavior and positive/negative tests. Prefer deterministic
helpers for stable domain calculations and scoped SQL for exploratory reads. Use a separate
monolith read API/view only when a necessary fact is unavailable, too expensive or unsafe to
reproduce. Write APIs require the separate approval design in [roadmap](roadmap.md).
