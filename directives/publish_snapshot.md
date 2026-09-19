# Directive: publish_snapshot

**Goal:** A weekly, immutable, public snapshot the site can read without touching the database.

## Tool
- `python -m execution.run_pipeline`: the whole chain, publishing only if QA passes
- `python -m execution.export_snapshot --week YYYY-MM-DD [--draft]`: export only

## Output
- `snapshots/<method_version>/<week>.json` (schema `sc-price-observatory/snapshot@1`) and `<week>_levels.csv`
- `snapshots/latest.json`
- `snapshots/manifest.json`: every file ever published, with sha256. This backs `/data`, including revisions
- A re-publish of the same week becomes `<week>.r2.json`. Existing files are never overwritten

## What's in a snapshot
- `headline`: state hours-to-basket, basket cost, WoW/YoY change, and the sentence: "X hours of average local work buys a week of groceries for a family of three."
- `geos[]`: status (`published | thin_coverage | suppressed | no_data`), reasons, levels, index (only after `index_publish_min_weeks` = 12 and a final base), coverage (stores by banner, imputed share), tier gap
- `history`: published, non-suppressed weekly values per geo (feeds the revision gate)
- `basket[]`: every item with stratum, weight, tier, and quantity (feeds `/basket`)

## Phasing
- **Phase 2:** publish levels (basket cost, time price). State plainly that the index series begins after 12 weeks.
- **Phase 3:** publish the index alongside BLS food-at-home for the South region.
- Commit and push `snapshots/` after each publish. Publishing isn't done until it's pushed and live.
