-- Store name as the retailer shows it ("Harris Teeter - Nexton"): needed for the
-- coverage page and for telling two locations at one address apart.
ALTER TABLE stores ADD COLUMN name TEXT;
