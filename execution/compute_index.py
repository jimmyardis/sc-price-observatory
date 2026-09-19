"""Matched-model price index, mirroring the BLS CPI structure with local data.

Lower level (within stratum, within geo): Jevons geometric mean of price
relatives over (store, item) pairs observed in BOTH this and the previous
collection week for the geo. Items appearing or disappearing never register
as price change.

Upper level: weight stratum relatives by CPI relative importance (renormalized
over strata with a relative this week), chain forward.

Imputation: an in-sample pair missing this week gets its stratum's relative
(or the all-strata relative) applied to its last price, is flagged, and counts
toward imputed_share. A pair is dropped after `drop_after` consecutive missing
weeks. Cells with imputed_share above the threshold are suppressed at export.

Base: mean of the first full calendar month of collection = 100. Until that
month exists, the first collection week = 100 and base_status='provisional'.

Usage: python -m execution.compute_index
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

import pandas as pd

SERIES = ("shelf", "promo_incl")


# --- pure core -------------------------------------------------------------

def effective_prices(obs: pd.DataFrame, series: str) -> pd.DataFrame:
    """One unit price per (week, store, item).

    Re-collection appends rows; the latest collected row per price_type wins.
    shelf: shelf prices only (headline). promo_incl: lowest of any price type
    (what a shopper chasing sales paid).
    """
    cols = ["week", "store_id", "item_id", "unit_price"]
    if obs.empty:
        return pd.DataFrame(columns=cols)
    df = obs.sort_values(["collected_at", "obs_id"])
    latest = df.drop_duplicates(["week", "store_id", "item_id", "price_type"], keep="last")
    if series == "shelf":
        out = latest[latest.price_type == "shelf"]
    elif series == "promo_incl":
        out = latest.groupby(["week", "store_id", "item_id"], as_index=False)["unit_price"].min()
    else:
        raise ValueError(series)
    return out[cols].reset_index(drop=True)


@dataclass
class WeekResult:
    week: date
    chain: float                       # un-rebased headline chain
    stratum_chain: dict[str, float]
    n_obs: int
    n_stores: int
    imputed_share: float
    stratum_imputed_share: dict[str, float]
    stratum_n_obs: dict[str, int]
    prices: dict[tuple[str, str], float] = field(repr=False)   # observed + imputed unit prices
    stores_observed: set[str] = field(default_factory=set, repr=False)


def compute_geo(prices: pd.DataFrame, item_stratum: dict[str, str], weights: dict[str, float],
                drop_after: int = 4) -> list[WeekResult]:
    """Chain the index for one geo. `prices` = effective_prices rows for the geo's stores."""
    results: list[WeekResult] = []
    if prices.empty:
        return results
    by_week = {w: g for w, g in prices.groupby("week")}
    chain = 100.0
    s_chain: dict[str, float] = {}
    prev_observed: dict[tuple[str, str], float] = {}
    est: dict[tuple[str, str], float] = {}       # in-sample pairs -> last known/imputed price
    streak: dict[tuple[str, str], int] = {}

    for week in sorted(by_week):
        g = by_week[week]
        cur = {(r.store_id, r.item_id): float(r.unit_price) for r in g.itertuples()}

        logs: dict[str, list[float]] = defaultdict(list)
        for key, p in cur.items():
            if key in prev_observed and p > 0 and prev_observed[key] > 0:
                logs[item_stratum[key[1]]].append(math.log(p / prev_observed[key]))
        rel = {s: math.exp(sum(v) / len(v)) for s, v in logs.items()}

        wsum = sum(weights.get(s, 0.0) for s in rel)
        rel_all = sum(weights.get(s, 0.0) * r for s, r in rel.items()) / wsum if wsum > 0 else None

        # imputation for in-sample pairs missing this week
        imputed_by_stratum: dict[str, int] = defaultdict(int)
        for key in list(est):
            if key in cur:
                continue
            streak[key] = streak.get(key, 0) + 1
            if streak[key] > drop_after:
                del est[key], streak[key]
                continue
            stratum = item_stratum[key[1]]
            r = rel.get(stratum, rel_all)
            if r is not None:
                est[key] *= r
            imputed_by_stratum[stratum] += 1
        for key, p in cur.items():
            est[key] = p
            streak[key] = 0

        observed_by_stratum: dict[str, int] = defaultdict(int)
        for key in cur:
            observed_by_stratum[item_stratum[key[1]]] += 1

        if rel_all is not None:
            chain *= rel_all
        for s in set(observed_by_stratum) | set(imputed_by_stratum):
            base = s_chain.get(s, 100.0)
            r = rel.get(s, rel_all)
            s_chain[s] = base * r if (r is not None and s in s_chain) else base

        n_imp = sum(imputed_by_stratum.values())
        results.append(WeekResult(
            week=week,
            chain=chain,
            stratum_chain=dict(s_chain),
            n_obs=len(cur),
            n_stores=len({k[0] for k in cur}),
            imputed_share=n_imp / (len(cur) + n_imp) if (cur or n_imp) else 1.0,
            stratum_imputed_share={
                s: imputed_by_stratum[s] / (observed_by_stratum[s] + imputed_by_stratum[s])
                for s in set(observed_by_stratum) | set(imputed_by_stratum)},
            stratum_n_obs=dict(observed_by_stratum),
            prices=dict(est),
            stores_observed={k[0] for k in cur},
        ))
        prev_observed = cur
    return results


def base_month(all_weeks: list[date]) -> tuple[int, int] | None:
    """First calendar month whose every Monday-week lies within collection."""
    if not all_weeks:
        return None
    first, last = min(all_weeks), max(all_weeks)
    y, m = first.year, first.month
    while True:
        mondays = _mondays(y, m)
        if mondays[-1] > last:
            return None
        if mondays[0] >= first:
            return (y, m)
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def _mondays(y: int, m: int) -> list[date]:
    d = date(y, m, 1)
    d += timedelta(days=(7 - d.weekday()) % 7)
    out = []
    while d.month == m:
        out.append(d)
        d += timedelta(days=7)
    return out


def rebase(values: dict[date, float], month: tuple[int, int] | None) -> tuple[dict[date, float], str]:
    if not values:
        return {}, "provisional"
    if month:
        in_month = [v for w, v in values.items() if (w.year, w.month) == month]
        if in_month:
            base = sum(in_month) / len(in_month)
            return {w: v / base * 100 for w, v in values.items()}, "final"
    first = values[min(values)]
    return {w: v / first * 100 for w, v in values.items()}, "provisional"


def basket_cost(prices: dict[tuple[str, str], float], quantities: dict[str, float],
                concept_item: dict[str, str]) -> tuple[float | None, int]:
    """Weekly basket dollars: sum(qty x mean unit price across the geo's stores)."""
    by_item: dict[str, list[float]] = defaultdict(list)
    for (_, item), p in prices.items():
        by_item[item].append(p)
    total, missing = 0.0, 0
    for concept, qty in quantities.items():
        ps = by_item.get(concept_item[concept])
        if not ps:
            missing += 1
            continue
        total += qty * sum(ps) / len(ps)
    return (None if missing else round(total, 2)), missing


def concept_items(items: list[dict], basket: str) -> dict[str, str]:
    """concept -> item_id for the standard (store/unbranded) or national basket."""
    out: dict[str, dict[str, str]] = defaultdict(dict)
    for it in items:
        if it["active"]:
            out[it["concept"]][it["tier"]] = it["item_id"]
    pick = {}
    for concept, tiers in out.items():
        order = (["national_brand", "store_brand", "unbranded"] if basket == "national"
                 else ["store_brand", "unbranded", "national_brand"])
        pick[concept] = next(tiers[t] for t in order if t in tiers)
    return pick


# --- DB wrapper ------------------------------------------------------------

def geo_members(geo_rows: list[dict], stores: list[dict]) -> dict[str, set[str]]:
    parent = {g["geo_id"]: g["parent_geo_id"] for g in geo_rows}
    members: dict[str, set[str]] = defaultdict(set)
    for s in stores:
        g = s["geo_id"]
        while g:
            members[g].add(s["store_id"])
            g = parent.get(g)
    return members


def load_observations(db) -> pd.DataFrame:
    rows = db.query("SELECT obs_id, collected_at, week, store_id, item_id, unit_price, price_type FROM observations")
    df = pd.DataFrame(rows, columns=["obs_id", "collected_at", "week", "store_id", "item_id", "unit_price", "price_type"])
    if not df.empty:
        df["week"] = pd.to_datetime(df["week"]).dt.date
        df["collected_at"] = df["collected_at"].astype(str)
        df["unit_price"] = df["unit_price"].astype(float)
    return df


def run(db, cfg: dict, items: list[dict], weights_doc: dict, basket_doc: dict, geo_rows: list[dict]) -> dict:
    method = cfg["method_version"]
    computed_at = datetime.now(timezone.utc).isoformat()
    obs = load_observations(db)
    stores = db.query("SELECT store_id, banner, geo_id FROM stores")
    banner_of = {s["store_id"]: s["banner"] for s in stores}
    members = geo_members(geo_rows, stores)
    item_stratum = {i["item_id"]: i["cpi_stratum"] for i in items}
    w = {s: v["relative_importance"] for s, v in weights_doc["strata"].items()}
    qty = basket_doc["weekly_quantity"]
    month = base_month(sorted(set(obs["week"]))) if not obs.empty else None

    n_rows = 0
    for series in SERIES:
        prices = effective_prices(obs, series)
        prices = prices[prices.item_id.isin(item_stratum)]
        for geo_id, store_ids in members.items():
            res = compute_geo(prices[prices.store_id.isin(store_ids)], item_stratum, w, cfg["drop_after_missing_weeks"])
            if not res:
                continue
            headline, status = rebase({r.week: r.chain for r in res}, month)
            strata = sorted({s for r in res for s in r.stratum_chain})
            s_rebased = {s: rebase({r.week: r.stratum_chain[s] for r in res if s in r.stratum_chain}, month)[0]
                         for s in strata}
            for r in res:
                costs = {b: basket_cost(r.prices, qty, concept_items(items, b)) for b in ("standard", "national")}
                db.upsert("index_values", {
                    "geo_id": geo_id, "week": r.week.isoformat(), "stratum": "ALL", "series": series,
                    "index_value": round(headline[r.week], 4), "basket_cost": costs["standard"][0],
                    "n_obs": r.n_obs, "n_stores": r.n_stores,
                    "n_banners": len({banner_of[s] for s in r.stores_observed}),
                    "imputed_share": round(r.imputed_share, 4), "base_status": status,
                    "method_version": method, "computed_at": computed_at,
                }, ["geo_id", "week", "stratum", "series", "method_version"])
                for s in r.stratum_chain:
                    db.upsert("index_values", {
                        "geo_id": geo_id, "week": r.week.isoformat(), "stratum": s, "series": series,
                        "index_value": round(s_rebased[s][r.week], 4), "basket_cost": None,
                        "n_obs": r.stratum_n_obs.get(s, 0), "n_stores": None, "n_banners": None,
                        "imputed_share": round(r.stratum_imputed_share.get(s, 0.0), 4), "base_status": status,
                        "method_version": method, "computed_at": computed_at,
                    }, ["geo_id", "week", "stratum", "series", "method_version"])
                for b, (cost, missing) in costs.items():
                    db.upsert("basket_costs", {
                        "geo_id": geo_id, "week": r.week.isoformat(), "series": series, "basket": b,
                        "cost": cost, "n_concepts": len(qty), "n_missing": missing,
                        "method_version": method, "computed_at": computed_at,
                    }, ["geo_id", "week", "series", "basket", "method_version"])
                n_rows += 1
    db.commit()
    return {"geo_weeks": n_rows, "base_month": month}


if __name__ == "__main__":
    from execution import config
    from execution.db import DB

    db = DB()
    cfg = config.collection()
    print(run(db, cfg, config.items(), config.weights(cfg), config.basket(cfg), config.geo()))
