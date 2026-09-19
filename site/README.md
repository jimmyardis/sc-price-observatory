# site/ — public frontend (Phase 2, not built yet)

Contract, fixed now so collection can start without it:

- Static. Reads `snapshots/latest.json`, `snapshots/<method_version>/<week>.json`, and `snapshots/manifest.json`. **Never queries the database.**
- Snapshot schema: `sc-price-observatory/snapshot@1` (see `execution/export_snapshot.py::build`).
- Above the fold: `headline.sentence`, `headline.change.wow` / `.yoy`, county choropleth on `geos[].levels.hours_to_basket`.
- Counties with `status: "thin_coverage"` render **hatched** and point to `rolled_up_to`; `suppressed` and `no_data` are shown as such, never interpolated.
- **Regional reconstruction** (`snapshots/regional_latest.json`, schema `sc-price-observatory/regional@1`): a separate artifact. Every chart that uses it carries its `label` ("Regional prices, local wages") and `disclaimer`, and is visually distinct from measured series. Never draw it as the same line as a measured value. `overlap[]` is the one place both appear together (same concepts, side by side). Months with `status` other than `published` are gaps, never interpolated.
- Required pages: `/methodology`, `/basket` (from `basket[]`), `/coverage` (from `geos[].coverage`), `/data` (every file in `manifest.json`, revisions included), `/code`.
