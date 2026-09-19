# 3. Small, deliberate deviations from the spec's schema

**Status:** accepted (2026-09-16)

- `items.concept`: store-brand and national-brand variants of one thing share a concept, so baskets and the tier-gap finding can pair them. Generic enough for later domains.
- `items.tier` adds `unbranded` (produce, fresh meat): calling bananas "store brand" would pollute the tier-gap measure.
- `index_values.series` (`shelf` headline, `promo_incl` secondary) in the primary key, instead of overloading `method_version` or `stratum`.
- `index_values.n_banners`, `base_status`; new tables `basket_costs` (standard + national baskets) and `time_prices`.
- `wages` carries `total_qtrly_wages` and `avg_employment` so regions can be employment-weighted from counties.
- `item_map.banner` is a *mapping family*: `kroger` covers Kroger and Harris Teeter stores, which share UPC product IDs. `stores.banner` still distinguishes them.
- Geo ids: state `45`, regions `region:<slug>`, counties 5-digit FIPS.
