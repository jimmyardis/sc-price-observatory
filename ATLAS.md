# ATLAS — South Carolina Price Observatory

## Meta
| Field | Value |
|---|---|
| Last Active | 2026-09-19 |
| Status | building |
| Path | /home/wner/sc-price-observatory |
| Spec | C:\Users\Owner\Downloads\sc-grocery-index-spec.md (v0.1 draft) |
| Phase | 0: prove the pipeline |

## Current State
**The measured pipeline runs weekly on its own now, and there is 20 years of labeled history beside it.** A systemd user timer (`sc-price-weekly.timer`, Tuesdays 03:00; it catches up if WSL was down) collects Kroger prices, writes draft snapshots, and backs the DB up to C:. The first run is 2026-09-22. The new *regional prices, local wages* reconstruction (ADR 0004) prices a fixed 22-concept basket from BLS South average prices, monthly 2006-01 to 2026-08 (246 of 248 months publishable), against each county's QCEW wage. County hours already run 2014 to now; 2006–2013 wages are waiting on BLS API quota. 82 tests pass. Nothing publishes until the weights and basket quantities are real.

## Next Action
Replace the placeholder basket quantities (USDA Thrifty Food Plan calibration) and the BLS relative importances. That one change unblocks publication of both the measured and the regional snapshots.

## Blockers
- Walmart, Aldi, Publix, and Food Lion collectors are deliberately stubbed until the ToS/legal question (spec §11 Q1) has a real answer.
- 2006–2013 county wages need about 6 BLS API queries; today's 25-query quota is spent. The Tuesday run picks it up automatically, or sooner with a free `BLS_API_KEY` in `.env`.

## Open Questions
- Richland has 3 Krogers but only one banner, so the county reads `thin_coverage` until a second banner clears the legal review. The state and Midlands cells publish.
- Real BLS CPI-U relative importances (Dec 2025) per stratum; bls.gov blocks scripted fetches, so pull them by hand.
- Basket quantities: calibrate against the USDA Thrifty Food Plan 2021 market basket? Family of three confirmed?
- Region membership for boundary counties (York/Chester/Lancaster, Sumter/Clarendon, Georgetown, Allendale).
- Promo handling test, backfill, publication cadence (spec §11 Q3–5).
- Postgres path untested (no local server). Test before Phase 1 migration.
- Overlap week 1: the regional basket's 22 concepts cost $79.48 at 3 Richland Krogers (store brand) vs $89.90 BLS South average (all brands), 12% below. Is the gap brand mix or real? Needs more weeks and banners before it's a claim.
- `data/observatory.db` is gitignored and is the only copy of observations apart from the weekly C: backup. Is an off-machine backup (private repo or cloud) wanted?

## Session Log
### 2026-09-19
- First commit (`d4fd2d4`). The repo had zero commits before this session.
- **Historical pricing answer:** store-level SC history can't be recovered. Built the defensible alternative, *regional prices, local wages*: BLS South average prices (AP series, titles verified at data.bls.gov) × county QCEW wages, monthly from 2006. Rejected back-casting today's basket with CPI (ADR 0004).
- Basket: 22 of 43 concepts have like-for-like South series. Yogurt and 2-liter soft drinks were dropped (South series start in 2018) to keep 20 years; coffee was dropped (published only 2021–25); OJ was dropped (frozen concentrate ≠ what we price). All 21 exclusions have reasons in config, enforced by the `concepts_accounted` gate.
- Gaps: U.S. item relative → South basket relative → carry ≤ 2 months, past-only (publishing a new month never moves an old one). Suppressed: 2020-04 (COVID) and 2025-10 (shutdown, BLS published nothing). The reconstruction tracks CPI food-at-home South closely (cost/CPI stays within 0.28–0.30 over 20 years).
- **Bug fixed (both pipelines):** hours on a projected wage would have tripped `no_silent_revision` as soon as the next QCEW quarter was published, blocking every later publish. `wage_is_projected` now starts at the last quarter's midpoint, and projected hours are exempt from the gate. Found before any publish, so method 0.1.0 is unchanged.
- Weekly automation: a systemd user timer instead of cron, because `Persistent=true` catches up runs missed while WSL is down (last night's crash). The smoke test under systemd passed. The weekly DB backup goes to `/mnt/c/Users/Owner/sc-price-observatory-backups/`.
- The BLS no-key API quota (25/day) ran out mid-session, so 2006–2013 wages are pending; the fetch is incremental and closed years are cached. QCEW open-data CSV only goes back to 2014, and pre-2014 comes from the `ENU…` timeseries.
- Left mid-stream: nothing published (config gates); site not built.

### 2026-09-17
- Kroger production app registered (Products + Locations, scope `product.compact`); credentials in `.env` (chmod 600, gitignored).
- `discover`: 43 SC stores across 13 counties. Fuel centers are separate locationIds with their own departments; now filtered by `is_grocery_store`. Harris Teeter's chain string is confirmed `HART`.
- **Parser bug found and fixed:** retailers write both "5 ct / 12 oz" (5 franks, 12 oz total) and "4 ct / 14.5 oz" (4 cans of 14.5 oz). The string cannot disambiguate, so `parse_pack_size` now refuses to guess and a curated `count_rule` (`multiply`|`total`) per SKU resolves it. Without this, hot dogs would have been understated 5x.
- Candidate ranker now downranks organic/premium sublines (Simple Truth, Private Selection) and keywords for commodity items; Big K and Heritage Farm reclassified as value store brands.
- Ice cream moved to `oz` because retailers label tubs that way; national vanilla switched from Breyers to Tillamook, since Breyers' vanilla here is labeled "frozen dairy dessert", not ice cream.
- First real findings: national brands run ~57% above store brands per unit on the 17 paired concepts, and chasing every promo saved only 2% this week (relevant to spec §11 Q3).

### 2026-09-16
- Built Phase 0 from the spec: schema (Postgres dialect, SQLite for Phase 0), 9 directives, collectors (Kroger live; 4 gated stubs), normalize_units, match_items, compute_index, compute_time_price, qa_checks, export_snapshot, run_pipeline, 56 tests.
- Decisions: relatives use strictly adjacent collection weeks (ADR 0002); published numbers are frozen, and changing one needs a new method_version, enforced by the `no_silent_revision` gate (ADR 0001); schema additions `items.concept`, tier `unbranded`, `series` column, `basket_costs` and `time_prices` tables (ADR 0003); `config_verified` gate blocks publishing on draft weights or basket.
- Basket v1: 60 items / 43 concepts / 17 store-vs-national pairs (spec needs ≥15).
- Left mid-stream: weights and basket quantities are placeholders; item_map empty; site not started (Phase 2, contract in site/README.md).
