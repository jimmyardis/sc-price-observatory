"""Parse retailer size strings into a pack size in an item's norm_unit.

    parse_pack_size("1 gal", "fl_oz")       -> 128.0
    parse_pack_size("6 ct / 12 fl oz", "fl_oz") -> 72.0
    parse_pack_size("18 ct", "dozen")       -> 1.5

Returns None when the size cannot be expressed in the target unit. Callers must
skip (and log) such observations; pack size is never assumed.
"""
from __future__ import annotations

import re

NORM_UNITS = {"lb", "oz", "fl_oz", "count", "dozen"}

# unit token -> (dimension, amount in the dimension's base unit)
# base units: mass = oz, volume = fl_oz, count = count
_UNITS = {
    "lb": ("mass", 16.0), "lbs": ("mass", 16.0), "pound": ("mass", 16.0), "pounds": ("mass", 16.0),
    "oz": ("mass", 1.0), "ounce": ("mass", 1.0), "ounces": ("mass", 1.0),
    "g": ("mass", 1 / 28.349523125), "gram": ("mass", 1 / 28.349523125), "grams": ("mass", 1 / 28.349523125),
    "kg": ("mass", 1000 / 28.349523125),
    "fl oz": ("volume", 1.0), "fl. oz": ("volume", 1.0), "fl.oz": ("volume", 1.0), "floz": ("volume", 1.0),
    "fluid ounce": ("volume", 1.0), "fluid ounces": ("volume", 1.0),
    "gal": ("volume", 128.0), "gallon": ("volume", 128.0), "gallons": ("volume", 128.0),
    "qt": ("volume", 32.0), "quart": ("volume", 32.0), "quarts": ("volume", 32.0),
    "pt": ("volume", 16.0), "pint": ("volume", 16.0), "pints": ("volume", 16.0),
    "l": ("volume", 33.814022701843), "liter": ("volume", 33.814022701843), "liters": ("volume", 33.814022701843),
    "litre": ("volume", 33.814022701843), "ml": ("volume", 0.033814022701843),
    "ct": ("count", 1.0), "count": ("count", 1.0), "each": ("count", 1.0), "ea": ("count", 1.0),
    "pk": ("count", 1.0), "pack": ("count", 1.0),
    "dozen": ("count", 12.0), "dz": ("count", 12.0),
}

_TARGET = {"lb": ("mass", 16.0), "oz": ("mass", 1.0), "fl_oz": ("volume", 1.0),
           "count": ("count", 1.0), "dozen": ("count", 12.0)}

_UNIT_RE = "|".join(sorted((re.escape(u) for u in _UNITS), key=len, reverse=True))
_QTY = r"(\d+(?:\.\d+)?|\d*\.\d+|\d+\s*/\s*\d+)"
_TERM_RE = re.compile(rf"{_QTY}\s*({_UNIT_RE})\b\.?", re.IGNORECASE)


def _num(s: str) -> float:
    s = s.replace(" ", "")
    if "/" in s:
        a, b = s.split("/")
        return float(a) / float(b)
    return float(s)


def _terms(text: str) -> list[tuple[str, float]]:
    """All (dimension, amount_in_base) terms in order of appearance."""
    out = []
    for m in _TERM_RE.finditer(text):
        dim, factor = _UNITS[m.group(2).lower()]
        out.append((dim, _num(m.group(1)) * factor))
    return out


def parse_pack_size(size: str | None, norm_unit: str, sold_by: str | None = None,
                    count_rule: str | None = None) -> float | None:
    """`count_rule` resolves sizes like "5 ct / 12 oz", which retailers use for both
    "5 franks weighing 12 oz total" (rule 'total') and "4 cans of 14.5 oz each"
    (rule 'multiply'). The string cannot tell them apart, so without a rule we
    return None rather than guess: a wrong reading is a 4-5x error in the level.
    The rule is curated once per SKU in config/item_map.csv."""
    if norm_unit not in NORM_UNITS:
        raise ValueError(f"unknown norm_unit {norm_unit!r}")
    target_dim, target_factor = _TARGET[norm_unit]

    # Random-weight produce/meat priced per pound: the price IS the unit price.
    if sold_by and sold_by.upper() == "WEIGHT":
        return 1.0 * 16.0 / target_factor if target_dim == "mass" else None

    if not size:
        return None
    text = size.strip().lower().replace("×", "x")
    text = re.sub(r"(\d),(\d)", r"\1\2", text)
    terms = _terms(text)
    if not terms:
        return None

    counts = [a for d, a in terms if d == "count"]
    measures = [a for d, a in terms if d == target_dim and d != "count"]

    if target_dim == "count":
        # "18 ct" or "1 dozen"; a lone count term is the pack.
        return counts[0] / target_factor if counts else None

    if not measures:
        return None
    # "2 x 16 oz" states the multiplication explicitly.
    mult = re.search(r"(\d+(?:\.\d+)?)\s*x\s*\d", text)
    if mult and not counts:
        return float(mult.group(1)) * measures[0] / target_factor
    if counts:
        if count_rule == "multiply":
            return counts[0] * measures[0] / target_factor
        if count_rule == "total":
            return measures[0] / target_factor
        return None        # ambiguous; needs a curated count_rule
    return measures[0] / target_factor
