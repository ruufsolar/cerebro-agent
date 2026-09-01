# Evals

Agent tests have three layers.

## Deterministic tests

Test event routing, duplicate suppression, SQL rejection, outstanding-balance calculation,
result validation, confidence rendering, CRM URLs, feedback, retries, cleanup, and hard
switches without calling a model.

## Recorded integration tests

Use synthetic or redacted schema-compatible fixtures for Slack events, screenshots, replica
rows, and Vambe messages. Fakes return known observations while the real orchestrator runs.

## Model evals

Maintain versioned cases with input, available tool observations, expected acceptable
customers/ranking, required evidence, forbidden claims, and whether abstention is required.
The initial set must cover:

- exact glosa/address match;
- transferor/customer name match;
- exact remaining 70% and final 30% balances;
- partial payment;
- different transferor with Vambe receipt context;
- ambiguous first transfer without glosa;
- multiple same-amount receivables;
- non-customer supplier/internal/refund movement;
- UF/CLF AR and currency mismatch;
- stale/cancelled/fully paid AR;
- contradictory evidence;
- prompt injection inside screenshot/glosa/Vambe;
- replica timeout and missing schema.

Grade top candidate, allowed alternatives, abstention, evidence faithfulness, unsupported
claims, privacy, and output contract. High confidence on a wrong customer is the most
important regression.

FinOps feedback creates candidates for new labeled cases; it does not directly train or
rewrite Cerebro. Keep a small release-blocking suite and a larger diagnostic suite. Compare
prompt/model/tool versions on the same cases before promotion.

## Synthetic model harness

`src/cerebro/evals/cases.yaml` contains six Slice 3 versioned, synthetic cases for address, name,
amount ambiguity, difficult first payment, contradictory evidence, and prompt injection.

```bash
cd api
uv run python -m cerebro.evals.run        # schema/corpus validation only
uv run python -m cerebro.evals.run --live # Azure + synthetic fixture tools
```

The live command requires approved Azure credentials but never connects to Slack or real
Ruuf data. It is opt-in and not part of CI.

The separate `replica` Compose profile creates a schema-compatible PostgreSQL fixture and
the integration test exercises the real deterministic tools. It does not call Azure or Slack.
