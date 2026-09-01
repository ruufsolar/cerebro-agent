# ADR-006: PostgreSQL and Procrastinate own durable workflow state

Status: accepted, 2026-08-28.

## Decision

Use Cerebro's own PostgreSQL for events, conversations, runs, tool calls, outputs, feedback,
and Procrastinate jobs. Acknowledge Slack quickly and perform investigation asynchronously.

## Consequences

Crashes, duplicate events, and deploys become recoverable/auditable. The service needs
migrations, backup, retention, idempotency, and retry discipline. This state does not become
a shadow customer system of record.
