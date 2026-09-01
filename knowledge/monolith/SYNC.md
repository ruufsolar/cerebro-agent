# Monolith knowledge sync

Reviewed against the sibling monolith on 2026-08-28.

Confirmed:

- currency enum is `CLP`, `USD`, `CLF`;
- normal AR creation defaults to CLP;
- Vambe stores direction/type/content/phone/user/stage/sender context;
- the inbound Vambe DTO has no generic attachment URL field;
- code convention is `pagos@ruuf.solar`, with only a specialized inbound email path found;
- FinOps CRM uses booking/order `orderId` in the route.

Known monolith knowledge drift to fix in a separate PR:

- a domain file calls UF `UF` instead of enum value `CLF`;
- an outstanding query omits receivable losses.

No monolith files are vendored yet. Slice 3 should add a reproducible schema/metadata
snapshot with source commit and drift check instead of blindly copying changing entities.
