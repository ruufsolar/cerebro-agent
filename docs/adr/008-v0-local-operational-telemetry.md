# ADR-008: V0 uses local operational telemetry only

Status: accepted, 2026-09-02.

## Context

The controlled V0 pilot needs reliability, latency, usage, and feedback signals, but does
not need a product-analytics system. Sending even metadata to another service adds setup,
retention, and access-control work before the team has validated the Slack workflow.

## Decision

V0 uses privacy-safe structured application logs, Cerebro's durable PostgreSQL state,
runtime readiness, and aggregate operator commands. It does not include PostHog or another
external dashboard/alert destination. Agents SDK tracing, provider storage, and sensitive
model/tool logging remain disabled.

Logs contain allowlisted operational categories and internal identifiers only. Detailed
investigation data stays in access-controlled Cerebro state and is never copied into CLI
reports. Retention is manual during the pilot and follows the operations runbook.

## Consequences

The pilot can be measured and debugged without creating another customer-data destination.
Operators must inspect readiness, logs, and aggregate CLI reports directly. A future launch
may introduce an external telemetry destination only through another ADR with explicit
event, access, and retention policies.
