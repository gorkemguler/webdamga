"""Yakalama indeksini ve iş kuyruğunu tutan küçük SQLite deposu (stdlib sqlite3)."""

from __future__ import annotations

import secrets
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
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

CREATE TABLE IF NOT EXISTS jobs (
    id            TEXT PRIMARY KEY,
    url           TEXT NOT NULL,
    settings_json TEXT NOT NULL,
    status        TEXT NOT NULL,          -- queued | running | done | failed | cancelled
    source        TEXT NOT NULL DEFAULT 'web',
    monitor_id    INTEGER,
    capture_id    TEXT,
    error         TEXT,
    attempts      INTEGER NOT NULL DEFAULT 0,
    created_utc   TEXT NOT NULL,
    started_utc   TEXT,
    finished_utc  TEXT
);
CREATE INDEX IF NOT EXISTS jobs_status_idx ON jobs (status, created_utc);
"""

JOB_ACTIVE = ("queued", "running")
MAX_ATTEMPTS = 3


def now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class Store:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir)
        self.captures_dir = self.data_dir / "captures"
        self.captures_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / "webdamga.db"
        with closing(self._conn()) as conn:
            # Web istekleri ve worker aynı anda yazabildiği için WAL.
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(_SCHEMA)
            conn.commit()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=15)
        conn.row_factory = sqlite3.Row
        return conn

    # ------------------------------------------------------------------ captures

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

    # ---------------------------------------------------------------------- jobs

    def create_job(
        self, url: str, settings_json: str, *, source: str = "web", monitor_id: int | None = None
    ) -> dict:
        job_id = secrets.token_hex(6)
        with closing(self._conn()) as conn:
            conn.execute(
                """
                INSERT INTO jobs (id, url, settings_json, status, source, monitor_id, created_utc)
                VALUES (?, ?, ?, 'queued', ?, ?, ?)
                """,
                (job_id, url, settings_json, source, monitor_id, now_iso()),
            )
            conn.commit()
        job = self.get_job(job_id)
        assert job is not None
        return job

    def get_job(self, job_id: str) -> dict | None:
        with closing(self._conn()) as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return dict(row) if row else None

    def list_jobs(self, *, statuses: tuple[str, ...] | None = None, limit: int = 50) -> list[dict]:
        query = "SELECT * FROM jobs"
        params: list = []
        if statuses:
            query += f" WHERE status IN ({','.join('?' * len(statuses))})"
            params.extend(statuses)
        query += " ORDER BY created_utc DESC, rowid DESC LIMIT ?"
        params.append(limit)
        with closing(self._conn()) as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def claim_next_job(self) -> dict | None:
        """En eski bekleyen işi atomik olarak 'running' durumuna çeker."""
        with closing(self._conn()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT id FROM jobs WHERE status = 'queued' ORDER BY created_utc, rowid LIMIT 1"
            ).fetchone()
            if row is None:
                conn.rollback()
                return None
            conn.execute(
                """
                UPDATE jobs SET status = 'running', started_utc = ?, attempts = attempts + 1
                WHERE id = ? AND status = 'queued'
                """,
                (now_iso(), row["id"]),
            )
            conn.commit()
        return self.get_job(row["id"])

    def finish_job(
        self, job_id: str, *, status: str, capture_id: str | None = None, error: str | None = None
    ) -> None:
        with closing(self._conn()) as conn:
            conn.execute(
                "UPDATE jobs SET status = ?, capture_id = ?, error = ?, finished_utc = ? WHERE id = ?",
                (status, capture_id, error, now_iso(), job_id),
            )
            conn.commit()

    def cancel_job(self, job_id: str) -> bool:
        """Yalnızca henüz başlamamış işler iptal edilebilir."""
        with closing(self._conn()) as conn:
            cur = conn.execute(
                "UPDATE jobs SET status = 'cancelled', finished_utc = ? WHERE id = ? AND status = 'queued'",
                (now_iso(), job_id),
            )
            conn.commit()
        return cur.rowcount == 1

    def recover_interrupted_jobs(self) -> tuple[int, int]:
        """Süreç çökerken 'running' kalan işleri yeniden kuyruğa alır.

        Çok kez yarıda kalan iş sonsuza dek tekrarlanmasın diye MAX_ATTEMPTS'ten
        sonra başarısız sayılır. (yeniden kuyruğa alınan, başarısız sayılan) döner.
        """
        with closing(self._conn()) as conn:
            failed = conn.execute(
                """
                UPDATE jobs SET status = 'failed', finished_utc = ?,
                    error = 'interrupted too many times'
                WHERE status = 'running' AND attempts >= ?
                """,
                (now_iso(), MAX_ATTEMPTS),
            ).rowcount
            requeued = conn.execute(
                "UPDATE jobs SET status = 'queued', started_utc = NULL WHERE status = 'running'"
            ).rowcount
            conn.commit()
        return requeued, failed
