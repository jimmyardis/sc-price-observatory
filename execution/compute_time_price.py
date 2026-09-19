"""Time price: hours of average local work that buy the weekly basket.

    hours_to_basket = weekly_basket_cost / (avg_weekly_wage / 40)

Wages: BLS QCEW county average weekly wage, all industries, all ownerships
(own_code 0, industry 10). Quarterly, ~5-6 month lag. Regions are
employment-weighted from their counties. Weekly wages are linearly
interpolated between quarter midpoints; past the midpoint of the last published
quarter the last value is held and flagged wage_is_projected, because the next
quarter will move it.

    python -m execution.compute_time_price fetch-wages [--since 2025Q1]
    python -m execution.compute_time_price compute
"""
from __future__ import annotations

import argparse
import csv
import io
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

import requests

QCEW_URL = "https://data.bls.gov/cew/data/api/{year}/{qtr}/industry/10.csv"
STATE_FIPS = "45"


def quarter_start(year: int, q: int) -> date:
    return date(year, 3 * (q - 1) + 1, 1)


def quarter_end(qs: date) -> date:
    return next_quarter(qs) - timedelta(days=1)


def next_quarter(qs: date) -> date:
    return date(qs.year + 1, 1, 1) if qs.month == 10 else date(qs.year, qs.month + 3, 1)


def quarter_mid(qs: date) -> date:
    return qs + (quarter_end(qs) - qs) / 2


def parse_qcew(text: str, geo_parent: dict[str, str | None]) -> dict[str, dict]:
    """QCEW industry-10 CSV -> {geo_id: wage row} for SC state, counties, and derived regions."""
    out: dict[str, dict] = {}
    for r in csv.DictReader(io.StringIO(text)):
        if not r["area_fips"].startswith(STATE_FIPS) or r["own_code"] != "0":
            continue
        geo_id = STATE_FIPS if r["area_fips"] == "45000" else r["area_fips"]
        if geo_id not in geo_parent:
            continue  # 45999 "unknown or undefined"
        wage = float(r["avg_wkly_wage"] or 0)
        if r["disclosure_code"] == "N" or wage <= 0:
            continue
        emp = sum(float(r[f"month{i}_emplvl"] or 0) for i in (1, 2, 3)) / 3
        out[geo_id] = {"avg_weekly_wage": wage, "total_qtrly_wages": float(r["total_qtrly_wages"] or 0),
                       "avg_employment": emp, "source": "QCEW"}
    return derive_regions(out, geo_parent)


def derive_regions(out: dict[str, dict], geo_parent: dict[str, str | None]) -> dict[str, dict]:
    """Add region rows, employment-weighted from their counties: total wages / employment / 13 weeks."""
    regions: dict[str, list[dict]] = defaultdict(list)
    for geo_id, row in list(out.items()):
        parent = geo_parent.get(geo_id)
        if parent and parent.startswith("region:"):
            regions[parent].append(row)
    for region, rows in regions.items():
        wages, emp = sum(r["total_qtrly_wages"] for r in rows), sum(r["avg_employment"] for r in rows)
        if emp > 0:
            out[region] = {"avg_weekly_wage": round(wages / emp / 13, 2), "total_qtrly_wages": wages,
                           "avg_employment": emp, "source": "QCEW-derived (employment-weighted counties)"}
    return out


def wage_at(week: date, series: list[tuple[date, float]]) -> tuple[float | None, bool]:
    """Interpolated weekly wage at `week` from [(quarter_start, wage)], and whether it is projected."""
    if not series:
        return None, False
    pts = sorted((quarter_mid(q), w) for q, w in series)
    # Past the last quarter's midpoint the wage is held flat, and the next published
    # quarter will move it: provisional, so flagged (and exempt from no_silent_revision).
    projected = week > pts[-1][0]
    if week <= pts[0][0]:
        return pts[0][1], projected
    if week >= pts[-1][0]:
        return pts[-1][1], projected
    for (d0, w0), (d1, w1) in zip(pts, pts[1:]):
        if d0 <= week <= d1:
            return w0 + (w1 - w0) * (week - d0).days / (d1 - d0).days, projected
    raise AssertionError("unreachable")


def hours_to_basket(cost: float | None, weekly_wage: float | None) -> float | None:
    if cost is None or not weekly_wage:
        return None
    return round(cost / (weekly_wage / 40), 2)


# --- DB wrappers -------------------------------------------------------------

def fetch_wages(db, geo_rows: list[dict], since: date, session=requests) -> list[str]:
    parent = {g["geo_id"]: g["parent_geo_id"] for g in geo_rows}
    fetched = []
    have = {str(r["quarter"]) for r in db.query("SELECT DISTINCT quarter FROM wages WHERE geo_id = ?", (STATE_FIPS,))}
    q = quarter_start(since.year, (since.month - 1) // 3 + 1)
    while q <= date.today():
        label = f"{q.year}Q{(q.month - 1) // 3 + 1}"
        if q.isoformat() not in have:
            r = session.get(QCEW_URL.format(year=q.year, qtr=(q.month - 1) // 3 + 1), timeout=120,
                            headers={"User-Agent": "sc-price-observatory/0.1"})
            if r.status_code == 404:
                break  # not yet published
            r.raise_for_status()
            for geo_id, row in parse_qcew(r.text, parent).items():
                db.upsert("wages", {"geo_id": geo_id, "quarter": q.isoformat(), **row}, ["geo_id", "quarter"])
            db.commit()
            fetched.append(label)
        q = next_quarter(q)
    return fetched


def run(db, cfg: dict) -> int:
    method = cfg["method_version"]
    computed_at = datetime.now(timezone.utc).isoformat()
    wages: dict[str, list[tuple[date, float]]] = defaultdict(list)
    for r in db.query("SELECT geo_id, quarter, avg_weekly_wage FROM wages"):
        wages[r["geo_id"]].append((date.fromisoformat(str(r["quarter"])), float(r["avg_weekly_wage"])))
    rows = db.query("SELECT geo_id, week, series, cost FROM basket_costs WHERE basket = 'standard' "
                    "AND method_version = ?", (method,))
    for r in rows:
        week = date.fromisoformat(str(r["week"]))
        wage, projected = wage_at(week, wages.get(r["geo_id"], []))
        cost = float(r["cost"]) if r["cost"] is not None else None
        db.upsert("time_prices", {
            "geo_id": r["geo_id"], "week": week.isoformat(), "series": r["series"],
            "basket_cost": cost, "avg_weekly_wage": round(wage, 2) if wage else None,
            "hours_to_basket": hours_to_basket(cost, wage), "wage_is_projected": projected,
            "method_version": method, "computed_at": computed_at,
        }, ["geo_id", "week", "series", "method_version"])
    db.commit()
    return len(rows)


if __name__ == "__main__":
    from execution import config
    from execution.db import DB

    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["fetch-wages", "compute"])
    ap.add_argument("--since", default=None, help="e.g. 2025Q1 (default: 4 quarters back)")
    args = ap.parse_args()
    db = DB()
    db.migrate()
    if args.command == "fetch-wages":
        if args.since:
            y, q = args.since.upper().split("Q")
            since = quarter_start(int(y), int(q))
        else:
            since = date.today() - timedelta(days=455)
        print("fetched:", fetch_wages(db, config.geo(), since))
    else:
        print("time prices:", run(db, config.collection()))
