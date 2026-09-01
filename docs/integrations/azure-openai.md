# Azure OpenAI and Agents SDK

Cerebro uses the OpenAI Agents SDK as an in-process ephemeral agent. Instructions, tools,
and state ownership remain in this repository; no persisted Foundry agent is required.

## Baseline

- Reuse Wattson's Azure/OpenAI deployment pattern and the OpenAI Responses API.
- Configure the Azure resource endpoint, API key (initially), and exact deployment names.
- The `model` sent to Azure is the deployment name, which may differ from the catalog model
  ID. Do not silently substitute one for the other.
- Main model should accept text and image input. A smaller deployment may later handle
  cheap classification/rendering but V0 begins with one investigator.
- Agents SDK tracing to external OpenAI endpoints stays disabled. PostHog receives only
  selected metadata.

Microsoft recommends Microsoft Entra ID for production; API keys are acceptable to unblock
the baseline when stored securely. The Azure v1 route is `<resource endpoint>/openai/v1/`
and does not take a dated `api-version`. See the
[Azure Responses API guide](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/responses)
and [OpenAI model/vision availability](https://developers.openai.com/api/docs/models).

## Adapter requirements

- Implement only behind `AgentRunner`.
- Pass validated image inputs directly; do not add a separate OCR vendor in V0.
- Enforce overall timeout, maximum turns, and maximum tool calls in code.
- Validate Pydantic output; one repair attempt can be allowed inside the same budget.
- Record deployment, token usage, latency, prompt version, and errors without input/output
  content in external telemetry.
- Unit tests inject the fake and never require Azure credentials.

## Implemented runtime behavior

`OpenAIAgentsRunner` uses the main deployment, medium reasoning, Responses, disabled
parallel tool calls, no response storage, and external tracing disabled. The application
enforces an eight-turn, twenty-custom-tool, 4,096-output-token, and 180-second baseline.
The custom-tool counter is application-owned rather than delegated to an API limit.

Runner selection happens at worker startup:

- endpoint + key + main deployment selects Azure;
- no endpoint and no key selects the deterministic fake;
- only one of endpoint/key fails startup instead of silently falling back.

The endpoint may be the resource root or already end in `/openai/v1/`; Cerebro normalizes
both forms. Set `CEREBRO_AZURE_OPENAI_USE_RESPONSES=false` only as a compatibility fallback.
Reasoning/store settings that are specific to Responses are omitted in that mode.

The runtime selects the Slice 3 replica backend only when
`CEREBRO_READ_REPLICA_URL` is configured; otherwise every data operation explicitly reports
unavailable and the model must abstain. Synthetic observations are confined to
`cerebro.evals` and are never selected by the Slack worker. Even with replica data, the
application accepts a recommended customer only when `verify_payment_candidate` returned
that exact order/receivable pair in the same run.
