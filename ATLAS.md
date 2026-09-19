# ATLAS — South Carolina Price Observatory

## Meta
| Field | Value |
|---|---|
| Last Active | 2026-09-17 |
| Status | building |
| Path | /home/wner/sc-price-observatory |
| Spec | C:\Users\Owner\Downloads\sc-grocery-index-spec.md (v0.1 draft) |
| Phase | 0: prove the pipeline |

## Current State
**Phase 0 is done: the pipeline produces a real number from live prices.** Kroger production credentials are in `.env`; discovery found 43 SC grocery stores (2 fuel centers filtered out) across 13 counties, including 3 Krogers in Richland. All 60 basket items are mapped in `config/item_map.csv` (42 exact, 18 close, drafted by Claude and awaiting the user's review). First live collection (week 2026-09-14, 3 Richland stores): 180 shelf + 33 promo observations, no parse problems. Standard basket $134.34, national-brand basket $160.96, promo-inclusive $131.64; time price 4.15 hours at a projected $1,296 state weekly wage. 63 tests pass. Only the `config_verified` gate blocks publication, exactly as intended.

## Next Action
Start weekly collection now (Tuesday overnight cron on `run_pipeline --draft`) so baseline accumulates, since every delayed week is unrecoverable history.

## Blockers
- Walmart, Aldi, Publix, and Food Lion collectors are deliberately stubbed until the ToS/legal question (spec §11 Q1) has a real answer.

## Open Questions
- Richland has 3 Krogers but only one banner, so the county reads `thin_coverage` until a second banner clears the legal review. The state and Midlands cells publish.
- Real BLS CPI-U relative importances (Dec 2025) per stratum; bls.gov blocks scripted fetches, so pull them by hand.
- Basket quantities: calibrate against the USDA Thrifty Food Plan 2021 market basket? Family of three confirmed?
- Region membership for boundary counties (York/Chester/Lancaster, Sumter/Clarendon, Georgetown, Allendale).
- Promo handling test, backfill, publication cadence (spec §11 Q3–5).
- Postgres path untested (no local server). Test before Phase 1 migration.

## Session Log
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
