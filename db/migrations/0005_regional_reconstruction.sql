-- Reference series (BLS average prices, CPI) stored exactly as published, and the
-- regional reconstruction built from them: "regional prices, local wages".
-- Kept apart from observations on purpose. Nothing here is a measured SC price.

CREATE TABLE reference_series (
  series_id   TEXT PRIMARY KEY,          -- BLS id, e.g. APU0300709112
  source      TEXT NOT NULL,             -- 'BLS API'
  fetched_at  TIMESTAMPTZ
);

CREATE TABLE reference_values (
  series_id    TEXT NOT NULL,
  period       DATE NOT NULL,            -- first day of the month (or quarter)
  value        NUMERIC NOT NULL,         -- as published; unpublished months are absent, never zero
  footnotes    TEXT,
  payload_hash TEXT NOT NULL,            -- sha256 of the raw API response in .tmp/raw/bls/
  PRIMARY KEY (series_id, period)
);

-- Derived. Regenerable from reference_values + wages + the regional method_version.
CREATE TABLE regional_basket_costs (
  month          DATE NOT NULL,
  cost           NUMERIC,                -- NULL when a concept is unpriced even after imputation
  n_concepts     INT,
  n_imputed      INT,                    -- concepts without a published South price this month
  imputed_share  NUMERIC,                -- share of cost from imputed prices
  status         TEXT NOT NULL,          -- published | suppressed | no_data
  method_version TEXT NOT NULL,
  computed_at    TIMESTAMPTZ NOT NULL,
  PRIMARY KEY (month, method_version)
);

CREATE TABLE regional_time_prices (
  geo_id            TEXT NOT NULL,
  month             DATE NOT NULL,
  basket_cost       NUMERIC,
  avg_weekly_wage   NUMERIC,
  wage_is_projected BOOLEAN,
  hours_to_basket   NUMERIC,
  status            TEXT NOT NULL,       -- inherits the basket month's status; no_data without a wage
  method_version    TEXT NOT NULL,
  computed_at       TIMESTAMPTZ NOT NULL,
  PRIMARY KEY (geo_id, month, method_version)
);
