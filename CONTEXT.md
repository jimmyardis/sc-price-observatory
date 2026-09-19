# CONTEXT — ubiquitous language

Use these words exactly, in code, names, and conversation.

## Domain

- **Observatory**: the whole system. Groceries are its first **domain**; rent, electricity, fuel, and insurance come later.
- **Banner**: a retail chain as shoppers know it (`kroger`, `harris_teeter`, `publix`, `food_lion`, `aldi`, `walmart`).
- **Mapping family**: the banner key in `item_map`. `kroger` covers Kroger and Harris Teeter, which share UPC product IDs.
- **Store**: one physical location, `store_id = '{banner}:{retailer_num}'`, assigned to a county by coordinates.
- **Geo**: a county (5-digit FIPS), a **region** (`region:upstate|midlands|pee_dee|lowcountry`), or the state (`45`).
- **Item**: one thing we price, at one **tier** (`store_brand | national_brand | unbranded`). Example: `peanut_butter_store`.
- **Concept**: what a basket buys; tier variants share it. Example: `peanut_butter`.
- **Stratum**: a BLS CPI item stratum (e.g. `FJ01` milk). The unit of lower-level aggregation and weighting.
- **Norm unit**: the unit a unit price is expressed in: `lb | oz | fl_oz | count | dozen`.
- **Observation**: one price seen once. Append-only. Carries its own **pack size**, never assumed.
- **Price type**: `shelf` (regular), `promo` (sale/loyalty), `member`, `unknown`.
- **Effective price**: the one unit price per (week, store, item) after re-collections: the latest row wins.
- **Week**: the Monday (America/New_York) of the collection week.

## Method

- **Series**: `shelf` is the headline and excludes promos; `promo_incl` is the lowest price any shopper could have paid.
- **Price relative**: p_t / p_{t-1} for a (store, item) pair observed in **both** adjacent collection weeks.
- **Jevons**: geometric mean of relatives within a stratum and geo.
- **Chain**: headline index_t = index_{t-1} × Σ w_s R_s, with weights renormalized over strata that have relatives.
- **Base**: the first full calendar month of collection = 100. Before that month exists, `base_status = provisional`.
- **Imputation**: a missing in-sample pair carries its stratum relative forward; after 4 consecutive missing weeks it is **dropped**.
- **Imputed share**: imputed pairs / (observed + imputed) for a geo-week. Above 0.25 the cell is **suppressed**.
- **Coverage rule**: a county needs 3+ stores across 2+ banners. Otherwise it is **thin coverage**, rendered hatched, and **rolled up** to its region (or to the state).
- **Standard basket**: weekly quantities per concept for the reference household, priced at store brand or unbranded. The **national basket** swaps in national brands.
- **Tier gap**: the geometric mean of national ÷ store-brand unit price across paired concepts.
- **Time price** (**hours to basket**): basket cost ÷ (QCEW average weekly wage ÷ 40). Wages after the last published quarter are **projected** (held flat, flagged).
- **Method version**: labels a computation. Changing a published number requires a new one.

## Publishing

- **Snapshot**: an immutable JSON file for one week and method version. The only thing the site reads.
- **Draft**: a snapshot written to `.tmp/snapshots/`, never public; QA may fail.
- **QA gate**: a check that halts publication. **Overrides** are human-confirmed exceptions in `config/qa_overrides.json`.
- **Silent revision**: an already-published value that changed under the same method version. Always blocked.

## Module map

| Module | Role |
|---|---|
| `execution/collectors/_base.py` | PoliteClient, save_payload, week_of, alerts, insert_observations |
| `execution/collectors/kroger.py` | KrogerAPI, discover (stores), collect (observations) |
| `execution/normalize_units.py` | parse_pack_size |
| `execution/match_items.py` | propose candidates, check item_map |
| `execution/load_reference.py` | config → DB |
| `execution/compute_index.py` | effective_prices, compute_geo, rebase, basket_cost |
| `execution/compute_time_price.py` | fetch_wages (QCEW), wage_at, hours_to_basket |
| `execution/qa_checks.py` | gates → `.tmp/qa_report_{week}.json` |
| `execution/export_snapshot.py` | build, publish, manifest |
| `execution/run_pipeline.py` | the one command |
