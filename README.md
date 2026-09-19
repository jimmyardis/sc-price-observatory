# South Carolina Price Observatory

BLS publishes no CPI for South Carolina. There is no published metro CPI area anywhere in the state; the nearest official series lumps SC in with the entire Census South region. USDA publishes one national set of food plans and reprices them monthly using national CPI-U. Every "South Carolina grocery cost" figure in circulation is a national number with a formula applied on top. Nobody measures prices here. We do.

The first collector is groceries: a weekly, county-level index and a **time price**, meaning the number of hours of average local work that buys a week of groceries. Later domains (rent, electricity, fuel, insurance) are new collector scripts on the same schema, not new systems.

The point is that every number can be checked. Observations are append-only, the method is versioned, every QA gate is public, and published snapshots are never overwritten.

## Status: Phase 0 (prove the pipeline)

Built and tested offline (56 tests): schema, Kroger API collector, unit normalization, matched-model index, time price, QA gates, and snapshot export. **Not yet run against live prices**; that needs Kroger API keys and a curated `config/item_map.csv`. QCEW wage fetching is live and verified.

## Quickstart

```bash
python -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
cp .env.example .env              # add KROGER_CLIENT_ID / KROGER_CLIENT_SECRET
python -m pytest

python -m execution.load_reference                     # config -> DB
python -m execution.collectors.kroger discover         # SC Kroger/Harris Teeter stores, by county
python -m execution.match_items propose --location <locationId>   # candidates -> .tmp/
#   curate config/item_map.csv by hand, then:
python -m execution.match_items check

python -m execution.run_pipeline --draft               # one command -> a number (draft)
```

`run_pipeline` without `--draft` publishes to `snapshots/` only if every QA gate passes. It won't pass while `config/weights_2025.json` is unverified or `config/basket_2026Q3.json` is still a draft, and that's intentional.

## Layout

| Path | What |
|---|---|
| `directives/` | SOPs: what each step does, inputs/outputs, failure handling |
| `execution/` | Deterministic scripts; `run_pipeline.py` chains them |
| `execution/collectors/` | One module per banner; `_base.py` = polite HTTP, raw payloads, hard stop on 429/403 |
| `config/` | Version-controlled source of truth: items, weights, basket, item map, geo, QA overrides |
| `db/migrations/` | Postgres-dialect schema (SQLite translated for Phase 0) |
| `snapshots/` | Published, immutable JSON/CSV. The site reads only these |
| `site/` | Static frontend (Phase 2), contract in `site/README.md` |
| `docs/adr/` | Decisions worth remembering |
| `.tmp/` | Raw payloads, QA reports, alerts, drafts. Regenerable, gitignored |

Read `CONTEXT.md` for the vocabulary.
