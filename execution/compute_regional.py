"""Regional reconstruction: "regional prices, local wages". A labeled estimate, never a measurement.

    regional basket cost (month) = sum over concepts of weekly_quantity x BLS South average price
    regional hours to basket     = regional basket cost / (county QCEW avg weekly wage / 40)

The basket is the standard basket's quantities restricted to the concepts BLS
prices in the South (config/regional_basket.json), fixed for the whole history.
A missing South price moves with the same item's U.S. city average change,
else with the South basket's geometric-mean change, else (a month BLS published
nothing) the last price is carried for at most max_carry_months.
Months whose imputed share of cost exceeds the threshold are suppressed, never
smoothed over.

    python -m execution.compute_regional
"""
from __future__ import annotations

import json
import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from execution.compute_index import basket_cost, concept_items, effective_prices
from execution.compute_time_price import hours_to_basket, wage_at


@dataclass
class ConceptMonth:
    price: float | None        # in the item's norm unit
    how: str | None            # published | imputed_us | imputed_basket | carried | None (unpriced)


def us_series(sid: str, reg: dict) -> str:
    return sid.replace(f"APU{reg['area']['code']}", f"APU{reg['imputation']['area']}", 1)


def series_needed(reg: dict) -> list[str]:
    south = [c["series"] for c in reg["concepts"].values()]
    return south + [us_series(s, reg) for s in south] + list(reg["comparison_series"])


def month_add(m: date, n: int) -> date:
    y, mo = divmod(m.year * 12 + m.month - 1 + n, 12)
    return date(y, mo + 1, 1)


def months_between(start: date, end: date) -> list[date]:
    out, m = [], start
    while m <= end:
        out.append(m)
        m = month_add(m, 1)
    return out


def basket_relatives(south_series: list[dict[date, float]], months: list[date]) -> dict[date, float | None]:
    """Geometric mean month-over-month relative of concepts published in the South both months."""
    out = {}
    for m in months:
        prev = month_add(m, -1)
        logs = [math.log(s[m] / s[prev]) for s in south_series if m in s and prev in s and s[prev] > 0]
        out[m] = math.exp(sum(logs) / len(logs)) if logs else None
    return out


def price_concept(south: dict[date, float], us: dict[date, float], basket_rel: dict[date, float | None],
                  months: list[date], max_impute: int, max_carry: int) -> dict[date, ConceptMonth]:
    """One concept's monthly price in BLS units, filled only from the past, never interpolated.

    Gap hierarchy (as ADR 0002: own cell first, then the all-strata relative):
    the item's U.S. city average relative, then the South basket relative, then
    carry the last price (only when BLS published nothing at all that month).
    """
    out, last, run, carry = {}, None, 0, 0
    for m in months:
        prev = month_add(m, -1)
        can = last is not None and run < max_impute
        if m in south:
            last, run, carry, how = south[m], 0, 0, "published"
        elif can and m in us and prev in us:
            last, run, carry, how = last * us[m] / us[prev], run + 1, 0, "imputed_us"
        elif can and basket_rel.get(m):
            last, run, carry, how = last * basket_rel[m], run + 1, 0, "imputed_basket"
        elif can and carry < max_carry:
            run, carry, how = run + 1, carry + 1, "carried"
        else:
            last, how = None, None
        out[m] = ConceptMonth(last, how)
    return out


def price_basket(values: dict[str, dict[date, float]], reg: dict, months: list[date]) -> dict[str, dict[date, ConceptMonth]]:
    """concept -> month -> price in the concept's norm unit."""
    imp = reg["imputation"]
    rel = basket_relatives([values.get(c["series"], {}) for c in reg["concepts"].values()], months)
    out = {}
    for concept, spec in reg["concepts"].items():
        raw = price_concept(values.get(spec["series"], {}), values.get(us_series(spec["series"], reg), {}), rel,
                            months, imp["max_impute_months"], imp["max_carry_months"])
        k = spec["norm_per_bls_unit"]
        out[concept] = {m: ConceptMonth(None if c.price is None else c.price / k, c.how) for m, c in raw.items()}
    return out


def basket_months(priced: dict[str, dict[date, ConceptMonth]], quantities: dict[str, float],
                  months: list[date], threshold: float) -> list[dict]:
    rows = []
    for m in months:
        total = imputed = 0.0
        n_imputed = missing = 0
        for concept, by_month in priced.items():
            c = by_month[m]
            if c.price is None:
                missing += 1
                continue
            v = quantities[concept] * c.price
            total += v
            if c.how != "published":
                imputed += v
                n_imputed += 1
        share = imputed / total if total else None
        if missing:
            status, cost = "no_data", None
        else:
            status, cost = ("suppressed" if share > threshold else "published"), round(total, 2)
        rows.append({"month": m, "cost": cost, "n_concepts": len(priced), "n_imputed": n_imputed,
                     "imputed_share": None if share is None else round(share, 4), "status": status})
    return rows


def time_prices(basket: list[dict], wages: list[tuple[date, float]]) -> list[dict]:
    """Monthly hours to basket for one geo. The wage is read at mid-month."""
    out, first = [], min((q for q, _ in wages), default=None)
    for b in basket:
        # wage_at holds the first quarter backwards; before any published quarter there is no wage.
        wage, projected = (wage_at(b["month"] + timedelta(days=14), wages) if first and b["month"] >= first
                           else (None, False))
        hours = hours_to_basket(b["cost"], wage)
        out.append({"month": b["month"], "basket_cost": b["cost"],
                    "avg_weekly_wage": round(wage, 2) if wage else None,
                    "wage_is_projected": projected if wage else None, "hours_to_basket": hours,
                    "status": b["status"] if wage else "no_data"})
    return out


def overlap(obs, items: list[dict], reg: dict, quantities: dict[str, float],
            basket: list[dict]) -> list[dict]:
    """Weeks we measured: SC shelf cost of the same concepts next to the regional cost.

    The measured side is every collected SC store (Kroger family only in Phase 0),
    standard tier; BLS averages every brand and outlet in the South.
    """
    if obs.empty:
        return []
    subset = {c: quantities[c] for c in reg["concepts"]}
    std = concept_items(items, "standard")
    shelf = effective_prices(obs, "shelf")
    by_month = {b["month"]: b for b in basket if b["status"] == "published"}
    out = []
    for week in sorted(set(shelf.week)):
        wk = shelf[shelf.week == week]
        prices = {(r.store_id, r.item_id): r.unit_price for r in wk.itertuples()}
        cost, missing = basket_cost(prices, subset, std)
        month = date(week.year, week.month, 1)
        ref = next((by_month[m] for m in sorted(by_month, reverse=True) if m <= month), None)
        out.append({"week": week.isoformat(), "measured_cost": cost, "n_missing": missing,
                    "n_stores": int(wk.store_id.nunique()),
                    "regional_month": ref["month"].isoformat() if ref else None,
                    "regional_month_lag": (month.year - ref["month"].year) * 12 + month.month - ref["month"].month if ref else None,
                    "regional_cost": ref["cost"] if ref else None,
                    "measured_over_regional": round(cost / ref["cost"], 4) if cost and ref else None})
    return out


# --- DB wrappers -------------------------------------------------------------

def load_values(db, series_ids: list[str]) -> dict[str, dict[date, float]]:
    marks = ",".join("?" for _ in series_ids)
    out: dict[str, dict[date, float]] = defaultdict(dict)
    for r in db.query(f"SELECT series_id, period, value FROM reference_values WHERE series_id IN ({marks})",
                      tuple(series_ids)):
        out[r["series_id"]][date.fromisoformat(str(r["period"])[:10])] = float(r["value"])
    return out


def load_wages(db) -> dict[str, list[tuple[date, float]]]:
    wages: dict[str, list[tuple[date, float]]] = defaultdict(list)
    for r in db.query("SELECT geo_id, quarter, avg_weekly_wage FROM wages WHERE avg_weekly_wage IS NOT NULL"):
        wages[r["geo_id"]].append((date.fromisoformat(str(r["quarter"])[:10]), float(r["avg_weekly_wage"])))
    return wages


def compute(db, reg: dict, basket_doc: dict) -> tuple[list[date], dict, list[dict]]:
    """Months, per-concept prices, and basket rows, from what's stored. Pure apart from the reads."""
    values = load_values(db, series_needed(reg))
    south = [values.get(c["series"], {}) for c in reg["concepts"].values()]
    last = max((max(s) for s in south if s), default=None)
    if last is None:
        return [], {}, []
    start = date.fromisoformat(reg["start_month"] + "-01")
    months = months_between(start, last)
    priced = price_basket(values, reg, months)
    rows = basket_months(priced, basket_doc["weekly_quantity"], months, reg["suppress_imputed_share_above"])
    return months, priced, rows


def run(db, reg: dict, basket_doc: dict, geo_rows: list[dict]) -> dict:
    method = reg["method_version"]
    computed_at = datetime.now(timezone.utc).isoformat()
    months, _, basket = compute(db, reg, basket_doc)
    for b in basket:
        db.upsert("regional_basket_costs", {**b, "month": b["month"].isoformat(), "method_version": method,
                                            "computed_at": computed_at}, ["month", "method_version"])
    wages = load_wages(db)
    n = 0
    for g in geo_rows:
        for t in time_prices(basket, wages.get(g["geo_id"], [])):
            db.upsert("regional_time_prices", {**t, "geo_id": g["geo_id"], "month": t["month"].isoformat(),
                                               "method_version": method, "computed_at": computed_at},
                      ["geo_id", "month", "method_version"])
            n += 1
    db.commit()
    statuses: dict[str, int] = defaultdict(int)
    for b in basket:
        statuses[b["status"]] += 1
    return {"months": len(months), "first": months[0].isoformat() if months else None,
            "last": months[-1].isoformat() if months else None, "basket_status": dict(statuses),
            "time_prices": n}


if __name__ == "__main__":
    from execution import config
    from execution.db import DB

    db = DB()
    db.migrate()
    cfg = config.collection()
    print(json.dumps(run(db, config.regional(), config.basket(cfg), config.geo()), indent=1))
