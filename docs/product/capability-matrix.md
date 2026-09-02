# Capability matrix

| Capability | State | Trigger | Reads | Effects | Human approval |
|---|---|---|---|---|---|
| Foundation health/state/jobs | Implemented | Process start / HTTP | Cerebro DB | Health response, durable jobs | No |
| Payment identification V0 | Preview; text + ephemeral screenshot vision + live replica tools | Slack mention/follow-up | Stored transcript metadata; triggering screenshot bytes; allowed replica relations; candidate-scoped Vambe | Same-thread structured Slack reply in review/apply | No business action |
| Reaction feedback | Implemented | 🧀 / 🔌 | Cerebro investigation outputs | Feedback row; flavor reply on 🔌 | No |
| Automatic bank investigation | Future | New bank movement | Bank + same V0 reads | Proactive FinOps proposal | No business action |
| Register AR payment | Future | Explicit FinOps approval | Candidate + AR state | Monolith write API | Required |
| Correct/revert AR payment | Future | Explicit FinOps approval | Existing association | Monolith write API | Required |
| Hold recommendation | Future V1 | Due AR without payment | AR + payment context | Slack verdict proposal | FinOps decides |
| Apply/reverse hold | Blocked on definition | Explicit approval / payment | Hold + payment state | Monolith write API | Required |
| Customer acknowledgement | Out of scope | Payment registered | N/A | Owned by Pinky/human | N/A |

`src/cerebro/capabilities/registry.py` is the executable subset of this matrix. A capability
becomes `live` only after production setup, tests, evals, and a rollback plan are complete.
