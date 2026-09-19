"""Build, gate, and publish the regional reconstruction snapshot.

A separate artifact from the weekly measured snapshot, with its own schema, so
the site can never mistake one for the other:

    snapshots/regional/<method_version>/<latest_month>.json   schema sc-price-observatory/regional@1
    snapshots/regional/<method_version>/<latest_month>_hours.csv      every geo x month
    snapshots/regional/<method_version>/<latest_month>_concepts.csv   every concept x month, how it was priced
    snapshots/regional_latest.json, and entries in snapshots/manifest.json

Files are never overwritten (a re-publish becomes <month>.r2.json).

    python -m execution.export_regional [--draft]
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
from datetime import date, datetime, timezone

from execution import qa_checks
from execution.compute_index import load_observations
from execution.compute_regional import compute, load_values, load_wages, overlap, time_prices
from execution.config import TMP
from execution.export_snapshot import SNAPSHOTS

SCHEMA = "sc-price-observatory/regional@1"
DISCLAIMER = ("A reconstruction, not a measurement. Prices are BLS average prices for the whole South Census "
              "region (urban areas, every brand and store type), not prices collected in South Carolina. "
              "Wages are measured locally: QCEW average weekly wage for each county. The measured series "
              "starts in September 2026 and supersedes this one as it accumulates.")


def _month(d: date) -> str:
    return d.isoformat()[:7]


def build(db, reg: dict, basket_doc: dict, items: list[dict], geo_rows: list[dict], obs=None) -> dict:
    months, priced, basket = compute(db, reg, basket_doc)
    qty = basket_doc["weekly_quantity"]
    wages = load_wages(db)
    label = {i["concept"]: i["label"] for i in items if i["tier"] in ("store_brand", "unbranded")}
    unit = {i["concept"]: i["norm_unit"] for i in items}
    published = [b for b in basket if b["status"] == "published"]

    geos, first_wage = [], {}
    for g in geo_rows:
        tp = time_prices(basket, wages.get(g["geo_id"], []))
        first_wage[g["geo_id"]] = min((q for q, _ in wages.get(g["geo_id"], [])), default=None)
        geos.append({
            "geo_id": g["geo_id"], "geo_type": g["geo_type"], "name": g["name"], "parent_geo_id": g["parent_geo_id"],
            "series": [{"month": _month(t["month"]), "status": t["status"],
                        "hours_to_basket": t["hours_to_basket"] if t["status"] == "published" else None,
                        "avg_weekly_wage": t["avg_weekly_wage"], "wage_is_projected": t["wage_is_projected"]}
                       for t in tp]})

    state_pts = [s for s in next(x for x in geos if x["geo_id"] == "45")["series"] if s["hours_to_basket"] is not None]
    headline = None
    if state_pts:
        a, b = state_pts[0], state_pts[-1]
        headline = {"geo_id": "45", "from": a, "to": b,
                    "sentence": (f"By this estimate, a week of the regional basket took {a['hours_to_basket']:.1f} hours "
                                 f"of average South Carolina work in {a['month']} and {b['hours_to_basket']:.1f} "
                                 f"hours in {b['month']}.")}
    comparison = {}
    values = load_values(db, list(reg["comparison_series"]))
    start = months[0] if months else None
    for sid, name in reg["comparison_series"].items():
        v = values.get(sid, {})
        comparison[sid] = {"label": name,
                           "values": [{"month": _month(m), "value": v[m]} for m in sorted(v) if start and m >= start]}
    obs = load_observations(db) if obs is None else obs
    return {
        "schema": SCHEMA, "kind": "regional_reconstruction", "label": reg["label"],
        "method_version": reg["method_version"],
        "latest_month": _month(published[-1]["month"]) if published else None,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "disclaimer": DISCLAIMER,
        "config": {
            "area": reg["area"], "start_month": reg["start_month"], "imputation": reg["imputation"],
            "suppress_imputed_share_above": reg["suppress_imputed_share_above"],
            "basket_version": basket_doc.get("basket_version"), "basket_status": basket_doc.get("status"),
            "household": basket_doc.get("household"),
            "wage_source": "BLS QCEW average weekly wage, all industries, all ownerships; regions employment-weighted; "
                           "read at mid-month, interpolated between quarter midpoints, held flat and flagged "
                           "wage_is_projected after the last published quarter",
            "wage_first_quarter": {k: v.isoformat() if v else None for k, v in first_wage.items()},
            "concepts": [{"concept": c, "label": label.get(c, c), "norm_unit": unit.get(c),
                          "weekly_quantity": qty[c], **spec} for c, spec in reg["concepts"].items()],
            "excluded": [{"concept": c, "reason": why} for c, why in reg["excluded"].items()],
        },
        "headline": headline,
        "basket": [{**b, "month": _month(b["month"]),
                    "cost": b["cost"] if b["status"] == "published" else None} for b in basket],
        "geos": geos,
        "comparison": comparison,
        "overlap": overlap(obs, items, reg, qty, basket),
        "_concepts": {c: {_month(m): (cm.price, cm.how) for m, cm in by.items()} for c, by in priced.items()},
    }


def _hours_csv(snap: dict) -> str:
    buf = io.StringIO()
    wr = csv.writer(buf)
    wr.writerow(["month", "geo_id", "name", "geo_type", "status", "basket_cost", "avg_weekly_wage",
                 "wage_is_projected", "hours_to_basket", "method_version"])
    cost = {b["month"]: b["cost"] for b in snap["basket"]}
    for g in snap["geos"]:
        for s in g["series"]:
            wr.writerow([s["month"], g["geo_id"], g["name"], g["geo_type"], s["status"], cost.get(s["month"]),
                         s["avg_weekly_wage"], s["wage_is_projected"], s["hours_to_basket"], snap["method_version"]])
    return buf.getvalue()


def _concepts_csv(snap: dict) -> str:
    buf = io.StringIO()
    wr = csv.writer(buf)
    wr.writerow(["month", "concept", "bls_series", "unit_price", "norm_unit", "priced_by"])
    spec = {c["concept"]: c for c in snap["config"]["concepts"]}
    for c, by in snap["_concepts"].items():
        for m, (price, how) in by.items():
            wr.writerow([m, c, spec[c]["series"], None if price is None else round(price, 5), spec[c]["norm_unit"], how])
    return buf.getvalue()


def previous_snapshots(method: str) -> list[dict]:
    d = SNAPSHOTS / "regional" / method
    return [json.loads(p.read_text()) for p in sorted(d.glob("*.json"))] if d.exists() else []


def publish(snap: dict) -> list[str]:
    d = SNAPSHOTS / "regional" / snap["method_version"]
    d.mkdir(parents=True, exist_ok=True)
    stem, n = snap["latest_month"], 1
    while (d / f"{stem}.json").exists():
        n += 1
        stem = f"{snap['latest_month']}.r{n}"
    public = {k: v for k, v in snap.items() if not k.startswith("_")}
    body = json.dumps(public, separators=(",", ":")).encode()
    files = {d / f"{stem}.json": body, d / f"{stem}_hours.csv": _hours_csv(snap).encode(),
             d / f"{stem}_concepts.csv": _concepts_csv(snap).encode()}
    for p, b in files.items():
        p.write_bytes(b)
    (SNAPSHOTS / "regional_latest.json").write_bytes(body)
    manifest_path = SNAPSHOTS / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {"files": []}
    for p, b in files.items():
        manifest["files"].append({"path": str(p.relative_to(SNAPSHOTS)), "sha256": hashlib.sha256(b).hexdigest(),
                                  "kind": "regional_reconstruction", "month": snap["latest_month"],
                                  "method_version": snap["method_version"], "revision": n,
                                  "published_at": snap["generated_at"]})
    manifest_path.write_text(json.dumps(manifest, indent=1))
    return [str(p) for p in files]


def run(db, reg: dict, basket_doc: dict, items: list[dict], geo_rows: list[dict], overrides: list[dict],
        draft: bool) -> dict:
    snap = build(db, reg, basket_doc, items, geo_rows)
    report = qa_checks.run_regional(reg, basket_doc, snap, previous_snapshots(reg["method_version"]), overrides)
    snap["qa"] = {"passed": report["passed"],
                  "failed_gates": [g["gate"] for g in report["gates"] if not g["passed"]]}
    if draft:
        snap["draft"] = True
        out = TMP / "snapshots" / f"draft_regional_{snap['latest_month']}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({k: v for k, v in snap.items() if not k.startswith("_")}, indent=1))
        (out.with_suffix(".hours.csv")).write_text(_hours_csv(snap))
        (out.with_suffix(".concepts.csv")).write_text(_concepts_csv(snap))
        return {"published": False, "draft_path": str(out), "qa": snap["qa"], "headline": snap["headline"]}
    if not report["passed"]:
        return {"published": False, "qa": snap["qa"],
                "report": str(TMP / f"qa_report_regional_{snap['latest_month']}.json")}
    snap["draft"] = False
    return {"published": True, "files": publish(snap), "qa": snap["qa"], "headline": snap["headline"]}


if __name__ == "__main__":
    import argparse
    import sys

    from execution import config
    from execution.db import DB

    ap = argparse.ArgumentParser()
    ap.add_argument("--draft", action="store_true")
    args = ap.parse_args()
    db, cfg = DB(), config.collection()
    result = run(db, config.regional(), config.basket(cfg), config.items(), config.geo(), config.qa_overrides(),
                 args.draft)
    print(json.dumps(result, indent=1, default=str))
    sys.exit(0 if result["published"] or args.draft else 1)
