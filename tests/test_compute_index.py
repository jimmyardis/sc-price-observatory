import math
from datetime import date, timedelta

import pandas as pd
import pytest

from execution.compute_index import (base_month, basket_cost, compute_geo, concept_items,
                                     effective_prices, rebase)

W0 = date(2026, 9, 7)  # a Monday
STRATUM = {"milk": "FJ01", "cheese": "FJ02", "eggs": "FH01", "bread": "FB01"}
EQUAL = {"FJ01": 1.0, "FJ02": 1.0, "FH01": 1.0, "FB01": 1.0}


def wk(n):
    return W0 + timedelta(weeks=n)


def frame(rows):
    return pd.DataFrame(rows, columns=["week", "store_id", "item_id", "unit_price"])


def test_jevons_within_stratum_is_geometric_mean():
    prices = frame([
        (wk(0), "s1", "milk", 1.0), (wk(0), "s2", "milk", 1.0),
        (wk(1), "s1", "milk", 1.2), (wk(1), "s2", "milk", 1.5),
    ])
    res = compute_geo(prices, STRATUM, EQUAL)
    assert res[0].chain == 100
    assert res[1].chain == pytest.approx(100 * math.sqrt(1.2 * 1.5))


def test_upper_level_weights_strata():
    prices = frame([
        (wk(0), "s1", "milk", 1.0), (wk(0), "s1", "cheese", 1.0),
        (wk(1), "s1", "milk", 1.10), (wk(1), "s1", "cheese", 1.00),
    ])
    res = compute_geo(prices, STRATUM, {"FJ01": 3.0, "FJ02": 1.0})
    assert res[1].chain == pytest.approx(100 * (0.75 * 1.10 + 0.25 * 1.00))


def test_new_item_does_not_move_index():
    prices = frame([
        (wk(0), "s1", "milk", 1.0),
        (wk(1), "s1", "milk", 1.0), (wk(1), "s1", "cheese", 50.0), (wk(1), "s2", "milk", 9.0),
    ])
    assert compute_geo(prices, STRATUM, EQUAL)[1].chain == pytest.approx(100)


def test_missing_item_is_imputed_then_dropped_after_four_weeks():
    rows = [(wk(0), "s1", "milk", 1.0), (wk(0), "s1", "cheese", 2.0)]
    for n in range(1, 7):
        rows.append((wk(n), "s1", "milk", 1.0 * 1.01 ** n))
    res = compute_geo(frame(rows), STRATUM, EQUAL, drop_after=4)
    shares = [r.imputed_share for r in res]
    assert shares[0] == 0
    assert shares[1:5] == [0.5] * 4          # cheese imputed weeks 1-4
    assert shares[5:] == [0.0, 0.0]          # dropped from week 5
    # imputed cheese price moved with the all-strata relative (milk)
    assert res[4].prices[("s1", "cheese")] == pytest.approx(2.0 * 1.01 ** 4)
    assert ("s1", "cheese") not in res[5].prices


def test_disappearing_item_is_not_a_price_change():
    prices = frame([
        (wk(0), "s1", "milk", 1.0), (wk(0), "s1", "cheese", 100.0),
        (wk(1), "s1", "milk", 1.0),
    ])
    assert compute_geo(prices, STRATUM, EQUAL)[1].chain == pytest.approx(100)


def test_returning_item_links_without_a_relative():
    prices = frame([
        (wk(0), "s1", "milk", 1.0), (wk(0), "s1", "cheese", 1.0),
        (wk(1), "s1", "milk", 1.0),
        (wk(2), "s1", "milk", 1.0), (wk(2), "s1", "cheese", 3.0),
        (wk(3), "s1", "milk", 1.0), (wk(3), "s1", "cheese", 3.3),
    ])
    res = compute_geo(prices, STRATUM, EQUAL)
    assert res[2].chain == pytest.approx(100)
    assert res[3].chain == pytest.approx(100 * (1.0 + 1.1) / 2)


def test_shrinkflation_shows_as_inflation():
    # same shelf price, pack shrinks 16 -> 14.5 oz: unit price rises
    prices = frame([(wk(0), "s1", "cheese", 4.00 / 16), (wk(1), "s1", "cheese", 4.00 / 14.5)])
    assert compute_geo(prices, STRATUM, EQUAL)[1].chain == pytest.approx(100 * 16 / 14.5)


def test_collection_gap_week_chains_across():
    prices = frame([(wk(0), "s1", "milk", 1.0), (wk(2), "s1", "milk", 1.2)])
    res = compute_geo(prices, STRATUM, EQUAL)
    assert [r.week for r in res] == [wk(0), wk(2)]
    assert res[1].chain == pytest.approx(120)


def test_effective_prices_shelf_vs_promo():
    obs = pd.DataFrame([
        (1, "2026-09-08T01:00", wk(0), "s1", "milk", 4.00, "shelf"),
        (2, "2026-09-08T01:00", wk(0), "s1", "milk", 3.00, "promo"),
        (3, "2026-09-08T05:00", wk(0), "s1", "milk", 4.20, "shelf"),   # re-collection wins
    ], columns=["obs_id", "collected_at", "week", "store_id", "item_id", "unit_price", "price_type"])
    assert effective_prices(obs, "shelf").unit_price.tolist() == [4.20]
    assert effective_prices(obs, "promo_incl").unit_price.tolist() == [3.00]


def test_base_month_is_first_full_month():
    weeks = [date(2026, 9, 15) + timedelta(weeks=n) for n in range(10)]  # starts mid-September
    assert base_month(weeks) == (2026, 10)
    assert base_month(weeks[:3]) is None


def test_rebase_final_and_provisional():
    vals = {date(2026, 10, 5): 100.0, date(2026, 10, 12): 110.0, date(2026, 11, 2): 121.0}
    out, status = rebase(vals, (2026, 10))
    assert status == "final" and out[date(2026, 11, 2)] == pytest.approx(121 / 105 * 100)
    out, status = rebase(vals, None)
    assert status == "provisional" and out[date(2026, 10, 5)] == 100


def test_basket_cost_and_concept_selection():
    items = [
        {"item_id": "pb_store", "concept": "pb", "tier": "store_brand", "active": True},
        {"item_id": "pb_nat", "concept": "pb", "tier": "national_brand", "active": True},
        {"item_id": "mayo", "concept": "mayo", "tier": "national_brand", "active": True},
    ]
    assert concept_items(items, "standard") == {"pb": "pb_store", "mayo": "mayo"}
    assert concept_items(items, "national") == {"pb": "pb_nat", "mayo": "mayo"}
    prices = {("s1", "pb_store"): 0.10, ("s2", "pb_store"): 0.20, ("s1", "mayo"): 0.25}
    assert basket_cost(prices, {"pb": 10, "mayo": 4}, concept_items(items, "standard")) == (2.5, 0)
    assert basket_cost(prices, {"pb": 10, "mayo": 4}, concept_items(items, "national")) == (None, 1)
