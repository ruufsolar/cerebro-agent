# Architecture overview

Cerebro is an asynchronous agent application with strict capability boundaries.

```text
Slack Socket Mode
      |
      v
event ingestion --dedupe--> Cerebro PostgreSQL --> Procrastinate worker
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

The web/socket process acknowledges and stores events quickly. Durable worker jobs perform
slow investigation. Tool calls are code with typed boundaries; the model chooses which
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
- **Observability:** structured logs and metadata-only PostHog events. External model tracing
  containing customer content is disabled.
- **Future action gateway:** explicit approval state plus narrow monolith write APIs. It is
  absent from V0.

## Deployment boundaries

Cerebro uses its own image, Compose project, PostgreSQL volume, environment file, update
timer, and backup directory on the same baseline VM as Wattson. Socket Mode means Slack
does not require a public inbound route. The health port binds to localhost.
