# ADR-010: Route conversations before granting specialist tools

Status: accepted, 2026-09-07.

## Decision

Expand V0 beyond payment identification with an application-controlled, structured router. A
no-tool, low-reasoning model classifies each run as `payment_identification` or `general` before a
specialist is created. Mixed, uncertain, invalid, and adversarial-looking classifications use the
payment path. The payment specialist keeps its grounded candidate/evidence contract. The general
specialist receives only curated FinOps knowledge, schema descriptions, and allowlisted read-only
SQL.

## Rationale and consequences

This gives the Slack persona useful conversational range without weakening payment safeguards or
giving a general prompt specialized customer-verification tools. The router and specialist share
one deadline and tool budget. Routes, versions, aggregate usage, and final replies are stored, but
router rationale and model reasoning are not. General answers can contain scoped replica PII in
the originating private Slack thread, so installing Cerebro only in private channels is an
operational requirement even though the service does not enforce a channel allowlist.
