# Evaluations and feedback

Tests protect deterministic behavior; synthetic model evaluations test reasoning; FinOps feedback
checks usefulness in actual work. None automatically retrains or rewrites Cerebro.

## Automated and synthetic checks

CI is offline: scripted model outputs, fake Slack, synthetic tool observations and disposable
PostgreSQL prove routing fallback, grounding, budgets, SQL boundaries, modes, outbox and cleanup.
Mocked routing labels do not establish real model accuracy.

`api/src/cerebro/evals/cases.yaml` contains twenty anonymized payment/general cases: addresses,
name collisions, 70/30 and partial payments, third-party transfers, currencies, contradictions,
unavailable sources and injection (including images/Vambe). Routing examples are maintained
separately under `evals/`.

From `api/`:
```bash
uv run python -m cerebro.evals.run
uv run python -m cerebro.evals.run --live
uv run python -m cerebro.evals.run --live --json-output /tmp/cerebro-eval.json
uv run python -m cerebro.evals.run --live --case third_party_with_vambe
```

Without `--live`, the command validates the corpus, not model quality. Live is explicitly
opt-in/cost-bearing: Azure plus fixture-only data and generated fake screenshots. It never uses
Slack, the production replica or shared-memory reads/writes, even when memory credentials exist.
Synthetic preflight uses the same isolation. Reports record deployment, prompt/knowledge,
duration and token usage; no real customers enter the corpus.

The full synthetic gate retains at least 17/20 correct decisions, zero wrong high-confidence
matches and zero unsupported claims. Routing, format, forbidden-tool or unsupported-claim
errors are hard failures even if the aggregate score otherwise passes. A filtered run requires
every selected case to pass and is diagnostic, not a substitute for the whole suite.
Model defaults and configured Azure deployment names are not assumed to be identical.

## Optional production quality report

There is no mandatory “exactly ten cases before launch” lifecycle or capability promotion flag.
Cerebro is already used in production. Periodically select a deliberate channel/time window:

```bash
uv run python -m cerebro.ops.quality_report \
  --channel C0123456789 --since 2026-09-10T00:00:00-03:00 --json
```

Default: evaluate all payment runs in the window, require a nonempty sample and 90% positive
feedback, but no minimum screenshot count. Set `--sample-size 10 --min-image-cases 4` for a
balanced fixed sample, or `--min-positive-rate 0.95` for a stricter target.
General conversation is excluded. The legacy `cerebro.ops.pilot_gate` command remains available
with its old ten-case/four-image defaults for existing operator workflows.

Reports label cases `case_01`, etc.; no names, message text, order IDs or payment values.
Checks retain single sent investigation per trigger, resolved feedback, supported evidence/source
tool names, response-length contracts, successful runs/deliveries and no timeouts.
They inspect stored metadata; they are not an independent reconstruction of the replica truth.
Latency: median at most 60s, nearest-rank p95 at most 120s. Average input/output tokens:
50,000/1,000; per-run maxima: 100,000/2,000. Exit codes: 0 pass, 1 quality failure, 2 usage/config error.

## Feedback loop

🧀 means correct/useful. 🔌 means wrong/unhelpful and triggers one in-thread pain response.
Both active on one answer are a conflict to resolve; an active 🔌 takes precedence over positives.
Multiple cheeses count as one positive case; removed reactions become inactive.
Feedback works on payment/general replies, never on flavor/error replies.

For negative and representative positive cases, have FinOps supply the expected answer,
relevant missing fact and whether abstention was appropriate. Convert to synthetic names,
identities, amounts and screenshots; preserve the failure mechanism without retaining real data.
Review changes to tools/policy before merely adjusting the prompt. No formal production score,
FinOps signoff or live Azure test is implied by a passing offline suite.
