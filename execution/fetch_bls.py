"""Reference series from the BLS public API: stored as published, never modeled.

Two uses:
  - BLS average prices (AP) and CPI for the South region -> reference_values.
    They price the regional basket and give the "SC vs the South" comparison.
  - QCEW county wages for quarters before 2014, which the open-data CSV that
    compute_time_price uses doesn't cover -> wages.

No key needed. Without BLS_API_KEY the API allows 25 queries/day, 25 series and
10 years per query; with one (free, from bls.gov/developers) 500/day, 50 series,
20 years. Every raw response is kept under .tmp/raw/bls/. Fetches are
incremental: a series is only re-requested from the last year already stored,
and responses for closed past years are cached in .tmp/cache/bls/.

    python -m execution.fetch_bls reference [--since 2006]
    python -m execution.fetch_bls wage-history [--since 2006]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
from collections import defaultdict
from datetime import date, datetime, timezone

from execution.collectors._base import PoliteClient, save_payload
from execution.config import TMP
from execution.compute_time_price import STATE_FIPS, derive_regions, quarter_start

API = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
log = logging.getLogger("bls")


class BLSQuotaExceeded(RuntimeError):
    """The daily query limit is spent. Stored data is intact; rerun tomorrow."""


def parse_period(year: str, period: str) -> date | None:
    """'2026','M08' -> 2026-08-01; 'Q03' -> 2026-07-01; annual/semiannual codes -> None."""
    kind, n = period[0], int(period[1:])
    if kind == "M" and 1 <= n <= 12:
        return date(int(year), n, 1)
    if kind == "Q" and 1 <= n <= 4:
        return quarter_start(int(year), n)
    return None


def parse_response(doc: dict) -> list[dict]:
    """API JSON -> [{series_id, period, value, footnotes}]. Unpublished values ('-') are skipped."""
    if doc.get("status") != "REQUEST_SUCCEEDED":
        msg = " ".join(doc.get("message", []))
        if "threshold" in msg.lower():
            raise BLSQuotaExceeded(msg)
        raise RuntimeError(f"BLS API: {doc.get('status')}: {msg}")
    rows = []
    for s in doc["Results"]["series"]:
        for d in s["data"]:
            period = parse_period(d["year"], d["period"])
            try:
                value = float(d["value"].replace(",", ""))
            except ValueError:
                continue
            if period is None:
                continue
            notes = "; ".join(f["text"] for f in d.get("footnotes", []) if f.get("text"))
            rows.append({"series_id": s["seriesID"], "period": period, "value": value, "footnotes": notes or None})
    return rows


class BLSClient:
    def __init__(self, key: str | None = None, session=None, sleep=None):
        self.key = key if key is not None else os.environ.get("BLS_API_KEY")
        self.max_series, self.max_years = (50, 20) if self.key else (25, 10)
        kw = {"session": session} if session else {}
        if sleep:
            kw["sleep"] = sleep
        self.http = PoliteClient("bls", min_interval=1.0, **kw)
        self.queries = 0
        self.today = date.today()

    @staticmethod
    def _cache_path(body: dict):
        """Closed past years don't change often enough to spend the daily quota on. Delete to refetch."""
        key = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
        return TMP / "cache" / "bls" / f"{key}.json"

    def fetch(self, series_ids: list[str], start_year: int, end_year: int) -> tuple[list[dict], list[str]]:
        rows, hashes = [], []
        ids = sorted(set(series_ids))
        for i in range(0, len(ids), self.max_series):
            batch = ids[i:i + self.max_series]
            y0 = start_year
            while y0 <= end_year:
                y1 = min(y0 + self.max_years - 1, end_year)
                body = {"seriesid": batch, "startyear": str(y0), "endyear": str(y1)}
                cache = self._cache_path(body) if y1 < self.today.year else None
                if cache and cache.exists():
                    content = cache.read_bytes()
                else:
                    resp = self.http.request("POST", API, json={**body, "registrationkey": self.key} if self.key else body)
                    self.queries += 1
                    content = resp.content
                h = save_payload("bls", content)
                got = parse_response(json.loads(content))
                if cache and not cache.exists():
                    cache.parent.mkdir(parents=True, exist_ok=True)
                    cache.write_bytes(content)
                for r in got:
                    r["payload_hash"] = h
                rows += got
                hashes.append(h)
                y0 = y1 + 1
        return rows, hashes


def store(db, rows: list[dict], source: str) -> dict:
    """Upsert values. A changed value is a BLS revision: kept, counted, and logged."""
    have = {(r["series_id"], str(r["period"])): float(r["value"])
            for r in db.query("SELECT series_id, period, value FROM reference_values")}
    new = revised = 0
    fetched_at = datetime.now(timezone.utc).isoformat()
    for r in rows:
        key = (r["series_id"], r["period"].isoformat())
        old = have.get(key)
        if old is None:
            new += 1
        elif abs(old - r["value"]) > 1e-9:
            revised += 1
            log.warning("BLS revised %s %s: %s -> %s", *key, old, r["value"])
        else:
            continue
        db.upsert("reference_values", {"series_id": r["series_id"], "period": key[1], "value": r["value"],
                                       "footnotes": r["footnotes"], "payload_hash": r["payload_hash"]},
                  ["series_id", "period"])
    for sid in {r["series_id"] for r in rows}:
        db.upsert("reference_series", {"series_id": sid, "source": source, "fetched_at": fetched_at},
                  ["series_id"])
    db.commit()
    return {"new": new, "revised": revised}


def fetch_reference(db, client: BLSClient, series_ids: list[str], since: int, today: date | None = None) -> dict:
    """Fetch each series from the last year already stored (or `since`) through this year."""
    today = today or date.today()
    last = {r["series_id"]: str(r["p"]) for r in db.query(
        "SELECT series_id, MAX(period) AS p FROM reference_values GROUP BY series_id")}
    by_start: dict[int, list[str]] = defaultdict(list)
    for sid in series_ids:
        by_start[int(last[sid][:4]) if sid in last else since].append(sid)
    total = {"new": 0, "revised": 0, "queries": 0}
    for start, ids in sorted(by_start.items()):
        rows, _ = client.fetch(ids, start, today.year)
        res = store(db, rows, "BLS API")
        total["new"] += res["new"]
        total["revised"] += res["revised"]
    total["queries"] = client.queries
    return total


# --- QCEW before 2014 ----------------------------------------------------------
# Series: ENU{area}{datatype}{size 0}{ownership 0}{industry 10}
#   datatype 1 = employment (monthly), 3 = total quarterly wages, 4 = average weekly wage

def qcew_series(area: str, datatype: int) -> str:
    return f"ENU{area}{datatype}0010"


def wage_rows(values: list[dict], geo_parent: dict[str, str | None]) -> dict[tuple[str, date], dict]:
    """EN series values -> {(geo_id, quarter): wages row}, with regions employment-weighted like parse_qcew."""
    by: dict[tuple[str, int], dict[date, float]] = defaultdict(dict)
    for v in values:
        sid = v["series_id"]
        by[(sid[3:8], int(sid[8]))][v["period"]] = v["value"]
    quarters: dict[date, dict[str, dict]] = defaultdict(dict)
    for (area, dtype), series in by.items():
        if dtype != 4:
            continue
        geo_id = STATE_FIPS if area == STATE_FIPS + "000" else area
        if geo_id not in geo_parent:
            continue
        for q, wage in series.items():
            months = [by[(area, 1)].get(date(q.year, q.month + k, 1)) for k in range(3)]
            emp = sum(months) / 3 if all(m is not None for m in months) else 0.0
            quarters[q][geo_id] = {"avg_weekly_wage": wage, "total_qtrly_wages": by[(area, 3)].get(q, 0.0),
                                   "avg_employment": emp, "source": "QCEW (BLS timeseries API)"}
    out = {}
    for q, geos in quarters.items():
        for geo_id, row in derive_regions(geos, geo_parent).items():
            out[(geo_id, q)] = row
    return out


def fetch_wage_history(db, client: BLSClient, geo_rows: list[dict], since: int, until: int = 2013) -> dict:
    """County, state, and region wages for quarters the open-data CSV lacks. Skips quarters already stored."""
    parent = {g["geo_id"]: g["parent_geo_id"] for g in geo_rows}
    have = {str(r["quarter"]) for r in db.query("SELECT DISTINCT quarter FROM wages WHERE geo_id = ?", (STATE_FIPS,))}
    wanted = [y for y in range(since, until + 1) if any(quarter_start(y, q).isoformat() not in have for q in (1, 2, 3, 4))]
    if not wanted:
        return {"quarters": 0, "queries": 0}
    areas = [STATE_FIPS + "000"] + [g["geo_id"] for g in geo_rows if g["geo_type"] == "county"]
    ids = [qcew_series(a, t) for a in areas for t in (1, 3, 4)]
    rows, _ = client.fetch(ids, min(wanted), max(wanted))
    out = wage_rows(rows, parent)
    for (geo_id, q), row in out.items():
        if q.isoformat() in have:
            continue
        db.upsert("wages", {"geo_id": geo_id, "quarter": q.isoformat(), **row}, ["geo_id", "quarter"])
    db.commit()
    return {"quarters": len({q for _, q in out}), "queries": client.queries}


if __name__ == "__main__":
    from execution import config
    from execution.db import DB

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["reference", "wage-history"])
    ap.add_argument("--since", type=int, default=None)
    args = ap.parse_args()
    config.load_env()
    db = DB()
    db.migrate()
    reg = config.regional()
    client = BLSClient()
    if args.command == "reference":
        from execution.compute_regional import series_needed

        print(json.dumps(fetch_reference(db, client, series_needed(reg), args.since or int(reg["start_month"][:4]))))
    else:
        print(json.dumps(fetch_wage_history(db, client, config.geo(), args.since or int(reg["start_month"][:4]))))
