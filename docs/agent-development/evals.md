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

## Slice 5 release suite

`src/cerebro/evals/cases.yaml` contains exactly twenty anonymized cases across address/name,
70/30 balances, partial payments, duplicate amounts, third-party/Vambe evidence,
contradictions, eligibility, currency, no-customer, out-of-scope, injection, and unavailable
sources. Fixtures respond to the requested order and amount rather than exposing arbitrary
synthetic customers.

```bash
cd api
uv run python -m cerebro.evals.run        # schema/corpus validation only
uv run python -m cerebro.evals.run --live # Azure + synthetic fixture tools
uv run python -m cerebro.evals.run --live --json-output /tmp/cerebro-eval.json
uv run python -m cerebro.evals.run --live --case third_party_with_vambe
```

The live command runs each case once with the configured Luna deployment. Screenshot cases
generate temporary fake bank images. It requires approved Azure credentials but never
connects to Slack, the replica, or real customer data. Passing requires at least 17/20
correct decisions, zero wrong high-confidence matches, zero unsupported evidence/customer
claims, and all response-length budgets. The JSON report also records per-case deployment,
duration, and token use plus aggregate latency/usage; those measurements do not change the
Slice 5 quality gate. It remains opt-in and outside CI.
Repeat `--case` to rerun selected named cases while tuning; a filtered diagnostic requires
every selected case to pass and does not replace the full 20-case gate.

The separate `replica` Compose profile creates a schema-compatible PostgreSQL fixture and
the integration test exercises the real deterministic tools. It does not call Azure or Slack.

After the synthetic gate, run the ten-case FinOps pilot documented in
`docs/operations/slice5-pilot.md`. Slice 6A evaluates its aggregate metadata with
`python -m cerebro.ops.pilot_gate`; reactions inform fixture changes but never train or
modify the agent directly.
