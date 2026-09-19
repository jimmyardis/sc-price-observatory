# Directive: normalize_and_match

**Goal:** Every observation's price becomes a comparable unit price, and every retailer SKU is tied to one of our items by a human decision.

## Normalize (`execution/normalize_units.py`)
- `parse_pack_size(size, norm_unit, sold_by)` converts within a dimension only (mass↔mass, volume↔volume, count↔dozen). It never guesses density, so "16 oz" can't become fluid ounces.
- Multipacks multiply ("6 ct / 12 fl oz" → 72 fl_oz).
- If it returns None, the observation is skipped and logged. Pack size is never assumed.
- **Shrinkflation must show as inflation.** The observed pack size goes on each row. When it drifts from the mapped pack, a `pack_size_changed` problem is logged, and the unit price captures the change.

## Match (`execution/match_items.py`)
1. `propose --location <id>` searches each item's `search_terms` at a reference store and ranks up to 5 candidates per item (term hits, store-brand or brand-hint match, parseable size). Output goes to `.tmp/item_map_candidates.csv`.
2. A human copies the right row per item into `config/item_map.csv` and sets `confidence` (`exact`: the item as defined; `close`: same product, different pack; `proxy`: nearest substitute), `mapped_by`, and `mapped_at`.
3. `check` validates the file: duplicates, unknown items, confidence values, dates, and a warning for items at fewer than 4 banners.
4. Commit `config/item_map.csv`. `load_reference` syncs it to the DB.

## Item list rules (spec §4)
- ~60 items, 40 minimum. Every item stocked by at least 4 of the 5 banners.
- 15 or more concepts in both store and national tiers (currently 17).
- Freeze the list quarterly. Log changes in `config/CHANGELOG.md` with effective dates.
