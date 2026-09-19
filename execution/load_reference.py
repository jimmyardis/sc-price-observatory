"""Sync version-controlled reference config (geo, items, item_map) into the DB.

Config files are the source of truth; this makes the DB match them.
Items and mappings are never deleted from the DB (observations reference
them); removing one from config marks the item inactive.

    python -m execution.load_reference
"""
from __future__ import annotations

from execution import config


def run(db) -> dict:
    geo = config.geo()
    # parents before children for the FK
    order = {"state": 0, "region": 1, "county": 2}
    for g in sorted(geo, key=lambda g: order[g["geo_type"]]):
        db.upsert("geo", g, ["geo_id"])

    items = config.items()
    for i in items:
        db.upsert("items", {"item_id": i["item_id"], "domain": "grocery", "concept": i["concept"],
                            "label": i["label"], "cpi_stratum": i["cpi_stratum"], "norm_unit": i["norm_unit"],
                            "tier": i["tier"], "active": i["active"]}, ["item_id"])
    ids = {i["item_id"] for i in items}
    for r in db.query("SELECT item_id FROM items"):
        if r["item_id"] not in ids:
            db.execute("UPDATE items SET active = ? WHERE item_id = ?", (False, r["item_id"]))

    mapped = config.item_map()
    for m in mapped:
        db.upsert("item_map", {k: m[k] for k in ("banner", "retailer_sku", "item_id", "pack_size",
                                                 "count_rule", "confidence", "mapped_by", "mapped_at")},
                  ["banner", "retailer_sku"])
    db.commit()
    return {"geo": len(geo), "items": len(items), "item_map": len(mapped)}


if __name__ == "__main__":
    from execution.db import DB

    db = DB()
    db.migrate()
    print(run(db))
