# Success and feedback

## V0 release gate

A real mention in Slack with text and/or screenshots triggers one durable run, autonomously
searches real read-only monolith data, and produces an auditable same-thread answer that is
at least somewhat useful to FinOps.

Slice 5 requires one live Luna pass over the twenty-case synthetic suite: at least 17/20
correct, no wrong high-confidence match, no unsupported claim, and no verbose output. It then
requires ten FinOps-reviewed Slack cases, at least four with screenshots, with 9/10 correct
and the same zero-tolerance safety gates. Payment identification remains preview until FinOps
signs off.

The Slice 6A pilot command additionally requires median/p95 end-to-end delivery latency of
at most 60/120 seconds, average input/output use of at most 50,000/1,000 tokens, and per-run
maxima of 100,000/2,000 tokens. Token counts are the V0 cost proxy; no contractual Azure
price is embedded in the service.

## Operational metrics

- mention-to-first-status latency;
- run completion and failure rates;
- time to final thread reply;
- tool-call and turn counts, model/token usage;
- SQL timeouts/rejections/row counts;
- fraction with a customer candidate;
- confidence distribution;
- 🧀 and 🔌 rates;
- duplicate event suppression;
- manual correction rate once structured correction feedback exists.

## Quality metrics

Build a FinOps-labeled fixture set across: glosa match, name match, exact outstanding match,
partial payments, different transferor, multiple candidates, non-customer deposit, and the
ambiguous first transfer. Measure top-1 accuracy, top-k recall, abstention quality, evidence
faithfulness, and false high-confidence rate.

FinOps reactions are useful directional feedback, not a complete ground-truth label. Never
self-modify prompts or tools directly from reactions. Review evidence, update an eval case,
then change versioned code/knowledge in a normal PR.
