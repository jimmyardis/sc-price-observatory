"""Database access. One interface over SQLite (Phase 0) and Postgres (Phase 1+).

DATABASE_URL=postgresql://...  -> Postgres via psycopg
DATABASE_URL unset or sqlite:///path -> SQLite (default data/observatory.db)

SQL is written with `?` placeholders; they are translated for psycopg.
"""
from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS = ROOT / "db" / "migrations"
DEFAULT_SQLITE = ROOT / "data" / "observatory.db"


class DB:
    def __init__(self, url: str | None = None):
        url = url or os.environ.get("DATABASE_URL") or f"sqlite:///{DEFAULT_SQLITE}"
        self.url = url
        if url.startswith(("postgres://", "postgresql://")):
            import psycopg

            self.dialect = "postgres"
            self.conn = psycopg.connect(url)
        elif url.startswith("sqlite:///"):
            path = url[len("sqlite:///"):]
            if path != ":memory:":
                Path(path).parent.mkdir(parents=True, exist_ok=True)
            self.dialect = "sqlite"
            self.conn = sqlite3.connect(path)
            self.conn.execute("PRAGMA foreign_keys = ON")
        else:
            raise ValueError(f"Unsupported DATABASE_URL: {url}")

    def _sql(self, sql: str) -> str:
        return sql.replace("?", "%s") if self.dialect == "postgres" else sql

    def execute(self, sql: str, params=()):
        cur = self.conn.cursor()
        if params:
            cur.execute(self._sql(sql), params)
        else:
            cur.execute(sql)
        return cur

    def executemany(self, sql: str, rows):
        cur = self.conn.cursor()
        cur.executemany(self._sql(sql), rows)
        return cur

    def query(self, sql: str, params=()) -> list[dict]:
        cur = self.execute(sql, params)
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]

    def commit(self):
        self.conn.commit()

    def close(self):
        self.conn.close()

    def upsert(self, table: str, row: dict, key: list[str]):
        cols = list(row)
        updates = [c for c in cols if c not in key]
        set_clause = ", ".join(f"{c} = excluded.{c}" for c in updates) or None
        sql = (
            f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)}) "
            f"ON CONFLICT ({', '.join(key)}) "
            + (f"DO UPDATE SET {set_clause}" if set_clause else "DO NOTHING")
        )
        self.execute(sql, [row[c] for c in cols])

    # --- migrations -------------------------------------------------------

    def migrate(self) -> list[str]:
        self.execute("CREATE TABLE IF NOT EXISTS schema_migrations (name TEXT PRIMARY KEY)")
        done = {r["name"] for r in self.query("SELECT name FROM schema_migrations")}
        other = "sqlite" if self.dialect == "postgres" else "pg"
        applied = []
        for f in sorted(MIGRATIONS.glob("*.sql")):
            if f.name.endswith(f".{other}.sql") or f.name in done:
                continue
            sql = f.read_text()
            if self.dialect == "sqlite":
                self.conn.executescript(_to_sqlite(sql))
            else:
                self.conn.execute(sql)  # no params -> simple protocol, multi-statement OK
            self.execute("INSERT INTO schema_migrations (name) VALUES (?)", (f.name,))
            self.commit()
            applied.append(f.name)
        return applied


def _to_sqlite(sql: str) -> str:
    sql = re.sub(r"BIGSERIAL PRIMARY KEY", "INTEGER PRIMARY KEY AUTOINCREMENT", sql)
    sql = sql.replace("TIMESTAMPTZ", "TEXT")
    return sql
