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

## When to add a monolith read API

Use a separate monolith PR when a stable domain calculation is unsafe to reproduce, a
necessary source is not stored, a query is too costly/coupled, or row-level authorization
cannot be expressed safely at the replica boundary. The Cerebro slice may include those
read PRs in scope, but each PR follows monolith instructions and is independently mergeable.

Candidate early APIs/views include a canonical open-AR/outstanding-balance projection and a
normalized generic payments-email feed. Do not build them until Slice 3 proves the need.

## Writes

Never write through the replica. Future `AccountReceivablePayment` and hold operations use
narrow monolith command APIs with explicit FinOps approval, exact parameters, preconditions,
idempotency, and repair/reversal semantics. There is no write client in V0.

## Documentation debt to fix separately

Current monolith domain knowledge should consistently call UF currency `CLF`, and its
outstanding calculation should account for losses. Make this a small monolith docs PR when
that repository is in scope; do not copy the incorrect formula into Cerebro.
