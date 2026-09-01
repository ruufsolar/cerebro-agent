# ADR-004: Use OpenAI Agents SDK behind a local port

Status: accepted, 2026-08-28.

## Decision

Use OpenAI Agents SDK with the approved Azure deployment and Responses API, behind the
repository's harness-independent `AgentRunner` protocol. Use structured Pydantic output.

## Rationale and consequences

The SDK supplies the model/tool loop and usage information while Azure matches the company
baseline. The port/fake prevents SDK details from infecting Slack, persistence, and domain
code, and makes offline testing possible. External content tracing remains disabled.
