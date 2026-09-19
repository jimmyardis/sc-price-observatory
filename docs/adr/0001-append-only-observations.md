# 1. Observations are append-only; revisions are new method versions

**Status:** accepted (2026-09-16)

Every published number must be regenerable from raw observations plus a `method_version`. So `observations` rejects UPDATE/DELETE at the database level (triggers in `db/migrations/0002_*`). A re-collection appends new rows; the latest row per (week, store, item, price_type) is the effective price.

Derived tables (`index_values`, `basket_costs`, `time_prices`) are recomputed freely. What's frozen is what we *published*: snapshot files are never overwritten, and the `no_silent_revision` QA gate blocks any export where an already-published value changed under the same `method_version`. To change a published number, bump `method_version` in `config/collection.json`; both versions stay downloadable.
