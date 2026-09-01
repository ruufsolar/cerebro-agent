# Agents 101 for Cerebro

An agent is not just an LLM call. It is a software loop in which a model receives a goal
and context, chooses among code-defined tools, observes their results, and stops with a
typed result under application-enforced limits. The application remains responsible for
permissions, state, retries, validation, and side effects.

## The pieces

- **Instructions:** stable role, task, decision policy, output requirements, and explicit
  non-goals. They are versioned code/knowledge, not tribal knowledge.
- **Input:** the current Slack request, validated images, thread context, and run metadata.
- **Tools:** typed, small functions that access the real world. A tool is the security
  boundary; its docstring helps the model choose it but does not enforce authorization.
- **Loop:** model proposes a tool call, application executes it, result returns to model,
  and this repeats until a final output or a budget is reached.
- **Structured output:** Pydantic model validated by code before rendering to Slack.
- **Harness:** OpenAI Agents SDK adapter. Business orchestration depends on the local
  `AgentRunner` protocol so SDK/version changes do not spread through the codebase.
- **Durable workflow:** events, runs, jobs, tool calls, and deliveries persist outside the
  model so crashes/retries are safe.
- **Evals:** labeled examples and graders that detect regressions before prompt/model/tool
  changes ship.

## Autonomy is a permission budget

“Autonomous” means Cerebro may decide which approved read tools to call and in what order.
It does not mean arbitrary shell/network/database access. V0's autonomy envelope is:

- trigger: explicit Slack mention;
- goal: identify one incoming payment;
- data: curated knowledge and scoped read replica;
- time/turn/tool/image/row limits from config;
- output: one same-thread internal reply;
- writes: none.

Future approval-gated writes are separate capabilities and separate credentials.

## Common development loop

1. Write a concrete user outcome and forbidden effects.
2. Build one end-to-end slice with fake integrations.
3. Define typed tools based on observed questions, not speculative tool sprawl.
4. Create realistic eval cases before changing the prompt/model.
5. Add live read-only integration in shadow/review mode.
6. Inspect traces locally, errors, costs, and FinOps feedback.
7. Promote only after negative cases and idempotent retries work.

## Practices that matter most

- Give the model facts, not authority. Code enforces access.
- Keep tools composable and results compact.
- Separate investigation from action. A recommendation is not a write command.
- Make abstention first-class. “No sé” protects FinOps from fabricated certainty.
- Record enough to reproduce why an answer happened: prompt/knowledge/model versions, tool
  inputs/results, and final structured output.
- Never replay a non-idempotent side effect just because a model/run retried.
- Prefer a single capable investigator for this scoped task. Add multiple agents only when
  roles truly require separate context, permissions, or evaluation.

## Failure modes to watch

- giant prompts that dump all customers instead of letting tools narrow candidates;
- tools that accept arbitrary writes or return unbounded rows;
- natural-language confidence unsupported by evidence;
- model output directly causing a side effect;
- retrying Slack/business writes without an idempotency key;
- testing only happy paths;
- treating internal-only use as zero prompt-injection risk (customer-controlled glosa,
  screenshots, email, and WhatsApp text are still untrusted data);
- allowing docs, prompt, schema assumptions, and code to drift.
