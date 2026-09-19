# Directive: collect_kroger

**Goal:** One weekly pass of shelf and promo prices for every mapped item at every active Kroger and Harris Teeter store in the target counties.

**Why Kroger first:** It's the only licensed, documented source. It validates the whole pipeline against clean data before we attempt anything grey.

## Inputs
- `KROGER_CLIENT_ID`, `KROGER_CLIENT_SECRET` in `.env` (developer.kroger.com, Production app, scope `product.compact`)
- `config/collection.json`: `counties`, `banners`, `kroger.*` politeness settings
- `config/item_map.csv` rows with `banner=kroger`
- `stores` table (run `discover` first)

## Tool
- `python -m execution.collectors.kroger discover`: queries `/locations` around the `discovery_points` grid, keeps SC stores of known chains, and assigns counties via the FCC Area API. Re-run monthly: it updates `last_seen`.
- `python -m execution.collectors.kroger collect`: for each store, calls `/products?filter.productId=<≤50 ids>&filter.locationId=` and appends observations.

## Output
- `observations` rows with `source='api'`: a `shelf` row from `price.regular`, plus a `promo` row when `0 < price.promo < regular`
- Raw responses in `.tmp/raw/kroger/`, referenced by `payload_hash`
- Problems in `.tmp/problems.jsonl`: `unparseable_size`, `pack_size_changed`, `unknown_kroger_chain`

## Schedule
Weekly, **Tuesday overnight** (after most circular changeovers, before the weekend). Keep the same day every week.

## Edge cases & learnings
- A product with no price at a store is **missing**, not zero. The index imputes it and eventually drops it.
- `soldBy=WEIGHT` items are treated as priced per lb. **Verify on the first live run** that `price.regular` really is per-lb for random-weight produce and meat.
- The chain strings for Harris Teeter in `/locations` are unverified (`HART`/`HARRIS TEETER` assumed). Check `.tmp/problems.jsonl` for `unknown_kroger_chain` after the first discover.
- **Unverified:** whether Kroger or Harris Teeter operate stores in Richland County. If `discover` finds none there, pick the Phase 0 county from where stores actually are (spec intent: one county, one banner).
- Rate limits: 10,000 product calls/day, 1,600 location calls/day. Phase 0 uses about 2 calls per store.
- A 429 or 403 stops the run hard with an alert in `.tmp/alerts/`. Don't retry until a human has looked.
