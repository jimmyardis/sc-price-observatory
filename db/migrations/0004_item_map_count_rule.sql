-- Resolves ambiguous "N ct / M oz" sizes per SKU: 'multiply' (N packs of M) or
-- 'total' (N pieces, M is the pack). See execution/normalize_units.py.
ALTER TABLE item_map ADD COLUMN count_rule TEXT;
