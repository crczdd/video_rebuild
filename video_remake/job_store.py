from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import sqlite3
from pathlib import Path
from typing import Iterator


@dataclass(slots=True)
class Job:
    request_key: str
    request_id: str
    record_id: str
    video_name: str
    status: str
    final_prompt: str
    error_message: str
    duration_ms: int | None
    created_at: str
    updated_at: str


class JobStore:
    def __init__(self, path: str | Path, processing_timeout_seconds: float = 180.0) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.processing_timeout_seconds = processing_timeout_seconds
        self._initialize()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    request_key TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL,
                    record_id TEXT NOT NULL,
                    video_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    final_prompt TEXT NOT NULL DEFAULT '',
                    error_message TEXT NOT NULL DEFAULT '',
                    duration_ms INTEGER,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def begin(self, request_key: str, request_id: str, record_id: str, video_name: str) -> tuple[bool, Job | None]:
        now_dt = datetime.now(timezone.utc)
        now = now_dt.isoformat()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO jobs
                (request_key, request_id, record_id, video_name, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'processing', ?, ?)
                """,
                (request_key, request_id, record_id, video_name, now, now),
            )
            if cursor.rowcount == 1:
                return True, None
            row = connection.execute(
                "SELECT * FROM jobs WHERE request_key = ?", (request_key,)
            ).fetchone()
            if not row:
                return True, None
            status = row["status"]
            if status == "failed":
                connection.execute(
                    """UPDATE jobs SET status='processing', error_message='',
                       duration_ms=NULL, updated_at=? WHERE request_key=?""",
                    (now, request_key),
                )
                return True, None
            if status == "processing" and self._is_stale(row, now_dt):
                connection.execute(
                    """UPDATE jobs SET status='processing', request_id=?, record_id=?,
                       video_name=?, error_message='', duration_ms=NULL,
                       created_at=?, updated_at=? WHERE request_key=?""",
                    (request_id, record_id, video_name, now, now, request_key),
                )
                return True, None
            return False, _job(row) if row else None

    def _is_stale(self, row: sqlite3.Row, now_dt: datetime) -> bool:
        updated_at = _parse_iso(row["updated_at"])
        if updated_at is None:
            return True
        elapsed = (now_dt - updated_at).total_seconds()
        return elapsed > self.processing_timeout_seconds

    def reset_stale(self) -> int:
        """Force-reset all processing jobs that exceed the timeout. Returns count."""
        now_dt = datetime.now(timezone.utc)
        now = now_dt.isoformat()
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT request_key, updated_at FROM jobs WHERE status='processing'"
            ).fetchall()
            stale_keys = [row["request_key"] for row in rows if self._is_stale(row, now_dt)]
            if not stale_keys:
                return 0
            placeholders = ",".join("?" for _ in stale_keys)
            connection.execute(
                f"""UPDATE jobs SET status='failed',
                   error_message='强制回收：processing 超时',
                   duration_ms=0, updated_at=? WHERE request_key IN ({placeholders})""",
                (now, *stale_keys),
            )
            return len(stale_keys)

    def succeed(self, request_key: str, final_prompt: str, duration_ms: int) -> None:
        with self._connect() as connection:
            connection.execute(
                """UPDATE jobs SET status='success', final_prompt=?, error_message='',
                   duration_ms=?, updated_at=? WHERE request_key=?""",
                (final_prompt, duration_ms, _now(), request_key),
            )

    def fail(self, request_key: str, error_message: str, duration_ms: int) -> None:
        with self._connect() as connection:
            connection.execute(
                """UPDATE jobs SET status='failed', error_message=?, duration_ms=?,
                   updated_at=? WHERE request_key=?""",
                (error_message, duration_ms, _now(), request_key),
            )

    def summary(self) -> dict:
        with self._connect() as connection:
            totals = connection.execute(
                """
                SELECT COUNT(*) total,
                       SUM(CASE WHEN status='success' THEN 1 ELSE 0 END) success,
                       SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) failed,
                       SUM(CASE WHEN status='processing' THEN 1 ELSE 0 END) processing,
                       COALESCE(AVG(CASE WHEN status IN ('success','failed') THEN duration_ms END), 0) avg_duration_ms
                FROM jobs
                """
            ).fetchone()
            recent_rows = connection.execute(
                """SELECT * FROM jobs ORDER BY updated_at DESC LIMIT 50"""
            ).fetchall()
        return {
            "total": int(totals["total"] or 0),
            "success": int(totals["success"] or 0),
            "failed": int(totals["failed"] or 0),
            "processing": int(totals["processing"] or 0),
            "avg_duration_ms": int(totals["avg_duration_ms"] or 0),
            "recent": [
                {
                    "request_id": row["request_id"],
                    "record_id": row["record_id"],
                    "video_name": row["video_name"],
                    "status": row["status"],
                    "error_message": row["error_message"],
                    "duration_ms": row["duration_ms"],
                    "updated_at": row["updated_at"],
                }
                for row in recent_rows
            ],
        }


def _job(row: sqlite3.Row) -> Job:
    return Job(**dict(row))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
