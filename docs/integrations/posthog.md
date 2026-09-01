# PostHog

Use a separate PostHog project named `cerebro-agent`, never the Production or Melocotón
project.

Allowed event properties are operational metadata such as environment, capability, status,
confidence category, duration bucket, turn/tool counts, token counts, error code, presence
of images, and feedback sentiment.

Do not send Slack text, prompts, model output, SQL text/results, names, RUT, bank account,
phone, email, address, screenshot content, raw event payloads, or credentials. Distinct IDs
should be non-PII internal hashes when correlation is necessary.

External Agents SDK/OpenAI tracing remains disabled. Detailed replay data stays in the
access-controlled Cerebro DB/log environment according to the eventual retention policy.
