from execution.match_items import check, rank_candidates

ITEM = {"item_id": "peanut_butter_store", "tier": "store_brand", "norm_unit": "oz",
        "search_terms": "creamy peanut butter", "brand_hint": "", "active": True}


def product(pid, brand, desc, size, price):
    return {"productId": pid, "brand": brand, "description": desc,
            "items": [{"size": size, "soldBy": "UNIT", "price": {"regular": price}}]}


def test_rank_prefers_store_brand_and_skips_unparseable():
    ranked = rank_candidates(ITEM, [
        product("1", "Jif", "Jif Creamy Peanut Butter", "16 oz", 3.5),
        product("2", "Kroger", "Kroger Creamy Peanut Butter", "16 oz", 2.2),
        product("3", "Kroger", "Kroger Creamy Peanut Butter Variety", "family size", 5.0),
    ], ["Kroger"])
    assert [c["retailer_sku"] for c in ranked] == ["2", "1"]
    assert ranked[0]["pack_size"] == 16 and ranked[0]["confidence"] == ""


def test_check_flags_bad_rows_and_unmapped_items():
    items = [ITEM, {**ITEM, "item_id": "jif"}]
    rows = [
        {"banner": "kroger", "retailer_sku": "2", "item_id": "peanut_butter_store", "pack_size": "16",
         "confidence": "exact", "mapped_by": "jd", "mapped_at": "2026-09-16"},
        {"banner": "kroger", "retailer_sku": "2", "item_id": "nope", "pack_size": "0",
         "confidence": "maybe", "mapped_by": "", "mapped_at": "soon"},
    ]
    errors, warnings = check(rows, items)
    assert len(errors) == 6
    assert any("unmapped: jif" in w for w in warnings)
