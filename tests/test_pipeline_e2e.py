"""End-to-end on synthetic observations (tests only; never loaded into a real DB)."""
import json
from datetime import date, timedelta

import pandas as pd
import pytest

from execution import (compute_index, compute_time_price, config, export_snapshot, load_reference,
                       qa_checks)
from execution.collectors._base import insert_observations

START = date(2026, 6, 1)   # Monday; June 2026 is a full collection month
WEEKS = 14
STORES = [("kroger:1", "kroger", "45079"), ("kroger:2", "kroger", "45079"),
          ("harris_teeter:3", "harris_teeter", "45079"), ("kroger:4", "kroger", "45063")]


def seed(db, weeks=WEEKS, drift=0.002, skip=()):
    load_reference.run(db)
    for sid, banner, geo in STORES:
        db.upsert("stores", {"store_id": sid, "banner": banner, "retailer_num": sid.split(":")[1], "geo_id": geo},
                  ["store_id"])
    for gid, wage in (("45", 1100), ("45079", 1300), ("45063", 1000), ("region:midlands", 1150)):
        db.upsert("wages", {"geo_id": gid, "quarter": "2026-04-01", "avg_weekly_wage": wage}, ["geo_id", "quarter"])
    db.commit()
    rows = []
    for n in range(weeks):
        wk = START + timedelta(weeks=n)
        for s, (sid, _, _) in enumerate(STORES):
            for k, item in enumerate(config.items()):
                if (n, sid, item["item_id"]) in skip:
                    continue
                unit = (0.10 + 0.01 * k) * (1 + 0.03 * s) * (1 + drift) ** n
                rows.append({"collected_at": f"{wk}T06:00:00+00:00", "week": wk.isoformat(), "store_id": sid,
                             "item_id": item["item_id"], "raw_sku": f"sku{k}", "raw_label": item["label"],
                             "price": unit * 10, "pack_size": 10, "unit_price": unit, "price_type": "shelf",
                             "source": "api", "payload_hash": "synthetic"})
    insert_observations(db, rows)


def verified_configs():
    cfg = config.collection()
    weights = {**config.weights(cfg), "verified": True}
    basket = {**config.basket(cfg), "status": "final"}
    return cfg, weights, basket


def compute(db, cfg, weights, basket):
    compute_index.run(db, cfg, config.items(), weights, basket, config.geo())
    compute_time_price.run(db, cfg)


def export(db, cfg, weights, basket, week, draft=False):
    return export_snapshot.run(db, cfg, week, config.items(), weights, basket, config.geo(), [], draft)


LAST = START + timedelta(weeks=WEEKS - 1)


def test_full_run_publishes_levels_index_and_headline(db, tmp_dirs):
    _, snaps = tmp_dirs
    cfg, weights, basket = verified_configs()
    seed(db)
    compute(db, cfg, weights, basket)
    result = export(db, cfg, weights, basket, LAST)
    assert result["published"], result
    snap = json.loads((snaps / "latest.json").read_text())
    by = {g["geo_id"]: g for g in snap["geos"]}

    richland = by["45079"]
    assert richland["status"] == "published"
    assert richland["coverage"]["stores_by_banner"] == {"kroger": 2, "harris_teeter": 1}
    assert richland["index"]["base_status"] == "final"
    # June = base; every price drifts 0.2%/week, so index tracks the drift exactly
    june_mean = sum(1.002 ** n for n in range(5)) / 5
    assert richland["index"]["value"] == pytest.approx(100 * 1.002 ** 13 / june_mean, rel=1e-4)
    assert richland["index"]["wow_pct"] == pytest.approx(0.2, abs=0.01)
    assert richland["levels"]["hours_to_basket"] == pytest.approx(
        richland["levels"]["basket_cost"] / (1300 / 40), abs=0.01)
    assert richland["levels"]["wage_is_projected"] is True

    lexington = by["45063"]                           # one store, one banner
    assert lexington["status"] == "thin_coverage" and lexington["levels"] is None
    assert lexington["rolled_up_to"] == "region:midlands"
    assert by["45007"]["status"] == "no_data"

    assert snap["headline"]["sentence"].endswith("hours of average local work buys a week of groceries for a family of three.")
    assert richland["tier_gap"]["n_concepts"] == 17
    assert len(snap["basket"]) == 60
    manifest = json.loads((snaps / "manifest.json").read_text())
    assert {f["path"] for f in manifest["files"]} == {f"0.1.0/{LAST}.json", f"0.1.0/{LAST}_levels.csv"}


def test_draft_configs_block_publication(db, tmp_dirs):
    _, snaps = tmp_dirs
    cfg = config.collection()
    weights, basket = config.weights(cfg), config.basket(cfg)   # the real, still-draft files
    seed(db, weeks=3)
    compute(db, cfg, weights, basket)
    week = START + timedelta(weeks=2)
    result = export(db, cfg, weights, basket, week)
    assert not result["published"] and "config_verified" in result["qa"]["failed_gates"]
    assert not snaps.exists()
    draft = export(db, cfg, weights, basket, week, draft=True)
    assert json.loads(open(draft["draft_path"]).read())["draft"] is True


def test_heavy_imputation_is_suppressed(db, tmp_dirs):
    cfg, weights, basket = verified_configs()
    items = [i["item_id"] for i in config.items()]
    missing = {(3, sid, it) for sid, _, _ in STORES for it in items[:40]}   # 2/3 of items vanish in week 3
    seed(db, weeks=4, skip=missing)
    compute(db, cfg, weights, basket)
    snap = export_snapshot.build(db, cfg, START + timedelta(weeks=3), config.items(), weights, basket, config.geo())
    richland = next(g for g in snap["geos"] if g["geo_id"] == "45079")
    assert richland["status"] == "suppressed" and richland["levels"] is None


def test_silent_revision_blocks_until_method_version_bumps(db, tmp_dirs):
    cfg, weights, basket = verified_configs()
    seed(db, weeks=3)
    compute(db, cfg, weights, basket)
    assert export(db, cfg, weights, basket, START + timedelta(weeks=2))["published"]

    # a late re-collection for week 1 changes an already-published basket cost
    k, item = next((k, i) for k, i in enumerate(config.items()) if i["item_id"] == "milk_whole_store")
    wk1 = START + timedelta(weeks=1)
    insert_observations(db, [{"collected_at": f"{wk1}T23:00:00+00:00", "week": wk1.isoformat(), "store_id": sid,
                              "item_id": item["item_id"], "raw_sku": "sku", "raw_label": "x", "price": 1,
                              "pack_size": 10, "unit_price": 1.03 * (0.10 + 0.01 * k) * (1 + 0.03 * s) * 1.002,
                              "price_type": "shelf", "source": "api", "payload_hash": "synthetic"}
                             for s, (sid, _, _) in enumerate(STORES)])
    compute(db, cfg, weights, basket)
    result = export(db, cfg, weights, basket, START + timedelta(weeks=2))
    assert not result["published"] and "no_silent_revision" in result["qa"]["failed_gates"]

    cfg2 = {**cfg, "method_version": "0.1.1"}
    compute(db, cfg2, weights, basket)
    result = export(db, cfg2, weights, basket, START + timedelta(weeks=2))
    assert result["published"], result["qa"]


def test_qa_outlier_and_store_drop_gates(db):
    obs = pd.DataFrame(
        [(i, f"{START + timedelta(weeks=n)}", START + timedelta(weeks=n), "kroger:1", "milk", 1.0, "shelf")
         for i, n in enumerate(range(4))]
        + [(10, "x", START + timedelta(weeks=4), "kroger:1", "milk", 6.0, "shelf")],
        columns=["obs_id", "collected_at", "week", "store_id", "item_id", "unit_price", "price_type"])
    out = qa_checks.unit_price_outliers(obs, START + timedelta(weeks=4))
    assert len(out) == 1 and out[0]["ratio"] == 6.0

    wk = START + timedelta(weeks=1)
    obs2 = pd.DataFrame([(1, "x", START, f"kroger:{s}", "milk", 1.0, "shelf") for s in range(5)]
                        + [(2, "x", wk, f"kroger:{s}", "milk", 1.0, "shelf") for s in range(3)],
                        columns=obs.columns)
    drops = qa_checks.banner_store_drops(obs2, {f"kroger:{s}": "kroger" for s in range(5)}, wk)
    assert drops == [{"key": f"kroger|{wk}", "banner": "kroger", "stores_prev": 5, "stores_now": 3}]
