# Cerebro wiki

This wiki is the durable source of context for product, engineering, operations, and
future coding agents. It deliberately contains normalized requirements without links to
the planning system.

## Start here

1. [Quickstart](getting-started/quickstart.md)
2. [Local Slack testing](getting-started/local-slack-testing.md)
3. [Product requirements](product/requirements.md)
4. [Current state](product/current-state.md)
5. [Architecture](architecture/overview.md)
6. [Vertical slices](delivery/vertical-slices.md)
7. [External setup](operations/external-setup.md)

## Product

- [Requirements](product/requirements.md)
- [Current state](product/current-state.md)
- [Capability matrix](product/capability-matrix.md)
- [Response contract](product/response-contract.md)
- [Success and feedback](product/success-and-feedback.md)
- [Glossary](getting-started/glossary.md)

## Engineering

- [Architecture overview](architecture/overview.md)
- [Runtime flows](architecture/runtime-flows.md)
- [Data access](architecture/data-access.md)
- [Agents 101](agent-development/agents-101.md)
- [Tools and orchestration](agent-development/tools-and-orchestration.md)
- [Prompting](agent-development/prompting.md)
- [Safety](agent-development/safety.md)
- [Evals](agent-development/evals.md)

## Integrations and operations

- [Slack](integrations/slack.md)
- [Azure OpenAI](integrations/azure-openai.md)
- [Monolith and replica](integrations/monolith.md)
- [PostHog](integrations/posthog.md)
- [Future bank ingestion](integrations/bank-ingestion.md)
- [Secrets](operations/secrets.md)
- [Deployment](operations/deployment.md)
- [Runbook](operations/runbook.md)

## Decisions

- [ADR-001: Independent service](adr/001-independent-service.md)
- [ADR-002: Socket Mode](adr/002-slack-socket-mode.md)
- [ADR-003: Read-replica tools](adr/003-read-replica-tools.md)
- [ADR-004: OpenAI Agents SDK](adr/004-openai-agents-sdk.md)
- [ADR-005: Approval-gated writes](adr/005-approval-gated-writes.md)
- [ADR-006: Durable state and jobs](adr/006-durable-state-and-jobs.md)
- [ADR-007: Observability and tracing](adr/007-observability-and-tracing.md)

When code and documentation disagree, treat that as a bug. Update `current-state.md` and
the capability matrix in the same PR that changes behavior.
