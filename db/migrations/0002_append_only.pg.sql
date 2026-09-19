-- observations is append-only. Revisions ship as a new method_version.
CREATE FUNCTION observations_append_only() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'observations is append-only: % is not allowed', TG_OP;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER observations_no_update BEFORE UPDATE ON observations
  FOR EACH ROW EXECUTE FUNCTION observations_append_only();
CREATE TRIGGER observations_no_delete BEFORE DELETE ON observations
  FOR EACH ROW EXECUTE FUNCTION observations_append_only();
CREATE TRIGGER observations_no_truncate BEFORE TRUNCATE ON observations
  FOR EACH STATEMENT EXECUTE FUNCTION observations_append_only();
