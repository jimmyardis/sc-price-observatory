"""Load version-controlled config (config/*). The DB mirrors these; config wins."""
from __future__ import annotations

import csv
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config"
TMP = ROOT / ".tmp"


def collection() -> dict:
    return json.loads((CONFIG / "collection.json").read_text())


def geo() -> list[dict]:
    return json.loads((CONFIG / "geo_sc.json").read_text())["geo"]


def items() -> list[dict]:
    with open(CONFIG / "items.csv", newline="") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["active"] = r["active"].strip().lower() == "true"
    return rows


def item_map() -> list[dict]:
    with open(CONFIG / "item_map.csv", newline="") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["pack_size"] = float(r["pack_size"])
    return rows


def weights(cfg: dict | None = None) -> dict:
    cfg = cfg or collection()
    return json.loads((ROOT / cfg["weights_file"]).read_text())


def basket(cfg: dict | None = None) -> dict:
    cfg = cfg or collection()
    return json.loads((ROOT / cfg["basket_file"]).read_text())


def qa_overrides() -> list[dict]:
    return json.loads((CONFIG / "qa_overrides.json").read_text())["overrides"]


def load_env() -> None:
    """Populate os.environ from ./.env then ~/.env without overriding real env vars."""
    for path in (ROOT / ".env", Path.home() / ".env"):
        if not path.exists():
            continue
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.removeprefix("export ").strip()
            os.environ.setdefault(k, v.strip().strip('"').strip("'"))
