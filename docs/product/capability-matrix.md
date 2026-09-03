# Capability matrix

| Capability | State | Trigger | Reads | Effects | Human approval |
|---|---|---|---|---|---|
| Foundation health/state/jobs | Implemented; Slice 6A split workers, heartbeats, readiness, safe logs, operator CLIs, and Azure Terraform deployment reference | Process start / HTTP / CLI | Cerebro DB | Health/readiness response, durable jobs, aggregate local reports | No |
| Payment identification V0 | Preview; Slice 5 grounded outcomes, concise text, ephemeral screenshot vision, live replica tools; pilot pending | Slack mention/follow-up | Stored transcript metadata; triggering screenshot bytes; allowed replica relations; candidate-scoped Vambe | Same-thread evidence-grounded Slack reply in review/apply | No business action |
| Reaction feedback | Implemented | 🧀 / 🔌 | Cerebro investigation outputs | Feedback row; flavor reply on 🔌 | No |
| Automatic bank investigation | Future | New bank movement | Bank + same V0 reads | Proactive FinOps proposal | No business action |
| Register AR payment | Future | Explicit FinOps approval | Candidate + AR state | Monolith write API | Required |
| Correct/revert AR payment | Future | Explicit FinOps approval | Existing association | Monolith write API | Required |
| Hold recommendation | Future V1 | Due AR without payment | AR + payment context | Slack verdict proposal | FinOps decides |
| Apply/reverse hold | Blocked on definition | Explicit approval / payment | Hold + payment state | Monolith write API | Required |
| Customer acknowledgement | Out of scope | Payment registered | N/A | Owned by Pinky/human | N/A |

`src/cerebro/capabilities/registry.py` is the executable subset of this matrix. Payment
identification remains preview until the ten-case pilot, rollback drill, and FinOps signoff
are complete; Slice 6A does not promote it to `live`.
