# ADR-012: Simplify operation around actual production use

Status: accepted, 2026-09-10.

## Context

Cerebro is already being used in production. Wattson's comparison/rollout model is not its
operating model; four modes, a declarative capability registry and repetitive slice-status
documents obscured the implemented boundaries.

## Decision

- Keep only enabled/off. Review is a compatibility alias; shadow/apply fail explicitly.
- Remove the unused capability registry and future business-write flags. Permissions follow
  the specialist's actual tools, replica grants and deterministic validators.
- Keep quality checks as an optional configurable report, not a required ten-case launch
  ceremony. Preserve the legacy pilot command/defaults for operators.
- Retain local/test fakes, the Chat fallback, private-channel policy, shared memory and
  senior-maintained CD/public-ingress scaffolding. No model/deployment change.
- Do not auto-replay a running investigation after its worker dies: a memory write's outcome
  may be unknown. Mark it interrupted, release the queue lock and allow an explicit new request.
- Isolate synthetic evaluations/preflight from shared memory, including writes.
- Consolidate current documentation into eight topical guides; retain historical ADRs.
- Vambe keyword hits are mentions, not confirmed payment evidence. Exact address matching
  requires complete tokens. Resolve SQL CTE scope rather than globally trusting aliases.

This supersedes rollout-mode/capability/pilot-promotion statements in ADR-003, ADR-006,
ADR-008 and ADR-009; their read-only, durability, telemetry and infrastructure boundaries remain.
ADR-010's routing boundary is unchanged. ADR-011 remains an infrastructure decision: its
application endpoint/JWT validation/202 acceptance are not implemented by this cleanup.
Older documents/ADRs describe their historical state, not current operational readiness.

## Consequences

Existing review-configured deployments remain compatible. Shadow/apply deployments must change
configuration deliberately; they are not silently activated. Off requires coordinated process
restart and cannot retract an already-sent request. Business actions still need their own approved
API and authorization design. Production usage is not proof of model accuracy; tests/evaluations
and FinOps feedback remain essential. No live release is performed by accepting this ADR.
