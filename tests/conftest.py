import pytest

from execution import config, export_snapshot, qa_checks
from execution.collectors import _base
from execution.db import DB


@pytest.fixture
def tmp_dirs(tmp_path, monkeypatch):
    tmp = tmp_path / ".tmp"
    snaps = tmp_path / "snapshots"
    for mod in (config, _base, qa_checks, export_snapshot):
        monkeypatch.setattr(mod, "TMP", tmp, raising=False)
    monkeypatch.setattr(export_snapshot, "SNAPSHOTS", snaps)
    return tmp, snaps


@pytest.fixture
def db(tmp_path, tmp_dirs):
    d = DB(f"sqlite:///{tmp_path / 'test.db'}")
    d.migrate()
    yield d
    d.close()
