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
