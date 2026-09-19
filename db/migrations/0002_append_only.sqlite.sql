-- observations is append-only. Revisions ship as a new method_version.
CREATE TRIGGER observations_no_update BEFORE UPDATE ON observations
BEGIN
  SELECT RAISE(ABORT, 'observations is append-only: UPDATE is not allowed');
END;

CREATE TRIGGER observations_no_delete BEFORE DELETE ON observations
BEGIN
  SELECT RAISE(ABORT, 'observations is append-only: DELETE is not allowed');
END;
