# Directive: build_index

**Goal:** Compute the matched-model index, basket costs, and time price for every geo with data. The method mirrors BLS so "same method, local data" is defensible.

## Tools
- `python -m execution.compute_index`
- `python -m execution.compute_time_price fetch-wages [--since 2025Q1]`, then `compute`

## Method (method_version in `config/collection.json`)
1. **Effective prices:** the latest row per (week, store, item, price_type). `shelf` series = shelf only; `promo_incl` = the minimum across types.
2. **Lower level:** Jevons over (store, item) pairs observed in both this and the geo's previous collection week (ADR 0002).
3. **Upper level:** Σ w_s R_s, with weights from `weights_file` renormalized over strata that have relatives; chained.
4. **Imputation:** missing in-sample pairs get the stratum relative (or the all-strata relative) for basket cost and `imputed_share`. Dropped after 4 consecutive missing weeks.
5. **Base:** the first full calendar month of collection = 100, else provisional.
6. **Basket cost:** Σ over concepts of qty × mean unit price across the geo's stores. NULL if any concept is unpriced.
7. **Time price:** cost ÷ (wage/40). QCEW wage interpolated between quarter midpoints; past the last quarter's midpoint it's held flat with `wage_is_projected` (provisional: exempt from `no_silent_revision`).

## Before any publication
- Weights: `config/weights_2025.json` holds the BLS CPI-U relative importances, December 2025 (verified 2026-09-19; how it was reconciled is in the file). Refresh each year when BLS publishes the new table. bls.gov blocks scripts, so transcribe it, then check that group totals equal the sum of their strata, and check each code at `data.bls.gov/timeseries/CUUR0000SE<code>`.
- Basket: `config/basket_tfp2021.json` is **generated**. Change `config/basket_calibration.json` or the TFP table, then run `python -m execution.calibrate_basket`; a test fails if the file drifts. A person must set `status` to `final`. The `config_verified` gate blocks anything else.
- Household: USDA reference family of four (decided 2026-09-19; spec §11 Q2 closed).
- Benchmark: USDA publishes the national monthly cost of this basket (`usda-thriftyplan-june2021-present.xlsx` at fna.usda.gov). Ours is priced with store-brand stand-ins per category, so a gap against it is mostly method, not geography.

## Revisions
Recomputing is free. Changing a published number is not: bump `method_version` (ADR 0001).
