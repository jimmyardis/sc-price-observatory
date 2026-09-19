import json
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
import requests

from execution.collectors._base import CollectorBlocked, PoliteClient, week_of
from execution.collectors.kroger import parse_location, parse_products

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "kroger_products.json").read_text())
ITEMS = {
    "milk_whole_store": {"item_id": "milk_whole_store", "norm_unit": "fl_oz"},
    "bananas": {"item_id": "bananas", "norm_unit": "lb"},
    "peanut_butter_national": {"item_id": "peanut_butter_national", "norm_unit": "oz"},
    "eggs_large_dozen": {"item_id": "eggs_large_dozen", "norm_unit": "dozen"},
}
MAPPING = {
    "0001111041700": {"item_id": "milk_whole_store", "pack_size": 128},
    "0000000004011": {"item_id": "bananas", "pack_size": 1},
    "0004400000054": {"item_id": "peanut_butter_national", "pack_size": 16},   # shrank to 15 oz
    "0001111000000": {"item_id": "eggs_large_dozen", "pack_size": 1},
}


def parse(**kw):
    return parse_products(FIXTURE, MAPPING, ITEMS, store_id="kroger:01400943", week=date(2026, 9, 14),
                          collected_at="2026-09-16T06:00:00+00:00", payload_hash="abc", **kw)


def test_parse_products_shelf_and_promo(tmp_dirs):
    rows = parse()
    milk = [r for r in rows if r["item_id"] == "milk_whole_store"]
    assert {r["price_type"] for r in milk} == {"shelf", "promo"}
    shelf = next(r for r in milk if r["price_type"] == "shelf")
    assert shelf["pack_size"] == 128 and shelf["unit_price"] == pytest.approx(3.49 / 128)


def test_parse_products_weight_unmapped_unpriced(tmp_dirs):
    rows = parse()
    items = [r["item_id"] for r in rows]
    assert "bananas" in items and next(r for r in rows if r["item_id"] == "bananas")["unit_price"] == 0.59
    assert not any(r["raw_sku"] == "0009999999999" for r in rows)   # unmapped
    assert "eggs_large_dozen" not in items                           # no price -> missing, not zero


def test_pack_size_is_observed_not_assumed_and_change_is_logged(tmp_dirs):
    tmp, _ = tmp_dirs
    pb = next(r for r in parse() if r["item_id"] == "peanut_butter_national")
    assert pb["pack_size"] == 15 and pb["unit_price"] == pytest.approx(3.79 / 15)
    problems = [json.loads(l) for l in (tmp / "problems.jsonl").read_text().splitlines()]
    assert any(p["kind"] == "pack_size_changed" and p["observed"] == 15 for p in problems)


def test_parse_location_filters_to_sc_known_chains(tmp_dirs):
    loc = {"locationId": "01400943", "chain": "KROGER", "address": {"state": "SC", "addressLine1": "1 Main",
           "city": "Columbia", "zipCode": "29201"}, "geolocation": {"latitude": 34.0, "longitude": -81.0}}
    assert parse_location(loc)["store_id"] == "kroger:01400943"
    assert parse_location({**loc, "address": {"state": "NC"}}) is None
    assert parse_location({**loc, "chain": "FRED MEYER"}) is None


class FakeSession(requests.Session):
    def __init__(self, codes):
        super().__init__()
        self.codes, self.calls = list(codes), 0

    def request(self, method, url, **kw):
        self.calls += 1
        r = requests.Response()
        r.status_code = self.codes.pop(0)
        r._content = b"{}"
        return r


@pytest.mark.parametrize("code", [403, 429])
def test_hard_stop_on_block_writes_alert(tmp_dirs, code):
    tmp, _ = tmp_dirs
    s = FakeSession([code, 200])
    client = PoliteClient("walmart", min_interval=0, session=s, sleep=lambda _: None)
    with pytest.raises(CollectorBlocked):
        client.request("GET", "https://example.test/x")
    assert s.calls == 1                                   # never retried past a block
    assert list((tmp / "alerts").glob("walmart_*.json"))


def test_backoff_on_5xx_then_success(tmp_dirs):
    slept = []
    s = FakeSession([503, 502, 200])
    client = PoliteClient("kroger", min_interval=0, session=s, sleep=slept.append)
    assert client.request("GET", "https://example.test/x").status_code == 200
    assert s.calls == 3 and len(slept) == 2 and slept[1] > slept[0]


def test_week_of_is_local_monday():
    # 02:00 UTC Tuesday is still Monday night in Eastern time
    assert week_of(datetime(2026, 9, 15, 2, 0, tzinfo=timezone.utc)) == date(2026, 9, 14)
    assert week_of(datetime(2026, 9, 20, 23, 0, tzinfo=timezone.utc)) == date(2026, 9, 14)


def test_observations_are_append_only(db):
    from execution import load_reference
    load_reference.run(db)
    db.upsert("stores", {"store_id": "kroger:1", "banner": "kroger", "retailer_num": "1", "geo_id": "45079"},
              ["store_id"])
    db.execute("INSERT INTO observations (collected_at, week, store_id, item_id, raw_sku, raw_label, price, "
               "pack_size, unit_price, price_type, source, payload_hash) VALUES "
               "('2026-09-15', '2026-09-14', 'kroger:1', 'bananas', 'x', 'x', 1, 1, 1, 'shelf', 'api', 'h')")
    db.commit()
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        db.execute("UPDATE observations SET price = 2")
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        db.execute("DELETE FROM observations")
