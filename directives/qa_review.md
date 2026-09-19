# Directive: qa_review

**Goal:** Nothing gets published through a failed gate. Real anomalies get confirmed by a human, not waved through.

## Tool
`execution/qa_checks.py` runs inside `export_snapshot` and writes `.tmp/qa_report_{week}.json`.

| Gate | Fails when | Usual cause |
|---|---|---|
| week_has_observations | no rows this week | collector didn't run |
| unit_price_outlier | unit price >5× or <0.2× trailing 8-week median (item-store, ≥3 prior weeks) | bad mapping, pack parse error, real spike |
| imputed_share | a published cell above 0.25 | should be impossible: suppression runs first |
| banner_store_drop | a banner's observed stores fell >20% WoW | broken collector, not a market event |
| stratum_relative | a published stratum moved outside ±10% WoW | outlier, mapping swap, real shock |
| unknown_price_type | >10% of rows `unknown` | collector can't classify prices |
| config_verified | weights unverified or basket draft | Phase 0 |
| no_silent_revision | a published value changed under the same method_version | late re-collection, code change |

## When a gate fails
1. Read the report and find the row (`obs_id`, `key`).
2. Pull the raw payload: `.tmp/raw/<banner>/<hash[:2]>/<hash>.json`.
3. If the data is wrong, fix the cause (mapping, parser, collector) and re-collect. Observations are append-only, so the new rows supersede the old ones.
4. If the data is right (e.g. an egg shock), add an override to `config/qa_overrides.json`: `{gate, key, confirmed_by, reason}`. Commit it; overrides are part of the public record.
5. For `no_silent_revision`, bump `method_version` and say why in the changelog. Never delete old snapshots.
