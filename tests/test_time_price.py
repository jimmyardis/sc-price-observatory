from datetime import date

import pytest

from execution.compute_time_price import hours_to_basket, parse_qcew, quarter_mid, wage_at

HEADER = "area_fips,own_code,industry_code,agglvl_code,disclosure_code,month1_emplvl,month2_emplvl,month3_emplvl,total_qtrly_wages,avg_wkly_wage"
CSV = "\n".join([
    HEADER,
    '"45000","0","10","50","",100,100,100,130000,1000',
    '"45079","0","10","70","",30,30,30,46800,1200',
    '"45063","0","10","70","",10,10,10,10400,800',
    '"45001","0","10","70","N",0,0,0,0,0',
    '"45999","0","10","70","",1,1,1,13,1000',
    '"45079","5","10","71","",25,25,25,1,1',
    '"37001","0","10","70","",1,1,1,1,1',
])
PARENT = {"45": None, "region:midlands": "45", "45079": "region:midlands", "45063": "region:midlands",
          "45001": "region:upstate"}


def test_parse_qcew_counties_state_and_employment_weighted_region():
    out = parse_qcew(CSV, PARENT)
    assert out["45"]["avg_weekly_wage"] == 1000
    assert out["45079"]["avg_weekly_wage"] == 1200
    assert "45001" not in out and "45999" not in out      # suppressed / undefined
    # (46800 + 10400) / 40 employees / 13 weeks
    assert out["region:midlands"]["avg_weekly_wage"] == pytest.approx(110)


def test_wage_interpolates_between_quarter_midpoints():
    series = [(date(2025, 10, 1), 1000.0), (date(2026, 1, 1), 1100.0)]
    mid0, mid1 = quarter_mid(date(2025, 10, 1)), quarter_mid(date(2026, 1, 1))
    w, projected = wage_at(mid0 + (mid1 - mid0) / 2, series)
    assert w == pytest.approx(1050, abs=1) and not projected


def test_wage_held_forward_and_flagged_projected():
    series = [(date(2025, 10, 1), 1000.0), (date(2026, 1, 1), 1100.0)]
    assert wage_at(date(2026, 1, 20), series)[1] is False            # interpolated between two quarters
    assert wage_at(date(2026, 9, 14), series) == (1100.0, True)     # past the last quarter: projected


def test_wage_past_last_midpoint_is_projected_because_the_next_quarter_will_move_it():
    series = [(date(2026, 1, 1), 1100.0)]
    before, _ = wage_at(date(2026, 3, 30), series)
    assert wage_at(date(2026, 3, 30), series) == (1100.0, True)
    after, _ = wage_at(date(2026, 3, 30), series + [(date(2026, 4, 1), 1200.0)])
    assert after != before


def test_hours_to_basket():
    assert hours_to_basket(250.0, 1000.0) == 10.0
    assert hours_to_basket(None, 1000.0) is None
    assert hours_to_basket(250.0, None) is None
