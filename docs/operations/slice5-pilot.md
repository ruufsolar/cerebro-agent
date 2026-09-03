# Slice 5 controlled pilot

This is a release gate, not a production launch. Run Cerebro in one private FinOps test
channel with `CEREBRO_GLOBAL_MODE=review`; keep payment and hold writes disabled.

The baseline synthetic gate passed 20/20 on 2026-09-02 using
`payment-identification-slice5-v1`, `payment-identification-knowledge-v3`, and Azure deployment
`gpt-5-6-luna`. Rerun it after any model, prompt, knowledge, tool, or grounding-policy change.

## Prerequisites

1. Confirm one Socket Mode consumer, valid Slack `files:read`, the production physical-replica
   preflight, and the Azure deployment serving GPT-5.6 Luna.
2. Run `uv run python -m cerebro.evals.run --live` once. Continue only with at least 17/20
   correct, zero wrong high-confidence matches, zero unsupported claims, and a passing report.
3. Do not paste or commit real screenshots, transcripts, names, order IDs, or payment details.

## Ten reviewed cases

Use ten distinct real payments. Include at least four screenshots and cover:

- known address/glosa matches;
- transferor/name and 70%/30% balance matches;
- a valid partial payment;
- a payment from another name with Vambe context;
- a genuinely ambiguous payment or duplicate amount;
- a contradictory or currency-mismatch case;
- a search with no eligible customer.

Each case is sent once. FinOps reacts 🧀 when the match or abstention is correct and 🔌 when
it is not. For 🔌, an engineer obtains the correct result directly from FinOps outside
Cerebro. Reactions do not train or rewrite the agent.

## Gate and fixture follow-up

All ten cases must be labeled. Passing requires at least nine 🧀, no incorrect high-confidence
match, no customer/evidence claim unsupported by the run's tool ledger, one thread reply per
message, and no screenshot remaining in `/tmp/cerebro-images`.

Convert every 🔌 and representative 🧀 scenarios into anonymized synthetic fixtures. Preserve
only the evidence pattern and expected outcome; replace all identifying and payment data.

FinOps must explicitly sign off on the results. Record only the aggregate score, gate date,
prompt/knowledge versions, Azure deployment name, and reviewer role in the delivery checklist.
Payment identification stays preview until this signoff is complete.

Slice 6A automates the metadata-only gate. Select the exact private-channel/time window:

```bash
uv run python -m cerebro.ops.pilot_gate \
  --channel C0123456789 \
  --since 2026-09-02T09:00:00-04:00 \
  --until 2026-09-02T18:00:00-04:00
```

In addition to the quality rules above, it enforces median/p95 end-to-end latency of
60/120 seconds, average input/output use of 50,000/1,000 tokens, and per-run maxima of
100,000/2,000 tokens. See [Pilot operations](pilot-operations.md).
