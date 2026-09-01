# Monolith and read replica

## Reads

Cerebro connects directly to a dedicated read replica for exploratory investigation. The
initial relation scope is versioned in `knowledge/data-scope.yaml` and intentionally easy
to edit. Access is layered as described in `architecture/data-access.md`.

Known starting facts:

- normal customer ARs default to CLP, while the enum also supports USD and `CLF` (UF);
- outstanding balance must subtract both payments and losses;
- Vambe messages include direction, type, content, phone/user/stage/sender context;
- the Vambe receive DTO does not supply a generally persisted attachment URL;
- no generic searchable `pagos@ruuf.solar` mailbox exists;
- the FinOps CRM route uses the booking/order `orderId`.

Slice 3 implements this connection with `asyncpg`. Startup fails closed unless the session
is read-only, the role lacks dangerous/write privileges, the database is in recovery
(except the explicit local/test fixture override), and every declared relation/column is
schema-compatible. Non-local/test DSNs must request SSL.

The deterministic tools compute open balance from active same-currency payments and losses,
filter to eligible client/Ruuf receivables and active installations, and treat stored bank
ownership as supporting—not decisive—evidence. Vambe searches are candidate-scoped, default
to 30 days, and cannot exceed 90 days.

## When to add a monolith read API

Use a separate monolith PR when a stable domain calculation is unsafe to reproduce, a
necessary source is not stored, a query is too costly/coupled, or row-level authorization
cannot be expressed safely at the replica boundary. The Cerebro slice may include those
read PRs in scope, but each PR follows monolith instructions and is independently mergeable.

Candidate future APIs/views include a canonical open-AR/outstanding-balance projection and a
normalized generic payments-email feed. The Slice 3 implementation did not prove either
necessary, so no monolith PR is required at this point.

## Writes

Never write through the replica. Future `AccountReceivablePayment` and hold operations use
narrow monolith command APIs with explicit FinOps approval, exact parameters, preconditions,
idempotency, and repair/reversal semantics. There is no write client in V0.

## Documentation debt to fix separately

Current monolith domain knowledge should consistently call UF currency `CLF`, and its
outstanding calculation should account for losses. Make this a small monolith docs PR when
that repository is in scope; do not copy the incorrect formula into Cerebro.
