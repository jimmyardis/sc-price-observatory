"""Regional reconstruction: BLS fetch, gap filling, county time price, snapshot gates (synthetic data only)."""
import json
from datetime import date

import pytest

from execution import compute_regional, config, export_regional, load_reference
from execution.compute_regional import (ConceptMonth, basket_months, month_add, months_between, price_concept,
                                        time_prices)
from execution.fetch_bls import (BLSClient, BLSQuotaExceeded, parse_period, parse_response, qcew_series, store,
                                 wage_rows)

M = [date(2026, m, 1) for m in range(1, 7)]


# --- fetch_bls ---------------------------------------------------------------

def api_doc(series: dict[str, list[tuple[str, str, str]]]) -> dict:
    return {"status": "REQUEST_SUCCEEDED", "message": [], "Results": {"series": [
        {"seriesID": sid, "data": [{"year": y, "period": p, "value": v, "footnotes": [{}]} for y, p, v in rows]}
        for sid, rows in series.items()]}}


def test_parse_period_months_quarters_and_annual_codes():
    assert parse_period("2026", "M08") == date(2026, 8, 1)
    assert parse_period("2007", "Q04") == date(2007, 10, 1)
    assert parse_period("2026", "M13") is None and parse_period("2026", "A01") is None


def test_parse_response_skips_unpublished_values_and_raises_on_quota():
    rows = parse_response(api_doc({"APU0300709112": [("2025", "M10", "-"), ("2025", "M09", "3.904")]}))
    assert rows == [{"series_id": "APU0300709112", "period": date(2025, 9, 1), "value": 3.904, "footnotes": None}]
    with pytest.raises(BLSQuotaExceeded):
        parse_response({"status": "REQUEST_NOT_PROCESSED",
                        "message": ["the daily threshold for total number of requests ... has been reached."]})


class FakeResp:
    status_code = 200

    def __init__(self, doc):
        self.content = json.dumps(doc).encode()

    def raise_for_status(self):
        pass

    def json(self):
        return json.loads(self.content)


class FakeSession:
    def __init__(self):
        self.headers, self.bodies = {}, []

    def request(self, method, url, timeout=None, json=None):
        self.bodies.append(json)
        return FakeResp(api_doc({sid: [(json["startyear"], "M01", "1.0")] for sid in json["seriesid"]}))


def test_client_batches_series_and_windows_years_and_caches_closed_years(tmp_dirs):
    s = FakeSession()
    c = BLSClient(key="", session=s, sleep=lambda _: None)
    c.today = date(2026, 9, 19)
    rows, _ = c.fetch([f"S{i:02d}" for i in range(30)], 2006, 2026)
    # 2 batches (25 + 5) x 3 windows (2006-15, 2016-25, 2026)
    assert c.queries == 6 and {(b["startyear"], b["endyear"]) for b in s.bodies} == {
        ("2006", "2015"), ("2016", "2025"), ("2026", "2026")}
    assert len(rows) == 90
    c.fetch([f"S{i:02d}" for i in range(30)], 2006, 2026)
    assert c.queries == 8                                    # closed windows served from cache; 2026 refetched


def test_client_with_key_uses_larger_limits_and_sends_key(tmp_dirs):
    s = FakeSession()
    c = BLSClient(key="k", session=s, sleep=lambda _: None)
    c.fetch([f"S{i:02d}" for i in range(30)], 2006, 2026)
    assert c.queries == 2 and all(b["registrationkey"] == "k" for b in s.bodies)


def test_store_counts_new_and_revised_values(db):
    row = {"series_id": "X", "period": date(2026, 1, 1), "value": 1.0, "footnotes": None, "payload_hash": "h"}
    assert store(db, [row], "BLS API") == {"new": 1, "revised": 0}
    assert store(db, [row], "BLS API") == {"new": 0, "revised": 0}
    assert store(db, [{**row, "value": 1.1}], "BLS API") == {"new": 0, "revised": 1}


def test_wage_rows_from_qcew_series_with_employment_weighted_region():
    q = date(2007, 10, 1)
    vals = []
    for area, wage, emp, total in (("45000", 700, 100, 910000), ("45079", 800, 30, 312000), ("45063", 600, 10, 78000)):
        vals.append({"series_id": qcew_series(area, 4), "period": q, "value": wage})
        vals.append({"series_id": qcew_series(area, 3), "period": q, "value": total})
        vals += [{"series_id": qcew_series(area, 1), "period": date(2007, m, 1), "value": emp} for m in (10, 11, 12)]
    parent = {"45": None, "region:midlands": "45", "45079": "region:midlands", "45063": "region:midlands"}
    out = wage_rows(vals, parent)
    assert out[("45", q)]["avg_weekly_wage"] == 700 and out[("45079", q)]["avg_weekly_wage"] == 800
    assert out[("region:midlands", q)]["avg_weekly_wage"] == pytest.approx((312000 + 78000) / 40 / 13, abs=0.01)


# --- gap filling ---------------------------------------------------------------

def test_gap_hierarchy_us_relative_then_basket_relative_then_carry():
    south = {M[0]: 2.0, M[4]: 3.0}
    us = {M[0]: 1.0, M[1]: 1.1}                  # the U.S. series covers only February
    rel = {M[1]: 1.5, M[2]: 1.2, M[3]: None}     # March has a basket relative; April has nothing
    out = price_concept(south, us, rel, M[:5], max_impute=36, max_carry=2)
    assert out[M[0]] == ConceptMonth(2.0, "published")
    assert out[M[1]].price == pytest.approx(2.2) and out[M[1]].how == "imputed_us"   # own item first
    assert out[M[2]].price == pytest.approx(2.64) and out[M[2]].how == "imputed_basket"
    assert out[M[3]].price == pytest.approx(2.64) and out[M[3]].how == "carried"
    assert out[M[4]] == ConceptMonth(3.0, "published")


def test_gaps_are_never_filled_from_the_future_and_carry_is_capped():
    out = price_concept({M[0]: 2.0, M[5]: 9.0}, {}, {}, M, max_impute=36, max_carry=2)
    assert [out[m].how for m in M] == ["published", "carried", "carried", None, None, "published"]
    assert out[M[1]].price == 2.0                                      # not pulled toward 9.0


def test_imputation_stops_after_max_impute_months():
    us = {m: 1.0 for m in M}
    out = price_concept({M[0]: 2.0}, us, {}, M, max_impute=3, max_carry=2)
    assert [out[m].how for m in M] == ["published", "imputed_us", "imputed_us", "imputed_us", None, None]


def test_basket_months_status_share_and_units():
    priced = {"milk": {M[0]: ConceptMonth(4.0 / 128, "published"), M[1]: ConceptMonth(4.0 / 128, "published")},
              "eggs": {M[0]: ConceptMonth(3.0, "imputed_us"), M[1]: ConceptMonth(None, None)}}
    rows = basket_months(priced, {"milk": 192, "eggs": 1}, M[:2], threshold=0.25)
    assert rows[0]["cost"] == 9.0 and rows[0]["imputed_share"] == pytest.approx(3 / 9, abs=1e-4)
    assert rows[0]["status"] == "suppressed"
    assert rows[1] == {"month": M[1], "cost": None, "n_concepts": 2, "n_imputed": 0, "imputed_share": 0.0,
                       "status": "no_data"}


def test_no_wage_before_the_first_published_quarter():
    basket = [{"month": date(2013, 12, 1), "cost": 80.0, "status": "published"},
              {"month": date(2014, 1, 1), "cost": 80.0, "status": "published"}]
    out = time_prices(basket, [(date(2014, 1, 1), 800.0)])
    assert out[0]["status"] == "no_data" and out[0]["hours_to_basket"] is None     # not the 2014 wage held back
    assert out[1]["hours_to_basket"] == 4.0 and out[1]["status"] == "published"


def test_month_helpers():
    assert month_add(date(2025, 12, 1), 1) == date(2026, 1, 1) and month_add(date(2026, 1, 1), -1) == date(2025, 12, 1)
    assert len(months_between(date(2006, 1, 1), date(2026, 8, 1))) == 248


# --- end to end ----------------------------------------------------------------

REG = config.regional()
START, END = date(2024, 1, 1), date(2024, 12, 1)


def seed(db, drift=0.01):
    load_reference.run(db)
    rows = []
    for k, spec in enumerate(REG["concepts"].values()):
        for n, m in enumerate(months_between(START, END)):
            for sid in (spec["series"], compute_regional.us_series(spec["series"], REG)):
                rows.append((sid, m.isoformat(), (1 + k / 10) * (1 + drift) ** n))
    db.executemany("INSERT INTO reference_values (series_id, period, value, payload_hash) VALUES (?, ?, ?, 'syn')", rows)
    for q in ("2024-01-01", "2024-04-01", "2024-07-01"):
        for g in config.geo():
            db.upsert("wages", {"geo_id": g["geo_id"], "quarter": q, "avg_weekly_wage": 1000.0}, ["geo_id", "quarter"])
    db.commit()


def regional_run(db, reg=None, basket=None, draft=False):
    reg = reg or {**REG, "start_month": "2024-01"}
    basket = basket or {**config.basket(config.collection()), "status": "final"}
    compute_regional.run(db, reg, basket, config.geo())
    return export_regional.run(db, reg, basket, config.items(), config.geo(), [], draft)


def test_regional_publishes_a_separate_labeled_snapshot(db, tmp_dirs):
    seed(db)
    result = regional_run(db)
    assert result["published"], result["qa"]
    snap = json.loads((tmp_dirs[1] / "regional_latest.json").read_text())
    assert snap["schema"] == "sc-price-observatory/regional@1" and "not a measurement" in snap["disclaimer"]
    assert snap["latest_month"] == "2024-12" and len(snap["basket"]) == 12
    state = next(g for g in snap["geos"] if g["geo_id"] == "45")["series"]
    assert state[0]["hours_to_basket"] == pytest.approx(snap["basket"][0]["cost"] / 25, abs=0.01)
    assert state[-1]["wage_is_projected"] is True
    assert {c["concept"] for c in snap["config"]["concepts"]} | {c["concept"] for c in snap["config"]["excluded"]} \
        == set(config.basket(config.collection())["weekly_quantity"])
    assert not (tmp_dirs[1] / "latest.json").exists()             # the measured snapshot is untouched
    files = json.loads((tmp_dirs[1] / "manifest.json").read_text())["files"]
    assert {f["kind"] for f in files} == {"regional_reconstruction"} and len(files) == 3


def test_months_before_any_wage_are_no_data_but_a_one_county_hole_blocks(db, tmp_dirs):
    seed(db)
    reg = {**REG, "start_month": "2023-10"}           # a quarter earlier than any wage we hold
    assert regional_run(db, reg=reg)["published"]     # uniformly wage-less months are fine
    snap = json.loads((tmp_dirs[1] / "regional_latest.json").read_text())
    early = [s for s in next(g for g in snap["geos"] if g["geo_id"] == "45")["series"] if s["month"] < "2024-01"]
    assert early and all(s["status"] == "no_data" and s["hours_to_basket"] is None for s in early)

    db.execute("DELETE FROM wages WHERE geo_id = '45079'")   # one county with no wage at all
    db.commit()
    result = regional_run(db, reg=reg)
    assert not result["published"] and "wages_cover_history" in result["qa"]["failed_gates"]


def test_regional_draft_basket_blocks_publication(db, tmp_dirs):
    seed(db)
    result = regional_run(db, basket={**config.basket(config.collection()), "status": "proposed"})
    assert not result["published"] and "config_verified" in result["qa"]["failed_gates"]


def test_regional_unaccounted_concept_blocks_publication(db, tmp_dirs):
    seed(db)
    reg = {**REG, "start_month": "2024-01", "excluded": {k: v for k, v in REG["excluded"].items() if k != "butter"}}
    result = regional_run(db, reg=reg)
    assert not result["published"] and "concepts_accounted" in result["qa"]["failed_gates"]


def test_regional_revision_blocked_but_new_wage_quarter_is_not(db, tmp_dirs):
    seed(db)
    assert regional_run(db)["published"]

    # QCEW publishes 2024Q4: only projected months move -> publishes (as .r2)
    for g in config.geo():
        db.upsert("wages", {"geo_id": g["geo_id"], "quarter": "2024-10-01", "avg_weekly_wage": 1100.0},
                  ["geo_id", "quarter"])
    db.commit()
    result = regional_run(db)
    assert result["published"], result["qa"]

    # a BLS revision to a published month changes basket cost -> blocked
    db.execute("UPDATE reference_values SET value = value * 1.1 WHERE period = '2024-03-01'")
    db.commit()
    result = regional_run(db)
    assert not result["published"] and "no_silent_revision" in result["qa"]["failed_gates"]
    assert regional_run(db, reg={**REG, "start_month": "2024-01", "method_version": "regional-0.1.1"})["published"]


def test_overlap_puts_measured_weeks_next_to_the_regional_month(db, tmp_dirs):
    import pandas as pd

    seed(db)
    reg = {**REG, "start_month": "2024-01"}
    basket = {**config.basket(config.collection()), "status": "final"}
    _, _, rows = compute_regional.compute(db, reg, basket)
    std = compute_regional.concept_items(config.items(), "standard")
    obs = pd.DataFrame([{"obs_id": i, "collected_at": "2025-01-08T06:00:00", "week": date(2025, 1, 6),
                         "store_id": "kroger:1", "item_id": std[c], "unit_price": 1.0, "price_type": "shelf"}
                        for i, c in enumerate(reg["concepts"])])
    out = compute_regional.overlap(obs, config.items(), reg, basket["weekly_quantity"], rows)
    assert out[0]["regional_month"] == "2024-12-01" and out[0]["regional_month_lag"] == 1
    assert out[0]["measured_cost"] == pytest.approx(sum(basket["weekly_quantity"][c] for c in reg["concepts"]), abs=0.01)
    assert out[0]["measured_over_regional"] == pytest.approx(out[0]["measured_cost"] / rows[-1]["cost"], abs=1e-4)
