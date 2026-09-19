"""Build and check config/item_map.csv (retailer SKU -> our item).

Mapping is hand-curated. This script proposes candidates; a human picks.

    python -m execution.match_items propose --location 01400943   # -> .tmp/item_map_candidates.csv
    python -m execution.match_items check                         # validate config/item_map.csv

Workflow: run propose against one store in the target county, open the
candidates CSV, copy the right row per item into config/item_map.csv, set
confidence (exact | close | proxy), mapped_by, mapped_at. Commit it.
"""
from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from datetime import date

from execution import config
from execution.normalize_units import parse_pack_size

CONFIDENCE = {"exact", "close", "proxy"}
CANDIDATE_COLUMNS = ["item_id", "rank", "banner", "retailer_sku", "pack_size", "count_rule", "confidence",
                     "mapped_by", "mapped_at", "retailer_label", "brand", "size", "sold_by", "regular_price",
                     "unit_price", "why"]


def rank_candidates(item: dict, products: list[dict], store_brands: list[str], top: int = 5,
                    premium_brands: tuple[str, ...] = (), downrank_keywords: tuple[str, ...] = ()) -> list[dict]:
    """Score Kroger search results for one item. Higher is better.

    We want the ordinary version of each item: the mainline store brand or the
    named national brand, not an organic or premium subline. A premium substitute
    would measure a different market from the one the basket claims to price.
    """
    brands = {b.lower() for b in store_brands}
    premium = tuple(b.lower() for b in premium_brands)
    terms = [t for t in item["search_terms"].lower().split() if len(t) > 2]
    out = []
    for p in products:
        entry = (p.get("items") or [{}])[0]
        pack = parse_pack_size(entry.get("size"), item["norm_unit"], entry.get("soldBy"))
        ambiguous = pack is None and parse_pack_size(entry.get("size"), item["norm_unit"], entry.get("soldBy"),
                                                     count_rule="total") is not None
        if pack is None and not ambiguous:
            continue
        brand = (p.get("brand") or "").strip()
        desc = (p.get("description") or "").lower()
        score, why = 0.0, []
        hits = sum(t in desc for t in terms)
        score += 2 * hits / max(len(terms), 1)
        why.append(f"{hits}/{len(terms)} terms")
        hint = (item.get("brand_hint") or "").lower()
        blob = f"{brand} {desc}".lower()
        if item["tier"] == "store_brand" and brand.lower() in brands:
            score += 3
            why.append("store brand")
        elif item["tier"] == "national_brand" and hint and hint in blob:
            score += 3
            why.append("brand match")
        elif item["tier"] == "national_brand" and brand.lower() in brands:
            score -= 3
        if premium and item["tier"] != "national_brand" and any(b in blob for b in premium):
            score -= 1.5
            why.append("premium line")
        hit_words = [k for k in downrank_keywords if k in blob]
        if hit_words and not any(k in item["label"].lower() for k in hit_words):
            score -= 1.5 * len(hit_words)
            why.append("downranked: " + ", ".join(hit_words))
        if ambiguous:
            score -= 0.75
            why.append("AMBIGUOUS size: set count_rule (multiply|total)")
        price = (entry.get("price") or {}).get("regular")
        out.append({"item_id": item["item_id"], "banner": "kroger", "retailer_sku": p.get("productId"),
                    "pack_size": "" if pack is None else round(pack, 4), "count_rule": "", "confidence": "",
                    "mapped_by": "", "mapped_at": "",
                    "retailer_label": p.get("description"), "brand": brand, "size": entry.get("size"),
                    "sold_by": entry.get("soldBy"), "regular_price": price,
                    "unit_price": round(price / pack, 4) if price and pack else None,
                    "why": "; ".join(why), "_score": score})
    out.sort(key=lambda c: -c["_score"])
    for n, c in enumerate(out[:top], 1):
        c["rank"] = n
        del c["_score"]
    return out[:top]


def propose(api, location_id: str) -> str:
    cfg = config.collection()
    rows = []
    for item in config.items():
        if item["active"]:
            rows += rank_candidates(item, api.search(item["search_terms"], location_id),
                                    cfg["kroger"]["store_brands"],
                                    premium_brands=tuple(cfg["kroger"].get("store_brands_premium", [])),
                                    downrank_keywords=tuple(cfg["kroger"].get("downrank_keywords", [])))
    path = config.TMP / "item_map_candidates.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CANDIDATE_COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    return str(path)


def check(item_map: list[dict], items: list[dict], min_banners: int = 4) -> tuple[list[str], list[str]]:
    """Return (errors, warnings)."""
    by_id = {i["item_id"]: i for i in items}
    errors, warnings = [], []
    seen = set()
    for n, m in enumerate(item_map, 2):
        key = (m["banner"], m["retailer_sku"])
        if key in seen:
            errors.append(f"line {n}: duplicate {key}")
        seen.add(key)
        if m["item_id"] not in by_id:
            errors.append(f"line {n}: unknown item_id {m['item_id']}")
        if m["confidence"] not in CONFIDENCE:
            errors.append(f"line {n}: confidence must be one of {sorted(CONFIDENCE)}")
        if not m["pack_size"] or float(m["pack_size"]) <= 0:
            errors.append(f"line {n}: pack_size must be > 0")
        if m.get("count_rule") and m["count_rule"] not in ("multiply", "total"):
            errors.append(f"line {n}: count_rule must be blank, 'multiply', or 'total'")
        try:
            date.fromisoformat(m["mapped_at"])
        except (TypeError, ValueError):
            errors.append(f"line {n}: mapped_at must be YYYY-MM-DD")
        if not m.get("mapped_by"):
            errors.append(f"line {n}: mapped_by is required")
    banners = defaultdict(set)
    for m in item_map:
        banners[m["item_id"]].add(m["banner"])
    active = [i for i in items if i["active"]]
    unmapped = [i["item_id"] for i in active if i["item_id"] not in banners]
    if unmapped:
        warnings.append(f"{len(unmapped)} active items unmapped: {', '.join(unmapped[:10])}{'...' if len(unmapped) > 10 else ''}")
    thin = [i["item_id"] for i in active if 0 < len(banners[i["item_id"]]) < min_banners]
    if thin:
        warnings.append(f"{len(thin)} items mapped at fewer than {min_banners} banners (spec rule; expected in Phase 0)")
    return errors, warnings


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("propose")
    p.add_argument("--location", required=True, help="Kroger locationId of a reference store")
    sub.add_parser("check")
    args = ap.parse_args()
    if args.cmd == "propose":
        from execution.collectors.kroger import KrogerAPI

        cfg = config.collection()
        print(propose(KrogerAPI.from_env(min_interval=cfg["kroger"]["min_seconds_between_requests"]), args.location))
    else:
        with open(config.CONFIG / "item_map.csv", newline="") as f:
            raw = list(csv.DictReader(f))
        errs, warns = check(raw, config.items())
        for w in warns:
            print("WARN ", w)
        for e in errs:
            print("ERROR", e)
        print(f"{len(raw)} mappings, {len(errs)} errors")
        sys.exit(1 if errs else 0)
