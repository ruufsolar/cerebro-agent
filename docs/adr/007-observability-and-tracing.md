# ADR-007: Metadata telemetry, no external content tracing

Status: accepted, 2026-08-28.

## Decision

Use structured application logs, durable local run/tool state, and a separate Cerebro
PostHog project containing operational metadata only. Disable Agents SDK/OpenAI external
tracing that would export customer content.

## Consequences

We retain useful reliability/cost/feedback signals while reducing PII propagation. Detailed
debugging uses access-controlled Cerebro state with a retention policy still to be defined;
engineers must build explicit redaction and replay workflows rather than relying on a SaaS
trace viewer.
