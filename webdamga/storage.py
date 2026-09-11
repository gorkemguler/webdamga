"""Yakalama indeksini tutan küçük SQLite deposu (stdlib sqlite3)."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS captures (
    id              TEXT PRIMARY KEY,
    requested_url   TEXT NOT NULL,
    final_url       TEXT,
    http_status     INTEGER,
    page_title      TEXT,
    created_utc     TEXT NOT NULL,
    dir             TEXT NOT NULL,
    manifest_sha256 TEXT,
    ok              INTEGER NOT NULL DEFAULT 1,
    error           TEXT
);
CREATE INDEX IF NOT EXISTS captures_created_idx ON captures (created_utc DESC);
"""


class Store:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir)
        self.captures_dir = self.data_dir / "captures"
        self.captures_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / "webdamga.db"
        with closing(self._conn()) as conn:
            conn.executescript(_SCHEMA)
            conn.commit()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def record(self, meta: dict, *, manifest_sha256: str | None, ok: bool, error: str | None) -> None:
        with closing(self._conn()) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO captures
                    (id, requested_url, final_url, http_status, page_title,
                     created_utc, dir, manifest_sha256, ok, error)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    meta["capture_id"],
                    meta["requested_url"],
                    meta.get("final_url"),
                    meta.get("http_status"),
                    meta.get("page_title"),
                    meta["completed_at_utc"],
                    str(Path(meta["dir"]).resolve()),
                    manifest_sha256,
                    int(ok),
                    error,
                ),
            )
            conn.commit()

    def list(self, limit: int = 50) -> list[dict]:
        with closing(self._conn()) as conn:
            rows = conn.execute(
                "SELECT * FROM captures ORDER BY created_utc DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(row) for row in rows]

    def get(self, capture_id: str) -> dict | None:
        with closing(self._conn()) as conn:
            row = conn.execute("SELECT * FROM captures WHERE id = ?", (capture_id,)).fetchone()
        return dict(row) if row else None
