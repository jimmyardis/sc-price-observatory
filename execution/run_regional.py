"""One command for the regional reconstruction ("regional prices, local wages").

    python -m execution.run_regional --draft        # fetch what's new, compute, write a draft snapshot
    python -m execution.run_regional                # publish only if every regional QA gate passes
    python -m execution.run_regional --skip-fetch --draft

Steps: migrate -> reference config -> BLS reference series -> QCEW wages
(open-data CSV from 2014, BLS API before that) -> compute -> QA -> export.
A spent BLS daily quota is not a failure: stored data is used and the next run
picks up where this one stopped. Exit 0 = published or draft written; 1 = QA halted.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date

from execution import compute_regional, compute_time_price, config, export_regional, fetch_bls, load_reference
from execution.db import DB

log = logging.getLogger("regional")
CSV_WAGES_FROM = date(2014, 1, 1)   # the QCEW open-data CSV starts here


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--draft", action="store_true")
    ap.add_argument("--skip-fetch", action="store_true")
    args = ap.parse_args(argv)

    config.load_env()
    db, cfg, reg = DB(), config.collection(), config.regional()
    db.migrate()
    load_reference.run(db)
    geo = config.geo()
    start_year = int(reg["start_month"][:4])

    if not args.skip_fetch:
        client = fetch_bls.BLSClient()
        try:
            log.info("reference series: %s",
                     fetch_bls.fetch_reference(db, client, compute_regional.series_needed(reg), start_year))
            if start_year < CSV_WAGES_FROM.year:
                log.info("wage history: %s",
                         fetch_bls.fetch_wage_history(db, client, geo, start_year, CSV_WAGES_FROM.year - 1))
        except fetch_bls.BLSQuotaExceeded as e:
            log.warning("BLS daily quota spent (%s); continuing with stored data", e)
        try:
            log.info("QCEW quarters fetched: %s", compute_time_price.fetch_wages(db, geo, CSV_WAGES_FROM))
        except Exception as e:  # stale wages are flagged downstream
            log.warning("QCEW CSV fetch failed (%s); using stored wages", e)

    basket = config.basket(cfg)
    log.info("compute: %s", compute_regional.run(db, reg, basket, geo))
    result = export_regional.run(db, reg, basket, config.items(), geo, config.qa_overrides(), args.draft)
    print(json.dumps(result, indent=1, default=str))
    if not result["published"] and not args.draft:
        log.error("QA halted publication: %s", result["qa"]["failed_gates"])
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
