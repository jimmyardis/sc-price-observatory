"""One command, one number. Phase 0: Kroger API -> Richland -> index -> snapshot.

    python -m execution.run_pipeline --draft                 # full run, draft snapshot (Phase 0 default)
    python -m execution.run_pipeline                         # full run, publish only if every QA gate passes
    python -m execution.run_pipeline --skip-collect --draft  # recompute from existing observations

Steps: migrate -> load reference config -> [discover stores if none] -> collect
-> fetch wages -> compute index -> compute time price -> QA -> export.
Exit code 0 = published (or draft written); 1 = QA halted; 2 = collector blocked.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date, timedelta

from execution import compute_index, compute_time_price, config, export_snapshot, load_reference
from execution.collectors._base import CollectorBlocked
from execution.db import DB

log = logging.getLogger("pipeline")


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--draft", action="store_true", help="write a draft snapshot to .tmp/ instead of publishing")
    ap.add_argument("--skip-collect", action="store_true")
    ap.add_argument("--skip-wages", action="store_true")
    ap.add_argument("--week", help="Monday to export (default: latest computed)")
    args = ap.parse_args(argv)

    db, cfg = DB(), config.collection()
    db.migrate()
    log.info("reference: %s", load_reference.run(db))

    if not args.skip_collect:
        from execution.collectors import kroger

        api = kroger.KrogerAPI.from_env(min_interval=cfg["kroger"]["min_seconds_between_requests"])
        try:
            if not db.query("SELECT 1 FROM stores LIMIT 1"):
                log.info("no stores yet; discovering: %d SC stores", len(kroger.discover(db, api, cfg)))
            log.info("collect: %s", kroger.collect(db, api, cfg))
        except CollectorBlocked as e:
            log.error("%s — see .tmp/alerts/. Not publishing this week.", e)
            return 2

    if not args.skip_wages:
        try:
            log.info("wages fetched: %s",
                     compute_time_price.fetch_wages(db, config.geo(), date.today() - timedelta(days=548)))
        except Exception as e:  # stale wages are flagged downstream; don't lose the price run
            log.warning("wage fetch failed (%s); using stored wages", e)

    items, weights, basket, geo = config.items(), config.weights(cfg), config.basket(cfg), config.geo()
    log.info("index: %s", compute_index.run(db, cfg, items, weights, basket, geo))
    log.info("time prices: %s", compute_time_price.run(db, cfg))

    week = date.fromisoformat(args.week) if args.week else export_snapshot.latest_week(db, cfg["method_version"])
    if not week:
        log.error("no observations computed; nothing to export")
        return 1
    result = export_snapshot.run(db, cfg, week, items, weights, basket, geo, config.qa_overrides(), args.draft)
    print(json.dumps(result, indent=1, default=str))
    if not result["published"] and not args.draft:
        log.error("QA halted publication: %s", result["qa"]["failed_gates"])
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
