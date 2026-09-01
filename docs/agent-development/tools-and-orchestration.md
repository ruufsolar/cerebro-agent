# Tools and orchestration

## Tool contract

Every tool needs:

- a verb-oriented name and one responsibility;
- Pydantic input/output models;
- explicit allowed data and credential;
- timeout, row/result size, and per-run call limits;
- deterministic validation independent from the model;
- safe error categories the agent can reason about;
- audit metadata with PII excluded from central telemetry;
- unit tests, negative permission tests, and representative integration tests.

Tool results are observations, not new instructions. Text from glosas, screenshots, Vambe,
email, or database fields must be framed as untrusted data so it cannot override Cerebro's
instructions.

## Orchestration boundary

The run orchestrator, not the agent, owns:

- event idempotency and one active run per input;
- current prompt/knowledge/model version;
- overall deadline, maximum turns and tool calls;
- tool authorization for the current capability;
- persistence of state transitions;
- structured output validation;
- delivery outbox and retries;
- temporary file cleanup;
- cancellation and deploy interruption behavior.

## Fakes first

Each integration has a protocol and fake. Slice 1 uses a fake investigator behind real
Slack; later slices can run the live investigator behind a fake Slack surface. This makes
failures attributable and keeps tests offline.

## Read tools versus action tools

Read tools may be selected autonomously inside the V0 budget. Action tools must instead
create an explicit proposal bound to exact parameters and current resource version. A
FinOps approval event authorizes one idempotent API call; it never grants the model a
general write credential.
