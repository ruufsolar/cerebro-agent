# Slice checklist

Before merging a vertical slice:

- [ ] User outcome and non-goals are explicit.
- [ ] Capability matrix/current-state are updated.
- [ ] Integrations sit behind protocols with fakes.
- [ ] Inputs/outputs and failure categories are typed.
- [ ] Time, turn, tool, image, query, and result budgets are enforced where relevant.
- [ ] Idempotency/retry behavior is tested.
- [ ] Negative permission and prompt-injection cases are tested.
- [ ] Schema change includes Alembic migration.
- [ ] No secret, production PII, raw screenshot, or database dump is committed.
- [ ] Ruff, Pyright, pytest, Alembic, and container config pass.
- [ ] Operational signals and rollback are documented.
- [ ] New prompt/model/tool behavior passes the relevant eval suite.
- [ ] Monolith changes are separate, read its `AGENTS.md`, and remain independently mergeable.
