"""Build the public snapshot JSON for a week, gate it through QA, and publish.

The site reads snapshots only; it never touches the database.

    python -m execution.export_snapshot --week 2026-09-14          # publish (QA must pass)
    python -m execution.export_snapshot --week 2026-09-14 --draft  # write to .tmp/snapshots/, never public

Published files are immutable: snapshots/<method_version>/<week>.json (a
re-publish of the same week becomes <week>.r2.json), plus snapshots/latest.json
and snapshots/manifest.json listing every file with its sha256.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from execution import qa_checks
from execution.compute_index import concept_items, effective_prices, load_observations
from execution.config import ROOT, TMP

SNAPSHOTS = ROOT / "snapshots"
SCHEMA = "sc-price-observatory/snapshot@1"


def _f(v):
    return None if v is None else float(v)


def _pct(now, before):
    return None if now is None or not before else round((now / before - 1) * 100, 2)


def build(db, cfg: dict, week: date, items: list[dict], weights_doc: dict, basket_doc: dict,
          geo_rows: list[dict], obs=None) -> dict:
    method = cfg["method_version"]
    threshold = cfg["suppress_imputed_share_above"]
    rule = cfg["coverage_rule"]
    obs = load_observations(db) if obs is None else obs

    iv = db.query("SELECT * FROM index_values WHERE stratum = 'ALL' AND method_version = ? AND week <= ?",
                  (method, week.isoformat()))
    bc = db.query("SELECT * FROM basket_costs WHERE method_version = ? AND week <= ?", (method, week.isoformat()))
    tp = db.query("SELECT * FROM time_prices WHERE series = 'shelf' AND method_version = ? AND week <= ?",
                  (method, week.isoformat()))
    idx = {(r["geo_id"], str(r["week"]), r["series"]): r for r in iv}
    cost = {(r["geo_id"], str(r["week"]), r["series"], r["basket"]): _f(r["cost"]) for r in bc}
    tprice = {(r["geo_id"], str(r["week"])): r for r in tp}
    stores = db.query("SELECT store_id, banner, geo_id FROM stores")
    banner_of = {s["store_id"]: s["banner"] for s in stores}
    parent = {g["geo_id"]: g["parent_geo_id"] for g in geo_rows}

    def members(geo_id):
        out = set()
        for s in stores:
            g = s["geo_id"]
            while g:
                if g == geo_id:
                    out.add(s["store_id"])
                    break
                g = parent.get(g)
        return out

    shelf_now = effective_prices(obs[obs.week == week], "shelf") if not obs.empty else None
    item_by_id = {i["item_id"]: i for i in items}
    std, nat = concept_items(items, "standard"), concept_items(items, "national")
    paired = {c: (std[c], nat[c]) for c in std if std[c] != nat[c]}

    def status_of(geo, r):
        if r is None:
            return "no_data", ["no observations this week"]
        reasons = []
        if float(r["imputed_share"]) > threshold:
            return "suppressed", [f"imputed_share {float(r['imputed_share']):.2f} > {threshold}"]
        if geo["geo_type"] == "county" and (r["n_stores"] < rule["min_stores"] or r["n_banners"] < rule["min_banners"]):
            return "thin_coverage", [f"{r['n_stores']} stores / {r['n_banners']} banners; rule is "
                                     f"{rule['min_stores']}+ stores across {rule['min_banners']}+ banners"]
        return "published", reasons

    w = week.isoformat()
    wow_w = (week - timedelta(weeks=1)).isoformat()
    yoy_w = (week - timedelta(weeks=52)).isoformat()
    geos_out, history = [], {}
    for geo in geo_rows:
        gid = geo["geo_id"]
        r = idx.get((gid, w, "shelf"))
        status, reasons = status_of(geo, r)
        entry = {"geo_id": gid, "geo_type": geo["geo_type"], "name": geo["name"],
                 "parent_geo_id": geo["parent_geo_id"], "status": status, "reasons": reasons,
                 "rolled_up_to": None, "levels": None, "index": None, "tier_gap": None,
                 "coverage": {"n_stores": r["n_stores"] if r else 0, "n_banners": r["n_banners"] if r else 0,
                              "n_obs": r["n_obs"] if r else 0,
                              "imputed_share": _f(r["imputed_share"]) if r else None,
                              "coverage_ok": bool(r) and r["n_stores"] >= rule["min_stores"] and r["n_banners"] >= rule["min_banners"],
                              "stores_by_banner": {}}}
        if shelf_now is not None and r:
            here = shelf_now[shelf_now.store_id.isin(members(gid))]
            sb: dict[str, int] = defaultdict(int)
            for s in set(here.store_id):
                sb[banner_of[s]] += 1
            entry["coverage"]["stores_by_banner"] = dict(sb)
            logs = []
            for c, (si, ni) in paired.items():
                ps, pn = here[here.item_id == si].unit_price, here[here.item_id == ni].unit_price
                if len(ps) and len(pn):
                    logs.append(math.log(pn.mean() / ps.mean()))
            if logs:
                entry["tier_gap"] = {"national_over_store": round(math.exp(sum(logs) / len(logs)), 4),
                                     "n_concepts": len(logs), "of_paired_concepts": len(paired)}
        if status == "thin_coverage":
            up = parent.get(gid)
            entry["rolled_up_to"] = up
        if status == "published":
            t = tprice.get((gid, w)) or {}
            tw, ty = tprice.get((gid, wow_w)) or {}, tprice.get((gid, yoy_w)) or {}
            hours, bcost = _f(t.get("hours_to_basket")), cost.get((gid, w, "shelf", "standard"))
            entry["levels"] = {
                "basket_cost": bcost,
                "basket_cost_national": cost.get((gid, w, "shelf", "national")),
                "basket_cost_promo_incl": cost.get((gid, w, "promo_incl", "standard")),
                "avg_weekly_wage": _f(t.get("avg_weekly_wage")),
                "wage_is_projected": bool(t.get("wage_is_projected")) if t else None,
                "hours_to_basket": hours,
                "change": {
                    "wow": {"basket_cost_pct": _pct(bcost, cost.get((gid, wow_w, "shelf", "standard"))),
                            "hours_pct": _pct(hours, _f(tw.get("hours_to_basket")))},
                    "yoy": {"basket_cost_pct": _pct(bcost, cost.get((gid, yoy_w, "shelf", "standard"))),
                            "hours_pct": _pct(hours, _f(ty.get("hours_to_basket")))},
                },
            }
            weeks_of_history = sorted(str(k[1]) for k in idx if k[0] == gid and k[2] == "shelf")
            if len(weeks_of_history) >= cfg["index_publish_min_weeks"] and r["base_status"] == "final":
                prev, yago = idx.get((gid, wow_w, "shelf")), idx.get((gid, yoy_w, "shelf"))
                promo = idx.get((gid, w, "promo_incl"))
                entry["index"] = {
                    "value": _f(r["index_value"]), "base_status": r["base_status"],
                    "wow_pct": _pct(_f(r["index_value"]), _f(prev["index_value"]) if prev else None),
                    "yoy_pct": _pct(_f(r["index_value"]), _f(yago["index_value"]) if yago else None),
                    "promo_incl_value": _f(promo["index_value"]) if promo else None,
                }
            history[gid] = [
                {"week": wk, "basket_cost": cost.get((gid, wk, "shelf", "standard")),
                 "hours_to_basket": _f((tprice.get((gid, wk)) or {}).get("hours_to_basket")),
                 "wage_is_projected": bool((tprice.get((gid, wk)) or {}).get("wage_is_projected")),
                 "index_value": _f(idx[(gid, wk, "shelf")]["index_value"]) if entry["index"] else None,
                 "imputed_share": _f(idx[(gid, wk, "shelf")]["imputed_share"])}
                for wk in weeks_of_history
                if float(idx[(gid, wk, "shelf")]["imputed_share"]) <= threshold]
        geos_out.append(entry)

    # counties whose region is also thin roll up to the state
    by_id = {g["geo_id"]: g for g in geos_out}
    for g in geos_out:
        if g["rolled_up_to"] and by_id.get(g["rolled_up_to"], {}).get("status") != "published":
            g["rolled_up_to"] = parent.get(g["rolled_up_to"])

    state = by_id.get("45", {})
    lv = state.get("levels") or {}
    household = basket_doc.get("household", "")
    hh_short = basket_doc.get("household_short") or household
    headline = {
        "geo_id": "45", "status": state.get("status"),
        "hours_to_basket": lv.get("hours_to_basket"), "basket_cost": lv.get("basket_cost"),
        "avg_weekly_wage": lv.get("avg_weekly_wage"), "wage_is_projected": lv.get("wage_is_projected"),
        "change": lv.get("change"),
        "sentence": (f"{lv['hours_to_basket']:.1f} hours of average local work buys a week of groceries for {hh_short}."
                     if lv.get("hours_to_basket") else None),
    }
    strata = weights_doc["strata"]
    basket_items = [{
        "item_id": i["item_id"], "concept": i["concept"], "label": i["label"], "tier": i["tier"],
        "norm_unit": i["norm_unit"], "stratum": i["cpi_stratum"], "stratum_label": strata[i["cpi_stratum"]]["label"],
        "group": strata[i["cpi_stratum"]]["group"], "stratum_relative_importance": strata[i["cpi_stratum"]]["relative_importance"],
        "in_standard_basket": std.get(i["concept"]) == i["item_id"],
        "in_national_basket": nat.get(i["concept"]) == i["item_id"],
        "weekly_quantity": basket_doc["weekly_quantity"].get(i["concept"]),
        "quantity_from": basket_doc.get("provenance", {}).get(i["concept"]),
    } for i in items if i["active"]]
    notes = []
    if not any(g["index"] for g in geos_out):
        notes.append(f"The index series begins once {cfg['index_publish_min_weeks']} weeks of baseline exist. "
                     "Basket cost and time price are meaningful from week one.")
    return {
        "schema": SCHEMA, "week": w, "method_version": method,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "config": {"weights_version": weights_doc.get("weights_version"), "weights_verified": weights_doc.get("verified"),
                   "weights_source": weights_doc.get("source"), "basket_source": basket_doc.get("source"),
                   "basket_rule": basket_doc.get("rule"),
                   "basket_version": basket_doc.get("basket_version"), "basket_status": basket_doc.get("status"),
                   "household": household, "household_short": basket_doc.get("household_short"),
                   "banners_collected": cfg["banners"], "index_publish_min_weeks": cfg["index_publish_min_weeks"],
                   "headline_series": "shelf prices only (promotions excluded)",
                   "suppress_imputed_share_above": cfg["suppress_imputed_share_above"],
                   "coverage_rule": cfg["coverage_rule"]},
        "headline": headline, "geos": geos_out, "history": history, "basket": basket_items, "notes": notes,
    }


def _levels_csv(snap: dict) -> str:
    buf = io.StringIO()
    wr = csv.writer(buf)
    wr.writerow(["week", "geo_id", "name", "geo_type", "status", "basket_cost", "basket_cost_national",
                 "basket_cost_promo_incl", "avg_weekly_wage", "wage_is_projected", "hours_to_basket",
                 "index_value", "n_stores", "n_banners", "imputed_share", "method_version"])
    for g in snap["geos"]:
        lv, ix, cv = g["levels"] or {}, g["index"] or {}, g["coverage"]
        wr.writerow([snap["week"], g["geo_id"], g["name"], g["geo_type"], g["status"], lv.get("basket_cost"),
                     lv.get("basket_cost_national"), lv.get("basket_cost_promo_incl"), lv.get("avg_weekly_wage"),
                     lv.get("wage_is_projected"), lv.get("hours_to_basket"), ix.get("value"),
                     cv["n_stores"], cv["n_banners"], cv["imputed_share"], snap["method_version"]])
    return buf.getvalue()


def previous_snapshots(method: str) -> list[dict]:
    d = SNAPSHOTS / method
    return [json.loads(p.read_text()) for p in sorted(d.glob("*.json"))] if d.exists() else []


def publish(snap: dict) -> list[str]:
    d = SNAPSHOTS / snap["method_version"]
    d.mkdir(parents=True, exist_ok=True)
    stem, n = snap["week"], 1
    while (d / f"{stem}.json").exists():
        n += 1
        stem = f"{snap['week']}.r{n}"
    body = json.dumps(snap, indent=1).encode()
    files = {d / f"{stem}.json": body, d / f"{stem}_levels.csv": _levels_csv(snap).encode()}
    for p, b in files.items():
        p.write_bytes(b)
    (SNAPSHOTS / "latest.json").write_bytes(body)
    manifest_path = SNAPSHOTS / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {"files": []}
    for p, b in files.items():
        manifest["files"].append({"path": str(p.relative_to(SNAPSHOTS)), "sha256": hashlib.sha256(b).hexdigest(),
                                  "week": snap["week"], "method_version": snap["method_version"],
                                  "revision": n, "published_at": snap["generated_at"]})
    manifest_path.write_text(json.dumps(manifest, indent=1))
    return [str(p) for p in files]


def run(db, cfg, week: date, items, weights_doc, basket_doc, geo_rows, overrides, draft: bool) -> dict:
    obs = load_observations(db)
    snap = build(db, cfg, week, items, weights_doc, basket_doc, geo_rows, obs=obs)
    report = qa_checks.run(db, cfg, week, snap, weights_doc, basket_doc,
                           previous_snapshots(cfg["method_version"]), overrides, obs)
    snap["qa"] = {"passed": report["passed"],
                  "failed_gates": [g["gate"] for g in report["gates"] if not g["passed"]]}
    if draft:
        snap["draft"] = True
        out = TMP / "snapshots" / f"draft_{week.isoformat()}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(snap, indent=1))
        return {"published": False, "draft_path": str(out), "qa": snap["qa"], "headline": snap["headline"]}
    if not report["passed"]:
        return {"published": False, "qa": snap["qa"],
                "report": str(TMP / f"qa_report_{week.isoformat()}.json")}
    snap["draft"] = False
    return {"published": True, "files": publish(snap), "qa": snap["qa"], "headline": snap["headline"]}


def latest_week(db, method: str) -> date | None:
    r = db.query("SELECT MAX(week) AS w FROM index_values WHERE method_version = ?", (method,))
    return date.fromisoformat(str(r[0]["w"])) if r and r[0]["w"] else None


if __name__ == "__main__":
    import sys

    from execution import config
    from execution.db import DB

    ap = argparse.ArgumentParser()
    ap.add_argument("--week", help="Monday, YYYY-MM-DD (default: latest computed)")
    ap.add_argument("--draft", action="store_true")
    args = ap.parse_args()
    db, cfg = DB(), config.collection()
    week = date.fromisoformat(args.week) if args.week else latest_week(db, cfg["method_version"])
    if not week:
        sys.exit("nothing computed yet")
    result = run(db, cfg, week, config.items(), config.weights(cfg), config.basket(cfg), config.geo(),
                 config.qa_overrides(), args.draft)
    print(json.dumps(result, indent=1))
    sys.exit(0 if result["published"] or args.draft else 1)
