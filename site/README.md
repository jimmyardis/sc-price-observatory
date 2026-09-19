# site/ — the public front end

Plain HTML, one stylesheet, ES modules. **No framework, no build step, no dependencies.** Open a page and it works; the only assembly step is copying the published snapshots next to it.

```bash
ops/build_site.sh && python3 -m http.server -d .tmp/site 8765   # http://localhost:8765
```

`.github/workflows/pages.yml` runs the same script and deploys to
<https://jimmyardis.github.io/sc-price-observatory/> on every push that touches `site/` or `snapshots/`.

## The contract

- **The site reads published snapshots and nothing else.** No database, no API, no config files: if a number should appear on a page, it has to be in a snapshot first (that is why the snapshot carries basket provenance and `household_short`).
- Files read: `snapshots/latest.json`, `snapshots/regional_latest.json`, `snapshots/manifest.json`, and `data/sc-counties.geojson`.
- A page that cannot load its data says so plainly (`fail()`); it never renders a placeholder number.

## Pages

| Page | What it shows |
|---|---|
| `index.html` | Headline hours and basket cost, county choropleth (regional series), hours over time for a chosen county, basket cost against the BLS food-at-home index, and the measured-vs-regional overlap |
| `method.html` | How the measured series works, what the reconstruction is and is not, the QA gates, revisions, limitations |
| `basket.html` | Every item, its weekly quantity, the USDA basis for that quantity, its CPI weight, and the items excluded from the reconstruction with reasons |
| `coverage.html` | Status of every geography, the coverage rule, and wage coverage for the reconstruction |
| `data.html` | The manifest: every file ever published with its checksum, plus how to cite and re-check it |

## Rules for charts

Follow the same house style as the rest of the project — honest before pretty.

- **Never draw measured and reconstructed values as one line.** The reconstruction is labelled wherever it appears; `overlap[]` is the one place both are shown together, side by side on the same items.
- Status other than `published` (thin coverage, suppressed, no data) renders as itself. **Never interpolate to fill a gap**, on a map or in a series.
- Sequential blue ramp for magnitude (the map); the validated categorical pair (blue/orange) for two-series charts; gray for context series. Dark mode is a selected set of steps, not an automatic flip.
- Every chart carries a hover tooltip, a legend when there are two or more series, and a **Table** toggle — the numbers must be reachable without reading colour.
