# Directive: build_regional

**Goal:** A monthly county time price back to 2006 from published inputs only, called "regional prices, local wages" everywhere. See ADR 0004 for why this exists and what it must never become.

## Tools
- `python -m execution.run_regional [--draft] [--skip-fetch]`: the whole chain
- `python -m execution.fetch_bls reference` / `wage-history`: fetch only
- `python -m execution.compute_regional`, `python -m execution.export_regional [--draft]`

## Inputs
- `config/regional_basket.json`: concept → BLS South series, unit conversion (`norm_per_bls_unit`), match quality, exclusions with reasons, imputation rules, `method_version`
- Quantities: the standard basket (`basket_file` in `collection.json`). The draft-basket gate applies here too
- Wages: QCEW open-data CSV from 2014 (`compute_time_price.fetch_wages`); BLS API series `ENU{fips}{1,3,4}0010` before that

## BLS API limits
No key: 25 queries/day, 25 series and 10 years per query. Full refetch ≈ 12 queries; weekly incremental ≈ 3. A spent quota logs a warning and the run continues on stored data. Closed past years are cached in `.tmp/cache/bls/`. For headroom, register a free key at https://data.bls.gov/registrationEngine/ and put `BLS_API_KEY=` in `.env` (500/day, 50 series, 20 years).

## Adding or changing a concept
1. Confirm the series title at `https://data.bls.gov/timeseries/<id>`, and check it is published for area 0300 across the whole window.
2. Changing the concept set or conversions changes published numbers, so bump `method_version`.
3. The `concepts_accounted` gate fails if any standard-basket concept is neither priced nor excluded.

## QA gates (regional)
`concepts_accounted`, `config_verified`, `wages_cover_history`, `no_silent_revision`. Report: `.tmp/qa_report_regional_<month>.json`.

## Publishing
`snapshots/regional/<method_version>/<month>.json` plus `_hours.csv` and `_concepts.csv` (how every concept was priced every month), `snapshots/regional_latest.json`, and manifest entries. Commit and push `snapshots/` after publishing.
