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
- `config/weights_2025.json` must hold real BLS CPI-U relative importances (Dec 2025) for each stratum, with codes checked against the BLS table. Then set `verified: true`.
- `config/basket_2026Q3.json` quantities must be calibrated (e.g. USDA Thrifty Food Plan 2021 market basket, reference family). Then set `status` to final.
- Pick and state **one** household (spec §11 Q2). The current draft says family of three to match the headline sentence.

## Revisions
Recomputing is free. Changing a published number is not: bump `method_version` (ADR 0001).
