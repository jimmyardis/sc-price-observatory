import pytest

from execution.normalize_units import parse_pack_size


@pytest.mark.parametrize("size,unit,expected", [
    ("1 gal", "fl_oz", 128),
    ("1/2 gal", "fl_oz", 64),
    ("52 fl oz", "fl_oz", 52),
    ("2 L", "fl_oz", 67.628),
    ("48 fl. oz.", "fl_oz", 48),
    ("16 oz", "oz", 16),
    ("16 oz", "lb", 1),
    ("5 lb", "lb", 5),
    ("2 lbs", "oz", 32),
    ("453 g", "oz", 15.979),
    ("12 ct", "dozen", 1),
    ("18 ct", "dozen", 1.5),
    ("1 dozen", "dozen", 1),
    ("1 each", "count", 1),
    ("2 x 16 oz", "oz", 32),
    ("1,000 ml", "fl_oz", 33.814),
])
def test_parses(size, unit, expected):
    assert parse_pack_size(size, unit) == pytest.approx(expected, rel=1e-3)


@pytest.mark.parametrize("size,unit,rule,expected", [
    ("12 ct / 12 fl oz", "fl_oz", "multiply", 144),   # 12 cans of 12 fl oz
    ("4 ct / 14.5 oz", "oz", "multiply", 58),         # 4 cans of 14.5 oz
    ("5 ct / 12 oz", "oz", "total", 12),              # 5 franks, 12 oz in the pack
    ("6 ct / 24 fl oz", "fl_oz", "total", 24),
])
def test_count_rule_resolves_ambiguous_multipacks(size, unit, rule, expected):
    assert parse_pack_size(size, unit, count_rule=rule) == pytest.approx(expected)


@pytest.mark.parametrize("size,unit", [
    ("5 ct / 12 oz", "oz"),          # 5 franks totalling 12 oz, or 5 packs of 12 oz?
    ("4 ct / 14.5 oz", "oz"),
    ("12 ct / 12 fl oz", "fl_oz"),
])
def test_ambiguous_multipack_without_a_rule_is_refused(size, unit):
    assert parse_pack_size(size, unit) is None


def test_count_of_a_non_unit_word_is_not_a_multiplier():
    assert parse_pack_size("4 sticks / 16 oz", "oz") == 16


def test_sold_by_weight_is_per_pound():
    assert parse_pack_size("1 lb", "lb", sold_by="WEIGHT") == 1
    assert parse_pack_size(None, "oz", sold_by="WEIGHT") == 16


@pytest.mark.parametrize("size,unit", [
    ("16 oz", "fl_oz"),      # mass vs volume: never guess a density
    ("1 gal", "lb"),
    ("family size", "oz"),
    ("", "oz"),
    (None, "oz"),
    ("16 oz", "dozen"),
])
def test_refuses_to_guess(size, unit):
    assert parse_pack_size(size, unit) is None
