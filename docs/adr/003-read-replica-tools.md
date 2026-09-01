# ADR-003: Scoped read replica plus free-form SQL

Status: accepted, 2026-08-28.

## Decision

Give the investigator deterministic read tools plus a bounded free-form SQL tool over a
dedicated read replica/role. Enforce read-only at DB, transaction, validator, allowlist,
timeout, row, pool, and run-budget layers.

## Rationale and consequences

Exploratory reconciliation benefits from flexible joins, while fixed APIs alone would slow
iteration. Read-only DB permissions do not solve cost, privacy, or schema coupling, so the
additional controls and audit are mandatory. Stable queries can graduate into read APIs.
