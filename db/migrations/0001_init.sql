-- Price observatory core schema. Written in Postgres dialect; execution/db.py
-- translates the few differences for SQLite (Phase 0 only).
-- Generic across domains: grocery today, rent/electricity/fuel/insurance later.

CREATE TABLE geo (
  geo_id        TEXT PRIMARY KEY,     -- FIPS for counties: '45079'; 'SC' for state; 'region:midlands'
  geo_type      TEXT NOT NULL,        -- county | region | state
  name          TEXT NOT NULL,
  parent_geo_id TEXT REFERENCES geo(geo_id)
);

CREATE TABLE stores (
  store_id      TEXT PRIMARY KEY,     -- '{banner}:{retailer_store_num}'
  banner        TEXT NOT NULL,        -- kroger | harris_teeter | publix | food_lion | aldi | walmart
  retailer_num  TEXT NOT NULL,
  geo_id        TEXT REFERENCES geo(geo_id),
  lat NUMERIC, lon NUMERIC,
  address       TEXT,
  active        BOOLEAN DEFAULT TRUE,
  first_seen    DATE, last_seen DATE
);

CREATE TABLE items (
  item_id       TEXT PRIMARY KEY,     -- stable id, e.g. 'milk_whole_gal_store'
  domain        TEXT NOT NULL DEFAULT 'grocery',
  concept       TEXT NOT NULL,        -- the thing a basket buys; tier variants share a concept
  label         TEXT NOT NULL,
  cpi_stratum   TEXT NOT NULL,        -- BLS item stratum, see config/weights_*.json
  norm_unit     TEXT NOT NULL,        -- lb | oz | fl_oz | count | dozen
  tier          TEXT NOT NULL,        -- store_brand | national_brand | unbranded
  active        BOOLEAN DEFAULT TRUE
);

-- Maps a retailer SKU to our item. Source of truth is config/item_map.csv.
CREATE TABLE item_map (
  banner        TEXT NOT NULL,        -- mapping family: 'kroger' covers Kroger + Harris Teeter (shared UPCs)
  retailer_sku  TEXT NOT NULL,
  item_id       TEXT NOT NULL REFERENCES items(item_id),
  pack_size     NUMERIC NOT NULL,     -- in norm_unit, as seen at mapping time
  confidence    TEXT NOT NULL,        -- exact | close | proxy
  mapped_by     TEXT, mapped_at DATE,
  PRIMARY KEY (banner, retailer_sku)
);

-- APPEND ONLY. Never UPDATE, never DELETE. Enforced by triggers in 0002.
CREATE TABLE observations (
  obs_id        BIGSERIAL PRIMARY KEY,
  collected_at  TIMESTAMPTZ NOT NULL,
  week          DATE NOT NULL,        -- Monday of collection week
  store_id      TEXT NOT NULL REFERENCES stores(store_id),
  item_id       TEXT NOT NULL REFERENCES items(item_id),
  raw_sku       TEXT NOT NULL,
  raw_label     TEXT NOT NULL,
  price         NUMERIC NOT NULL,     -- as advertised, total for the pack
  pack_size     NUMERIC NOT NULL,     -- parsed from THIS observation, never assumed
  unit_price    NUMERIC NOT NULL,     -- price / pack_size, in norm_unit
  price_type    TEXT NOT NULL,        -- shelf | promo | member | unknown
  source        TEXT NOT NULL,        -- api | web | circular
  payload_hash  TEXT NOT NULL         -- sha256 of raw blob in .tmp/raw/
);
CREATE INDEX observations_week_idx ON observations (week);
CREATE INDEX observations_store_item_idx ON observations (store_id, item_id, week);

-- Derived. Regenerable from observations + method_version.
CREATE TABLE index_values (
  geo_id TEXT NOT NULL, week DATE NOT NULL,
  stratum TEXT NOT NULL,                  -- 'ALL' = headline
  series TEXT NOT NULL,                   -- shelf (headline) | promo_incl
  index_value NUMERIC,
  basket_cost NUMERIC,                    -- 'ALL' rows only: standard weekly basket, dollars
  n_obs INT, n_stores INT, n_banners INT,
  imputed_share NUMERIC,
  base_status TEXT,                       -- provisional | final
  method_version TEXT NOT NULL,
  computed_at TIMESTAMPTZ NOT NULL,
  PRIMARY KEY (geo_id, week, stratum, series, method_version)
);

CREATE TABLE basket_costs (
  geo_id TEXT NOT NULL, week DATE NOT NULL,
  series TEXT NOT NULL,
  basket TEXT NOT NULL,                   -- standard (store brand/unbranded) | national
  cost NUMERIC,                           -- NULL when any concept is unpriced
  n_concepts INT, n_missing INT,
  method_version TEXT NOT NULL,
  computed_at TIMESTAMPTZ NOT NULL,
  PRIMARY KEY (geo_id, week, series, basket, method_version)
);

CREATE TABLE wages (
  geo_id TEXT NOT NULL, quarter DATE NOT NULL,   -- first day of quarter
  avg_weekly_wage NUMERIC,
  total_qtrly_wages NUMERIC, avg_employment NUMERIC,
  source TEXT DEFAULT 'QCEW',
  PRIMARY KEY (geo_id, quarter)
);

CREATE TABLE time_prices (
  geo_id TEXT NOT NULL, week DATE NOT NULL,
  series TEXT NOT NULL,
  basket_cost NUMERIC, avg_weekly_wage NUMERIC,
  hours_to_basket NUMERIC,
  wage_is_projected BOOLEAN,
  method_version TEXT NOT NULL,
  computed_at TIMESTAMPTZ NOT NULL,
  PRIMARY KEY (geo_id, week, series, method_version)
);
