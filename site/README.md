# site/ — public frontend (Phase 2, not built yet)

Contract, fixed now so collection can start without it:

- Static. Reads `snapshots/latest.json`, `snapshots/<method_version>/<week>.json`, and `snapshots/manifest.json`. **Never queries the database.**
- Snapshot schema: `sc-price-observatory/snapshot@1` (see `execution/export_snapshot.py::build`).
- Above the fold: `headline.sentence`, `headline.change.wow` / `.yoy`, county choropleth on `geos[].levels.hours_to_basket`.
- Counties with `status: "thin_coverage"` render **hatched** and point to `rolled_up_to`; `suppressed` and `no_data` are shown as such, never interpolated.
- Required pages: `/methodology`, `/basket` (from `basket[]`), `/coverage` (from `geos[].coverage`), `/data` (every file in `manifest.json`, revisions included), `/code`.
