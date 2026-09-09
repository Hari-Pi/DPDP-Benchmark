"""Durable SQLite queue for requests submitted to the DPDP coordinator."""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class JobStore:
    """Small SQLite-backed job store.

    Each operation opens its own connection so the store is safe across
    FastAPI worker threads and survives coordinator restarts.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_lock = threading.Lock()
        self._initialize()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=10000")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _initialize(self) -> None:
        with self._init_lock, self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    question TEXT NOT NULL,
                    history_json TEXT NOT NULL,
                    k INTEGER NOT NULL,
                    model TEXT NOT NULL,
                    status TEXT NOT NULL,
                    answer TEXT,
                    sources_json TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )"""
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS jobs_status_created "
                "ON jobs(status, created_at)"
            )
            columns = {row[1] for row in conn.execute("PRAGMA table_info(jobs)")}
            if "worker_id" not in columns:
                conn.execute("ALTER TABLE jobs ADD COLUMN worker_id TEXT")
            if "pc_attempted" not in columns:
                conn.execute(
                    "ALTER TABLE jobs ADD COLUMN pc_attempted INTEGER "
                    "NOT NULL DEFAULT 0"
                )

    def create(self, *, question: str, history: list[dict], k: int,
               model: str) -> dict:
        job_id = str(uuid.uuid4())
        now = _now()
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO jobs
                   (id, question, history_json, k, model, status,
                    created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, 'queued', ?, ?)""",
                (job_id, question, json.dumps(history), k, model, now, now),
            )
        return self.get(job_id)  # type: ignore[return-value]

    def get(self, job_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            return None
        item = dict(row)
        item["history"] = json.loads(item.pop("history_json"))
        item["sources"] = json.loads(item.pop("sources_json") or "[]")
        item.pop("error", None) if item.get("error") is None else None
        return item

    def cancel(self, job_id: str) -> dict | None:
        now = _now()
        with self._connect() as conn:
            conn.execute(
                "UPDATE jobs SET status='cancelled', updated_at=? "
                "WHERE id=? AND status='queued'",
                (now, job_id),
            )
        return self.get(job_id)

    def claim_next(self, worker_id: str, *, worker_kind: str = "colab",
                   pc_available: bool = False) -> dict | None:
        """Claim work while preferring PC and preserving Colab fallback."""
        condition = "status='queued'"
        if worker_kind == "pc":
            condition += " AND pc_attempted=0"
        elif pc_available:
            condition += " AND pc_attempted=1"
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                f"SELECT id FROM jobs WHERE {condition} "
                "ORDER BY created_at LIMIT 1"
            ).fetchone()
            if row is None:
                conn.commit()
                return None
            conn.execute(
                "UPDATE jobs SET status='running', worker_id=?, updated_at=? "
                "WHERE id=? AND status='queued'",
                (worker_id, _now(), row["id"]),
            )
            conn.commit()
        return self.get(row["id"])

    def retry_on_colab(self, job_id: str, error: str) -> dict | None:
        """Return a PC failure to the queue for a Colab worker."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE jobs SET status='queued', worker_id=NULL, "
                "pc_attempted=1, error=?, updated_at=? "
                "WHERE id=? AND status='running'",
                (error[:2000], _now(), job_id),
            )
        return self.get(job_id)

    def complete(self, job_id: str, *, answer: str,
                 sources: list[dict]) -> dict | None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE jobs SET status='completed', answer=?, sources_json=?, "
                "error=NULL, updated_at=? WHERE id=? AND status='running'",
                (answer, json.dumps(sources), _now(), job_id),
            )
        return self.get(job_id)

    def fail(self, job_id: str, error: str) -> dict | None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE jobs SET status='failed', error=?, updated_at=? "
                "WHERE id=? AND status='running'",
                (error[:2000], _now(), job_id),
            )
        return self.get(job_id)

    def requeue_worker(self, worker_id: str, *, pc_attempted: bool = False) -> int:
        """Return jobs held by a disconnected worker to the queue."""
        with self._connect() as conn:
            result = conn.execute(
                "UPDATE jobs SET status='queued', worker_id=NULL, "
                "pc_attempted=MAX(pc_attempted, ?), updated_at=? "
                "WHERE status='running' AND worker_id=?",
                (int(pc_attempted), _now(), worker_id),
            )
        return result.rowcount

    def counts(self) -> dict[str, int]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) AS n FROM jobs GROUP BY status"
            ).fetchall()
        return {row["status"]: row["n"] for row in rows}
