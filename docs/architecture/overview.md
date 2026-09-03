# Architecture overview

Cerebro is an asynchronous agent application with strict capability boundaries.

```text
Slack Socket Mode
      |
      v
event ingestion --dedupe--> Cerebro PostgreSQL --> control queue
                                                   |       \
                                             Slack I/O    agent queue
                                                               |
                                      run orchestrator / budgets
                                      /        |          \
                              knowledge    replica tools   Vambe search
                                      \        |          /
                                       OpenAI Agents SDK
                                              |
                                  structured identification
                                              |
                                    Slack outbox/thread reply
                                              |
                                     reaction feedback
```

The web/socket process acknowledges and stores events quickly. Separate two-concurrency
control and agent workers prevent slow investigations from blocking Slack ingestion or
delivery. Tool calls are code with typed boundaries; the model chooses which
reads are useful but cannot obtain a write-capable replica connection. Slack delivery uses
an idempotent outbox record so retries do not produce duplicate answers.

## Components

- **Surface adapter:** Slack Socket Mode, mentions, thread context, images, status, replies,
  and reactions.
- **Run orchestrator:** durable state transitions, timeout/turn/tool budgets, retry rules,
  and structured result validation.
- **Agent runner:** small protocol with an OpenAI Agents SDK adapter and fakes.
- **Knowledge tools:** curated product semantics and the configurable candidate/data scope.
- **Replica tools:** schema allowlist, read-only SQL, Vambe search, and deterministic
  candidate verification helpers.
- **Cerebro DB:** operational state only; not a copy of monolith business data.
- **Operations:** local structured logs, runtime heartbeats/readiness, durable metadata, and
  aggregate CLIs. V0 has no PostHog or external model tracing.
- **Future action gateway:** explicit approval state plus narrow monolith write APIs. It is
  absent from V0.

## Deployment boundaries

Cerebro uses its own Azure resource group, private VM, stable NAT egress, Key Vault, retained
data disk, image, Compose project, PostgreSQL volume, update timer, and backup directory.
It does not share Wattson's VM. Socket Mode means Slack does not require a public inbound
route; the VM has no public IP or custom inbound NSG rule and the health port binds to localhost.
Runtime secrets are seeded after Terraform and read through the VM managed identity, never
stored in Terraform state.
