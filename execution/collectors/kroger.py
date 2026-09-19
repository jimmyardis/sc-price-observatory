"""Kroger Developer API collector (covers Kroger and Harris Teeter stores).

Licensed, documented API: https://developer.kroger.com
Needs KROGER_CLIENT_ID / KROGER_CLIENT_SECRET (in .env). Scope: product.compact.

    python -m execution.collectors.kroger discover        # find SC stores, assign counties
    python -m execution.collectors.kroger collect         # one weekly collection pass
"""
from __future__ import annotations

import argparse
import base64
import json
import logging
import os
import time
from datetime import date, datetime, timezone

import requests

from execution import config
from execution.collectors._base import (PoliteClient, insert_observations, log_problem, save_payload,
                                        week_of)
from execution.normalize_units import parse_pack_size

API = "https://api.kroger.com/v1"
MAP_BANNER = "kroger"   # item_map family: Kroger-family chains share UPC product ids
CHAIN_BANNER = {"KROGER": "kroger", "HART": "harris_teeter", "HARRIS TEETER": "harris_teeter",
                "HARRISTEETER": "harris_teeter"}
log = logging.getLogger("kroger")


class KrogerAPI:
    def __init__(self, client_id: str, client_secret: str, min_interval: float = 0.5,
                 session: requests.Session | None = None, sleep=time.sleep):
        self.http = PoliteClient("kroger", min_interval=min_interval, session=session, sleep=sleep)
        self._auth = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
        self._token, self._expires = None, 0.0

    @classmethod
    def from_env(cls, **kw) -> "KrogerAPI":
        config.load_env()
        cid, secret = os.environ.get("KROGER_CLIENT_ID"), os.environ.get("KROGER_CLIENT_SECRET")
        if not cid or not secret:
            raise SystemExit("KROGER_CLIENT_ID / KROGER_CLIENT_SECRET not set. Register an app at "
                             "https://developer.kroger.com (Production, scope product.compact) and add them to .env")
        return cls(cid, secret, **kw)

    def _headers(self) -> dict:
        if not self._token or time.time() > self._expires - 60:
            r = self.http.request("POST", f"{API}/connect/oauth2/token",
                                  headers={"Authorization": f"Basic {self._auth}",
                                           "Content-Type": "application/x-www-form-urlencoded"},
                                  data={"grant_type": "client_credentials", "scope": "product.compact"})
            tok = r.json()
            self._token, self._expires = tok["access_token"], time.time() + int(tok.get("expires_in", 1800))
        return {"Authorization": f"Bearer {self._token}", "Accept": "application/json"}

    def get(self, path: str, params: dict) -> tuple[dict, str]:
        r = self.http.request("GET", f"{API}{path}", headers=self._headers(), params=params)
        return r.json(), save_payload("kroger", r.content)

    def locations_near(self, lat: float, lon: float, radius: int) -> list[dict]:
        data, _ = self.get("/locations", {"filter.latLong.near": f"{lat},{lon}",
                                          "filter.radiusInMiles": radius, "filter.limit": 200})
        return data.get("data", [])

    def products_by_id(self, location_id: str, product_ids: list[str]) -> tuple[dict, str]:
        return self.get("/products", {"filter.productId": ",".join(product_ids),
                                      "filter.locationId": location_id, "filter.limit": 50})

    def search(self, term: str, location_id: str, limit: int = 50) -> list[dict]:
        data, _ = self.get("/products", {"filter.term": term, "filter.locationId": location_id,
                                         "filter.limit": limit})
        return data.get("data", [])


# --- store discovery ---------------------------------------------------------

def county_fips(lat: float, lon: float, session=requests) -> str | None:
    """County FIPS from coordinates via the FCC Area API, cached in .tmp/."""
    cache_path = config.TMP / "county_cache.json"
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    key = f"{lat:.5f},{lon:.5f}"
    if key not in cache:
        r = session.get("https://geo.fcc.gov/api/census/area",
                        params={"lat": lat, "lon": lon, "format": "json"}, timeout=30)
        r.raise_for_status()
        results = r.json().get("results") or [{}]
        cache[key] = results[0].get("county_fips")
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(cache))
    return cache[key]


NON_GROCERY_DEPARTMENTS = {"gas station", "lottery tickets", "tobacco", "atm", "car wash"}


def is_grocery_store(loc: dict) -> bool:
    """Fuel centers are separate locations with their own locationId. They stock no
    groceries, so including them would look like a store that never carries anything."""
    if "fuel" in str(loc.get("name", "")).lower():
        return False
    depts = [str(d.get("name", "")).lower() for d in (loc.get("departments") or [])]
    return not (depts and all(d in NON_GROCERY_DEPARTMENTS for d in depts))


def parse_location(loc: dict) -> dict | None:
    addr = loc.get("address") or {}
    banner = CHAIN_BANNER.get(str(loc.get("chain", "")).upper())
    if addr.get("state") != "SC":
        return None
    if not banner:
        log_problem("unknown_kroger_chain", {"chain": loc.get("chain"), "locationId": loc.get("locationId")})
        return None
    if not is_grocery_store(loc):
        return None
    geo = loc.get("geolocation") or {}
    return {
        "store_id": f"{banner}:{loc['locationId']}",
        "banner": banner,
        "retailer_num": loc["locationId"],
        "name": loc.get("name"),
        "lat": geo.get("latitude"), "lon": geo.get("longitude"),
        "address": ", ".join(x for x in (addr.get("addressLine1"), addr.get("city"), addr.get("zipCode")) if x),
    }


def discover(db, api: KrogerAPI, cfg: dict, fips_lookup=county_fips) -> list[dict]:
    kc = cfg["kroger"]
    seen: dict[str, dict] = {}
    for lat, lon in kc["discovery_points"]:
        for loc in api.locations_near(lat, lon, kc["discovery_radius_miles"]):
            s = parse_location(loc)
            if s:
                seen[s["store_id"]] = s
    today = date.today().isoformat()
    known_geos = {g["geo_id"] for g in config.geo()}
    for s in seen.values():
        fips = fips_lookup(s["lat"], s["lon"]) if s["lat"] is not None else None
        if fips and fips not in known_geos:
            log_problem("store_outside_known_geos", {"store_id": s["store_id"], "county_fips": fips,
                                                     "address": s["address"]})
            fips = None
        s["geo_id"] = fips
        existing = db.query("SELECT first_seen FROM stores WHERE store_id = ?", (s["store_id"],))
        db.upsert("stores", {**s, "active": True,
                             "first_seen": existing[0]["first_seen"] if existing else today,
                             "last_seen": today}, ["store_id"])
    db.commit()
    return list(seen.values())


# --- collection --------------------------------------------------------------

def parse_products(payload: dict, mapping: dict[str, dict], items: dict[str, dict], *, store_id: str,
                   week: date, collected_at: str, payload_hash: str) -> list[dict]:
    """Kroger /products response -> observation rows (shelf, plus promo when on sale)."""
    rows = []
    for product in payload.get("data", []):
        sku = product.get("productId")
        m = mapping.get(sku)
        if not m:
            continue
        item = items[m["item_id"]]
        entry = (product.get("items") or [{}])[0]
        price = entry.get("price") or {}
        regular, promo = float(price.get("regular") or 0), float(price.get("promo") or 0)
        if regular <= 0:
            continue  # not priced at this store this week -> treated as missing
        pack = parse_pack_size(entry.get("size"), item["norm_unit"], entry.get("soldBy"),
                               count_rule=m.get("count_rule") or None)
        label = product.get("description", "")
        if not pack:
            log_problem("unparseable_size", {"store_id": store_id, "sku": sku, "size": entry.get("size"),
                                             "sold_by": entry.get("soldBy"), "item_id": item["item_id"]})
            continue
        if abs(pack - m["pack_size"]) / m["pack_size"] > 0.01:
            log_problem("pack_size_changed", {"store_id": store_id, "sku": sku, "item_id": item["item_id"],
                                              "mapped": m["pack_size"], "observed": pack, "week": week.isoformat()})
        base = {"collected_at": collected_at, "week": week.isoformat(), "store_id": store_id,
                "item_id": item["item_id"], "raw_sku": sku, "raw_label": label, "pack_size": pack,
                "source": "api", "payload_hash": payload_hash}
        rows.append({**base, "price": regular, "unit_price": regular / pack, "price_type": "shelf"})
        if 0 < promo < regular:
            rows.append({**base, "price": promo, "unit_price": promo / pack, "price_type": "promo"})
    return rows


def collect(db, api: KrogerAPI, cfg: dict, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    week = week_of(now, cfg["timezone"])
    items = {i["item_id"]: i for i in config.items() if i["active"]}
    mapping = {m["retailer_sku"]: m for m in config.item_map()
               if m["banner"] == MAP_BANNER and m["item_id"] in items}
    if not mapping:
        raise SystemExit("config/item_map.csv has no kroger rows. Run `python -m execution.match_items propose` "
                         "and curate the candidates first.")
    banners = [b for b in cfg["banners"] if b in set(CHAIN_BANNER.values())]
    marks = ",".join("?" for _ in cfg["counties"])
    bmarks = ",".join("?" for _ in banners)
    stores = db.query(f"SELECT store_id, retailer_num FROM stores WHERE active AND geo_id IN ({marks}) "
                      f"AND banner IN ({bmarks}) ORDER BY store_id", (*cfg["counties"], *banners))
    skus = sorted(mapping)
    summary = {"week": week.isoformat(), "stores": len(stores), "observations": 0, "store_errors": []}
    for s in stores:
        rows = []
        for i in range(0, len(skus), 50):
            payload, h = api.products_by_id(s["retailer_num"], skus[i:i + 50])
            rows += parse_products(payload, mapping, items, store_id=s["store_id"], week=week,
                                   collected_at=now.isoformat(), payload_hash=h)
        summary["observations"] += insert_observations(db, rows)
        log.info("%s: %d observations", s["store_id"], len(rows))
    return summary


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["discover", "collect"])
    args = ap.parse_args()
    from execution.db import DB

    db, cfg = DB(), config.collection()
    db.migrate()
    from execution import load_reference
    load_reference.run(db)          # geo rows must exist before stores reference them
    api = KrogerAPI.from_env(min_interval=cfg["kroger"]["min_seconds_between_requests"])
    if args.command == "discover":
        stores = discover(db, api, cfg)
        by_county: dict[str, int] = {}
        for s in stores:
            by_county[s["geo_id"]] = by_county.get(s["geo_id"], 0) + 1
        print(json.dumps({"sc_stores": len(stores), "by_county": by_county}, indent=1))
    else:
        print(json.dumps(collect(db, api, cfg), indent=1))


if __name__ == "__main__":
    main()
