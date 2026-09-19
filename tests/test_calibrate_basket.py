"""Basket calibration against the USDA Thrifty Food Plan, 2021 (reference family of four)."""
import json
from collections import defaultdict

import pytest

from execution import calibrate_basket, config
from execution.calibrate_basket import allocate, build, coffee_oz

TFP, CAL = calibrate_basket.load()


def test_tfp_table_transcription_adds_up_to_the_published_subtotals():
    # USDA prints every figure rounded to 0.01, so a group may differ from its parts by one unit
    for name, g in TFP["groups"].items():
        parts = [TFP["categories"][c] for c in g["categories"]]
        assert sum(p["lbs"] for p in parts) == pytest.approx(g["lbs"], abs=0.011), name
        assert sum(p["cost"] for p in parts) == pytest.approx(g["cost"], abs=0.011), name
    assert sorted(c for g in TFP["groups"].values() for c in g["categories"]) == sorted(TFP["categories"])
    assert sum(g["lbs"] for g in TFP["groups"].values()) == pytest.approx(TFP["total"]["lbs"], abs=0.011)
    assert sum(g["cost"] for g in TFP["groups"].values()) == pytest.approx(TFP["total"]["cost"], abs=0.011)


def test_every_category_is_allocated_and_its_pounds_are_conserved():
    assert set(CAL["allocation"]) == set(TFP["categories"])
    by_cat = defaultdict(float)
    for parts in allocate(TFP, CAL).values():
        for p in parts:
            by_cat[p["category"]] += p["lbs"]
    for cat, c in TFP["categories"].items():
        if "derived" not in CAL["allocation"][cat]:
            assert by_cat[cat] == pytest.approx(c["lbs"]), cat


def test_within_category_split_follows_ers_availability():
    a = allocate(TFP, CAL)
    lbs = {c: sum(p["lbs"] for p in ps if p["category"] == "fruit_whole") for c, ps in a.items()}
    ers = {p["concepts"][0]: p["ers"]["value"] for p in CAL["allocation"]["fruit_whole"]["parts"]}
    assert lbs["bananas"] / lbs["apples"] == pytest.approx(ers["bananas"] / ers["apples"])
    # a group splits by ERS first, then evenly inside the group
    meat = {c: sum(p["lbs"] for p in ps if p["category"] == "protein_meats") for c, ps in a.items()}
    assert meat["ground_beef"] == pytest.approx(meat["hot_dogs"])
    beef, pork = (p["ers"]["value"] for p in CAL["allocation"]["protein_meats"]["parts"])
    assert (meat["ground_beef"] * 3) / (meat["bacon"] * 2) == pytest.approx(beef / pork)


def test_unit_conversions():
    doc = build(TFP, CAL, config.items())
    q, prov = doc["weekly_quantity"], doc["provenance"]
    assert q["milk_whole"] == pytest.approx(prov["milk_whole"]["lbs_per_week"] * 15.34, abs=0.01)
    assert q["pinto_beans_dry"] == pytest.approx(6.06 * 5.51 / 21.00, abs=0.001)      # canned lb -> dry lb
    assert 1.3 < q["eggs_large"] < 1.45                                                # 2.12 lb at ~1.55 lb/dozen
    assert coffee_oz(CAL["conversions"]["by_concept"]["coffee_ground"]) == pytest.approx(6.43, abs=0.01)


def test_every_standard_basket_concept_has_a_quantity():
    doc = build(TFP, CAL, config.items())
    assert set(doc["weekly_quantity"]) == {i["concept"] for i in config.items() if i["active"]}
    assert all(v > 0 for v in doc["weekly_quantity"].values())


def test_basket_file_is_generated_not_hand_edited():
    on_disk = json.loads(calibrate_basket.OUT.read_text())
    assert on_disk["weekly_quantity"] == build(TFP, CAL, config.items())["weekly_quantity"], \
        "rerun: python -m execution.calibrate_basket"
    assert config.collection()["basket_file"] == "config/basket_tfp2021.json"
