# South Carolina Price Observatory

BLS publishes no CPI for South Carolina. There is no published metro CPI area anywhere in the state; the nearest official series lumps SC in with the entire Census South region. USDA publishes one national set of food plans and reprices them monthly using national CPI-U. Every "South Carolina grocery cost" figure in circulation is a national number with a formula applied on top. Nobody measures prices here. We do.

The first collector is groceries: a weekly, county-level index and a **time price**, meaning the number of hours of average local work that buys a week of groceries. Later domains (rent, electricity, fuel, insurance) are new collector scripts on the same schema, not new systems.

The point is that every number can be checked. Observations are append-only, the method is versioned, every QA gate is public, and published snapshots are never overwritten.

## Status: Phase 0 (prove the pipeline)

Running on live Kroger data since 2026-09-17: 43 SC stores discovered, all 60 items mapped, and a weekly collection timer (`ops/`) starting 2026-09-22. 82 tests pass. Publication is blocked, on purpose, until the weights and basket quantities are real.

**History before collection.** Store-level prices from before we started can't be recovered, so none are invented. Instead there is a separate, clearly labeled series, *regional prices, local wages*: BLS average prices for the South region × each county's QCEW wage, monthly from 2006. It is a reconstruction, published apart from the measured series and never mixed into it (ADR 0004).

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
python -m execution.run_regional --draft               # regional reconstruction, 2006 -> latest BLS month (draft)
```

Weekly automation: `ops/weekly.sh`, run by the systemd user timer `sc-price-weekly.timer` (Tuesdays 03:00; `Persistent=true`, so a run missed while WSL was down fires on the next start). It also backs up `data/observatory.db` to `/mnt/c/Users/Owner/sc-price-observatory-backups/` (keeps 12). Install it with `ln -sf $PWD/ops/sc-price-weekly.* ~/.config/systemd/user/ && systemctl --user enable --now sc-price-weekly.timer`.

`run_pipeline` without `--draft` publishes to `snapshots/` only if every QA gate passes. It won't pass while `config/weights_2025.json` is unverified or `config/basket_2026Q3.json` is still a draft, and that's intentional.

## Layout

| Path | What |
|---|---|
| `directives/` | SOPs: what each step does, inputs/outputs, failure handling |
| `execution/` | Deterministic scripts; `run_pipeline.py` chains them |
| `execution/collectors/` | One module per banner; `_base.py` = polite HTTP, raw payloads, hard stop on 429/403 |
| `config/` | Version-controlled source of truth: items, weights, basket, item map, geo, QA overrides |
| `db/migrations/` | Postgres-dialect schema (SQLite translated for Phase 0) |
| `snapshots/` | Published, immutable JSON/CSV. The site reads only these (`regional/` holds the reconstruction) |
| `ops/` | Weekly script and systemd timer |
| `site/` | Static frontend (Phase 2), contract in `site/README.md` |
| `docs/adr/` | Decisions worth remembering |
| `.tmp/` | Raw payloads, QA reports, alerts, drafts. Regenerable, gitignored |

Read `CONTEXT.md` for the vocabulary.
