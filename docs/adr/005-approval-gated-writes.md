# ADR-005: All business writes require approval-gated APIs

Status: accepted, 2026-08-28.

## Decision

V0 performs no business writes. Future payment and hold changes require a narrow monolith
API and one explicit FinOps approval bound to exact parameters, preconditions, expiry, and
idempotency key. The model may propose but cannot authorize or execute arbitrary writes.

## Consequences

This adds a proposal/approval/action state machine and monolith work but preserves domain
invariants, auditability, and repair semantics. The replica credential is never reused.
