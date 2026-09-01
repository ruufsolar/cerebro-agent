# ADR-002: Slack Socket Mode is the V0 surface

Status: accepted, 2026-08-28.

## Decision

Use Slack Socket Mode for mentions, known-thread follow-ups, files, status, and reactions.
Any member may mention Cerebro in an installed/invited channel; replies remain in-thread.

## Rationale and consequences

This matches Melocotón and avoids a public webhook/DNS requirement while bank ingestion is
missing. It requires a long-running outbound WebSocket process and separate `xapp`/`xoxb`
tokens. Slack is a temporary manual trigger; future bank events reuse the same core.
