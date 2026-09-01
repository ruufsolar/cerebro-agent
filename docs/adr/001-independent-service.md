# ADR-001: Cerebro is an independent service

Status: accepted, 2026-08-28.

## Context

Cerebro begins with a narrow payment-identification task but is intended to grow into
FinOps' back-office agent. Embedding it as a constrained monolith decision service would
couple agent tools, memory, releases, and runtime risk to the main application.

## Decision

Build a standalone Python repository/service. It owns operational agent state and jobs,
reads business data from a dedicated replica, and uses monolith APIs for future writes.

## Consequences

Clear permission/deployment boundaries and faster agent iteration cost additional service
operations, schema coordination, and eventual API contracts. Business invariants remain in
the monolith; Cerebro must not reimplement writes through SQL.
