"""SQLite-basierte Job-Queue. Single-Writer, WAL-Modus.

Verträgt sich gut mit FastAPI, solange Concurrency auf Pi-Seite gering ist
(max. 1 Worker, der den Nano dispatcht). Für höhere Last später Redis.
"""
from __future__ import annotations

import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id            TEXT PRIMARY KEY,
    sha256        TEXT NOT NULL,
    kind          TEXT NOT NULL,
    source_path   TEXT NOT NULL,
    state         TEXT NOT NULL DEFAULT 'queued',
    attempts      INTEGER NOT NULL DEFAULT 0,
    error         TEXT,
    result_path   TEXT,
    created_at    REAL NOT NULL,
    updated_at    REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_state ON jobs(state);
CREATE INDEX IF NOT EXISTS idx_jobs_sha   ON jobs(sha256);
"""

VALID_STATES = {"queued", "running", "done", "failed", "quarantined"}


class JobQueue:
    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA synchronous=NORMAL")
            c.executescript(SCHEMA)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        c = sqlite3.connect(self.db_path, timeout=10.0, isolation_level=None)
        c.row_factory = sqlite3.Row
        try:
            yield c
        finally:
            c.close()

    def enqueue(self, *, sha256: str, kind: str, source_path: str) -> str:
        # Idempotent ueber (sha256, kind): existiert schon ein "done" -> wiederverwenden
        with self._conn() as c:
            row = c.execute(
                "SELECT id, state FROM jobs WHERE sha256=? AND kind=? "
                "ORDER BY created_at DESC LIMIT 1",
                (sha256, kind),
            ).fetchone()
            if row and row["state"] == "done":
                return row["id"]
            jid = str(uuid.uuid4())
            now = time.time()
            c.execute(
                "INSERT INTO jobs(id,sha256,kind,source_path,state,attempts,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (jid, sha256, kind, source_path, "queued", 0, now, now),
            )
            return jid

    def claim_next(self) -> dict | None:
        """Atomisch einen Job 'queued' -> 'running' setzen."""
        with self._conn() as c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute(
                "SELECT * FROM jobs WHERE state='queued' "
                "ORDER BY created_at ASC LIMIT 1"
            ).fetchone()
            if not row:
                c.execute("COMMIT")
                return None
            c.execute(
                "UPDATE jobs SET state='running', attempts=attempts+1, updated_at=? "
                "WHERE id=? AND state='queued'",
                (time.time(), row["id"]),
            )
            c.execute("COMMIT")
            return dict(row)

    def mark_done(self, job_id: str, result_path: str) -> None:
        with self._conn() as c:
            c.execute(
                "UPDATE jobs SET state='done', result_path=?, error=NULL, updated_at=? "
                "WHERE id=?",
                (result_path, time.time(), job_id),
            )

    def mark_failed(self, job_id: str, error: str, *, max_attempts: int = 3) -> None:
        with self._conn() as c:
            row = c.execute(
                "SELECT attempts FROM jobs WHERE id=?", (job_id,)
            ).fetchone()
            new_state = "failed" if row and row["attempts"] >= max_attempts else "queued"
            c.execute(
                "UPDATE jobs SET state=?, error=?, updated_at=? WHERE id=?",
                (new_state, error[:1000], time.time(), job_id),
            )

    def get(self, job_id: str) -> dict | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            return dict(row) if row else None

    def stats(self) -> dict[str, int]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT state, COUNT(*) AS n FROM jobs GROUP BY state"
            ).fetchall()
            return {r["state"]: r["n"] for r in rows}
