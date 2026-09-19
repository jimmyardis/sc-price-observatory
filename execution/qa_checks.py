"""QA gates. Run before every publish; any failure halts the pipeline.

Gates (spec §9, plus three the spec implies):
  unit_price_outlier      unit price outside 5x / 0.2x its trailing 8-week median (item-store)
  imputed_share           a published cell with imputed_share above the threshold
  banner_store_drop       a banner's observed store count fell >20% week over week
  stratum_relative        a published stratum moved outside ±10% week over week
  unknown_price_type      price_type='unknown' is >10% of the week's rows
  week_has_observations   the week has any observations at all
  config_verified         weights verified and basket status final (a human signs off)
  no_silent_revision      an already-published value changed under the same method_version
                          (hours on a projected wage were published as provisional and may move)

Regional reconstruction gates (run_regional):
  concepts_accounted      every standard-basket concept is priced or excluded with a reason, never both
  config_verified         basket final (the reconstruction uses the same quantities)
  wages_cover_history     no geo is missing a wage for a month other geos have (months before any
                          published QCEW quarter are uniformly no_data and fill in later)
  no_silent_revision      as above, for published regional snapshots

Human-confirmed exceptions live in config/qa_overrides.json ({gate, key}).
Report: .tmp/qa_report_{week}.json, .tmp/qa_report_regional_{month}.json
"""
from __future__ import annotations

import json
import statistics
from collections import defaultdict
from datetime import date, timedelta

import pandas as pd

from execution.compute_index import effective_prices
from execution.config import TMP


def _gate(name: str, failures: list, overrides: set[tuple[str, str]], info: str = "") -> dict:
    open_failures = [f for f in failures if (name, f.get("key", "")) not in overrides]
    return {"gate": name, "passed": not open_failures, "failures": open_failures,
            "overridden": len(failures) - len(open_failures), "info": info}


def unit_price_outliers(obs: pd.DataFrame, week: date, lo: float = 0.2, hi: float = 5.0) -> list[dict]:
    shelf = effective_prices(obs[obs.week < week], "shelf")
    window = shelf[shelf.week >= week - timedelta(weeks=8)]
    hist = window.groupby(["store_id", "item_id"])["unit_price"].apply(list).to_dict()
    out = []
    for r in obs[obs.week == week].itertuples():
        prior = hist.get((r.store_id, r.item_id), [])
        if len(prior) < 3:
            continue
        med = statistics.median(prior)
        ratio = r.unit_price / med
        if ratio > hi or ratio < lo:
            out.append({"key": f"{r.store_id}|{r.item_id}|{week}", "obs_id": int(r.obs_id),
                        "unit_price": r.unit_price, "trailing_median": med, "ratio": round(ratio, 3),
                        "price_type": r.price_type})
    return out


def banner_store_drops(obs: pd.DataFrame, banner_of: dict[str, str], week: date, max_drop: float = 0.2) -> list[dict]:
    def counts(w):
        stores = set(obs[obs.week == w].store_id)
        c: dict[str, int] = defaultdict(int)
        for s in stores:
            c[banner_of.get(s, "?")] += 1
        return c
    now, before = counts(week), counts(week - timedelta(weeks=1))
    return [{"key": f"{b}|{week}", "banner": b, "stores_prev": n, "stores_now": now.get(b, 0)}
            for b, n in before.items() if n and (n - now.get(b, 0)) / n > max_drop]


def run(db, cfg: dict, week: date, snapshot: dict, weights_doc: dict, basket_doc: dict,
        previous_snapshots: list[dict], overrides: list[dict], obs: pd.DataFrame) -> dict:
    ov = {(o["gate"], o["key"]) for o in overrides}
    method = cfg["method_version"]
    threshold = cfg["suppress_imputed_share_above"]
    stores = db.query("SELECT store_id, banner FROM stores")
    banner_of = {s["store_id"]: s["banner"] for s in stores}
    wk = obs[obs.week == week] if not obs.empty else obs
    published = [g for g in snapshot["geos"] if g["status"] == "published"]

    gates = []
    gates.append(_gate("week_has_observations",
                       [] if len(wk) else [{"key": str(week), "detail": "no observations for week"}], ov))
    gates.append(_gate("unit_price_outlier", unit_price_outliers(obs, week) if len(wk) else [], ov))
    gates.append(_gate("imputed_share", [
        {"key": f"{g['geo_id']}|{week}", "imputed_share": g["coverage"]["imputed_share"]}
        for g in published if (g["coverage"]["imputed_share"] or 0) > threshold], ov))
    gates.append(_gate("banner_store_drop", banner_store_drops(obs, banner_of, week) if len(wk) else [], ov))

    strat_fail = []
    pub_ids = [g["geo_id"] for g in published]
    if pub_ids:
        prev = (week - timedelta(weeks=1)).isoformat()
        marks = ",".join("?" for _ in pub_ids)
        rows = db.query(
            f"SELECT geo_id, week, stratum, index_value FROM index_values WHERE series = 'shelf' "
            f"AND stratum != 'ALL' AND method_version = ? AND week IN (?, ?) AND geo_id IN ({marks})",
            (method, prev, week.isoformat(), *pub_ids))
        vals = {(r["geo_id"], str(r["week"]), r["stratum"]): float(r["index_value"]) for r in rows}
        for (g, w, s), v in vals.items():
            if w != week.isoformat() or (g, prev, s) not in vals:
                continue
            rel = v / vals[(g, prev, s)]
            if abs(rel - 1) > 0.10:
                strat_fail.append({"key": f"{g}|{s}|{week}", "relative": round(rel, 4)})
    gates.append(_gate("stratum_relative", strat_fail, ov))

    unknown = int((wk.price_type == "unknown").sum()) if len(wk) else 0
    gates.append(_gate("unknown_price_type",
                       [{"key": str(week), "unknown_share": unknown / len(wk)}] if len(wk) and unknown / len(wk) > 0.10 else [],
                       ov))

    cfg_fail = []
    if not weights_doc.get("verified"):
        cfg_fail.append({"key": "weights", "detail": f"{weights_doc.get('weights_version')} is not verified against BLS"})
    if basket_doc.get("status") != "final":
        cfg_fail.append({"key": "basket", "detail": f"{basket_doc.get('basket_version')} is {basket_doc.get('status')}, not final"})
    gates.append(_gate("config_verified", cfg_fail, ov))

    revisions = []
    new_hist = {(g, h["week"]): h for g, hs in snapshot["history"].items() for h in hs}
    for old in previous_snapshots:
        if old.get("method_version") != method:
            continue
        for g, hs in old["history"].items():
            for h in hs:
                n = new_hist.get((g, h["week"]))
                for field in ("basket_cost", "hours_to_basket", "index_value"):
                    if field == "hours_to_basket" and h.get("wage_is_projected"):
                        continue  # published as provisional: the next QCEW quarter moves it
                    if n is not None and h.get(field) is not None and n.get(field) != h.get(field):
                        revisions.append({"key": f"{g}|{h['week']}|{field}", "published": h.get(field),
                                          "recomputed": n.get(field), "in_snapshot": old["week"]})
    gates.append(_gate("no_silent_revision", revisions, ov,
                       info="changing a published number requires a new method_version"))

    report = {"week": week.isoformat(), "method_version": method,
              "passed": all(g["passed"] for g in gates), "gates": gates}
    TMP.mkdir(parents=True, exist_ok=True)
    (TMP / f"qa_report_{week.isoformat()}.json").write_text(json.dumps(report, indent=1, default=str))
    return report


def run_regional(reg: dict, basket_doc: dict, snapshot: dict, previous_snapshots: list[dict],
                 overrides: list[dict]) -> dict:
    ov = {(o["gate"], o["key"]) for o in overrides}
    gates = []

    basket_concepts = set(basket_doc["weekly_quantity"])
    priced, excluded = set(reg["concepts"]), set(reg["excluded"])
    acct = ([{"key": c, "detail": "neither priced nor excluded"} for c in sorted(basket_concepts - priced - excluded)]
            + [{"key": c, "detail": "both priced and excluded"} for c in sorted(priced & excluded)]
            + [{"key": c, "detail": "priced but not in the standard basket"} for c in sorted(priced - basket_concepts)])
    gates.append(_gate("concepts_accounted", acct, ov))

    cfg_fail = []
    if basket_doc.get("status") != "final":
        cfg_fail.append({"key": "basket", "detail": f"{basket_doc.get('basket_version')} is {basket_doc.get('status')}, not final"})
    gates.append(_gate("config_verified", cfg_fail, ov))

    # A month before any QCEW quarter we hold has no wage for anyone: it is uniformly no_data and
    # fills in later without moving a published value. A month where only SOME geos have a wage is
    # a hole, and that is what this gate catches.
    publishable = {b["month"] for b in snapshot["basket"] if b["status"] == "published"}
    have_any = {s["month"] for g in snapshot["geos"] for s in g["series"] if s["avg_weekly_wage"] is not None}
    holes = []
    for g in snapshot["geos"]:
        missing = sorted(s["month"] for s in g["series"]
                         if s["month"] in publishable and s["month"] in have_any and s["avg_weekly_wage"] is None)
        if missing:
            holes.append({"key": g["geo_id"], "n_months": len(missing), "first": missing[0], "last": missing[-1]})
    gates.append(_gate("wages_cover_history", holes, ov,
                       info="a geo is missing a wage for a month other geos have; pre-2014 quarters come from "
                            "`python -m execution.fetch_bls wage-history`"))

    revisions = []
    now_cost = {b["month"]: b["cost"] for b in snapshot["basket"]}
    now_hours = {(g["geo_id"], s["month"]): s["hours_to_basket"] for g in snapshot["geos"] for s in g["series"]}
    for old in previous_snapshots:
        if old.get("method_version") != reg["method_version"]:
            continue
        for b in old["basket"]:
            if b["cost"] is not None and now_cost.get(b["month"]) != b["cost"]:
                revisions.append({"key": f"basket|{b['month']}", "published": b["cost"],
                                  "recomputed": now_cost.get(b["month"]), "in_snapshot": old["latest_month"]})
        for g in old["geos"]:
            for s in g["series"]:
                n = now_hours.get((g["geo_id"], s["month"]))
                if s["hours_to_basket"] is not None and not s["wage_is_projected"] and n != s["hours_to_basket"]:
                    revisions.append({"key": f"{g['geo_id']}|{s['month']}", "published": s["hours_to_basket"],
                                      "recomputed": n, "in_snapshot": old["latest_month"]})
    gates.append(_gate("no_silent_revision", revisions, ov,
                       info="changing a published number requires a new regional method_version"))

    report = {"kind": "regional_reconstruction", "latest_month": snapshot["latest_month"],
              "method_version": reg["method_version"],
              "passed": all(g["passed"] for g in gates), "gates": gates}
    TMP.mkdir(parents=True, exist_ok=True)
    (TMP / f"qa_report_regional_{snapshot['latest_month']}.json").write_text(json.dumps(report, indent=1, default=str))
    return report
