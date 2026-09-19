"""Shared collector plumbing: polite HTTP, raw payload storage, week keys, alerts.

Politeness defaults: minimum spacing between requests, honest user agent,
exponential backoff on 5xx/timeouts, HARD STOP on 429/403 with an alert file.
A blocked collector must never retry its way past a block.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import requests

from execution.config import TMP

USER_AGENT = "sc-price-observatory/0.1 (public price research; weekly collection)"
log = logging.getLogger("collector")


class CollectorBlocked(RuntimeError):
    """Raised on 429/403. Collection for this banner stops for the run."""


class PoliteClient:
    def __init__(self, banner: str, min_interval: float = 60.0, max_retries: int = 5,
                 session: requests.Session | None = None, sleep=time.sleep):
        self.banner = banner
        self.min_interval = min_interval
        self.max_retries = max_retries
        self.session = session or requests.Session()
        self.session.headers.setdefault("User-Agent", USER_AGENT)
        self._sleep = sleep
        self._last = 0.0

    def request(self, method: str, url: str, **kw) -> requests.Response:
        for attempt in range(self.max_retries + 1):
            wait = self.min_interval - (time.monotonic() - self._last)
            if wait > 0:
                self._sleep(wait)
            self._last = time.monotonic()
            try:
                resp = self.session.request(method, url, timeout=30, **kw)
            except (requests.ConnectionError, requests.Timeout) as e:
                if attempt == self.max_retries:
                    raise
                log.warning("%s %s failed (%s); backing off", self.banner, url, e)
                self._sleep(min(2 ** attempt * 5, 300))
                continue
            if resp.status_code in (403, 429):
                alert(self.banner, f"HTTP {resp.status_code} from {url}", resp.text[:500])
                raise CollectorBlocked(f"{self.banner}: HTTP {resp.status_code} — hard stop")
            if resp.status_code >= 500 and attempt < self.max_retries:
                self._sleep(min(2 ** attempt * 5, 300))
                continue
            resp.raise_for_status()
            return resp
        raise RuntimeError("unreachable")


def save_payload(banner: str, body: bytes) -> str:
    """Store a raw response under .tmp/raw/ keyed by sha256; return the hash."""
    h = hashlib.sha256(body).hexdigest()
    path = TMP / "raw" / banner / h[:2] / f"{h}.json"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
    return h


def week_of(ts: datetime, tz: str = "America/New_York") -> date:
    local = ts.astimezone(ZoneInfo(tz)).date()
    return local - timedelta(days=local.weekday())


def alert(banner: str, message: str, detail: str = "") -> None:
    d = TMP / "alerts"
    d.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    (d / f"{banner}_{stamp}.json").write_text(json.dumps({"banner": banner, "message": message, "detail": detail}, indent=1))
    log.error("ALERT %s: %s", banner, message)


def log_problem(kind: str, record: dict) -> None:
    path = TMP / "problems.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps({"kind": kind, "at": datetime.now().isoformat(), **record}) + "\n")


OBS_COLUMNS = ["collected_at", "week", "store_id", "item_id", "raw_sku", "raw_label", "price",
               "pack_size", "unit_price", "price_type", "source", "payload_hash"]


def insert_observations(db, rows: list[dict]) -> int:
    if rows:
        db.executemany(
            f"INSERT INTO observations ({', '.join(OBS_COLUMNS)}) VALUES ({', '.join('?' for _ in OBS_COLUMNS)})",
            [[r[c] for c in OBS_COLUMNS] for r in rows])
        db.commit()
    return len(rows)
