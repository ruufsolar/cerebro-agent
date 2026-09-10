# Cerebro knowledge

This directory contains versioned facts/policies made available to the agent. It is separate
from the engineering wiki: wiki text explains the system; knowledge text influences live
investigation.

- `data-scope.yaml` provides curated starting relations, business rules and query resource limits;
  live replica grants and metadata define readable application relations, not this curated subset.
- `finops-general-policy.md` defines the conversational read-only operating boundary.
- `payment-identification-policy.md` is the normalized identification policy.
- `monolith/SYNC.md` records which monolith facts were checked and known drift.

Changes require review like code and a knowledge revision in agent runs. Do not paste live
customer examples or credentials here.
