"""Durable local spool for Universe media ingestion jobs."""

import hashlib
import os
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class UniverseMediaJob:
    job_id: int
    filename: str
    mime_type: str
    content_sha256: str
    body_path: str
    attempts: int


class UniverseMediaQueue:
    def __init__(self, root: str, maximum_attempts: int = 20):
        self.root = Path(root).expanduser().resolve()
        self.objects = self.root / "objects" / "sha256"
        self.database_path = self.root / "jobs.sqlite3"
        self.maximum_attempts = max(1, min(100, maximum_attempts))
        self.objects.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS media_jobs (
                  job_id INTEGER PRIMARY KEY AUTOINCREMENT,
                  filename TEXT NOT NULL,
                  mime_type TEXT NOT NULL,
                  content_sha256 TEXT NOT NULL,
                  body_path TEXT NOT NULL,
                  attempts INTEGER NOT NULL DEFAULT 0,
                  status TEXT NOT NULL DEFAULT 'queued',
                  next_retry_at REAL NOT NULL DEFAULT 0,
                  last_error TEXT,
                  created_at REAL NOT NULL,
                  updated_at REAL NOT NULL,
                  UNIQUE(filename, content_sha256)
                )
                """)
            connection.execute("CREATE INDEX IF NOT EXISTS media_jobs_claim ON media_jobs(status, next_retry_at, job_id)")
            connection.execute("""
                CREATE TABLE IF NOT EXISTS media_backfill_sources (
                  source_name TEXT PRIMARY KEY,
                  cursor_value INTEGER NOT NULL DEFAULT 0,
                  high_watermark INTEGER NOT NULL DEFAULT 0,
                  scanned INTEGER NOT NULL DEFAULT 0,
                  enqueued INTEGER NOT NULL DEFAULT 0,
                  missing INTEGER NOT NULL DEFAULT 0,
                  decode_failures INTEGER NOT NULL DEFAULT 0,
                  status TEXT NOT NULL DEFAULT 'pending',
                  last_error TEXT,
                  updated_at REAL NOT NULL
                )
                """)
            connection.execute("UPDATE media_jobs SET status='retry', next_retry_at=0 WHERE status='processing'")

    def enqueue(self, filename: str, mime_type: str, body: bytes) -> int:
        if not filename or not body:
            raise ValueError("Universe media queue requires filename and bytes")
        content_hash = hashlib.sha256(body).hexdigest()
        body_path = self.objects / content_hash[:2] / content_hash[2:4] / content_hash
        body_path.parent.mkdir(parents=True, exist_ok=True)
        if body_path.exists():
            if hashlib.sha256(body_path.read_bytes()).hexdigest() != content_hash:
                raise RuntimeError("Universe media spool content collision")
        else:
            temporary = body_path.with_name(f"{body_path.name}.{os.getpid()}.tmp")
            try:
                with open(temporary, "xb") as output:
                    output.write(body)
                    output.flush()
                    os.fsync(output.fileno())
                os.replace(temporary, body_path)
            finally:
                try:
                    temporary.unlink()
                except FileNotFoundError:
                    pass
        now = time.time()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO media_jobs
                  (filename,mime_type,content_sha256,body_path,status,
                   next_retry_at,created_at,updated_at)
                VALUES (?,?,?,?,'queued',0,?,?)
                ON CONFLICT(filename,content_sha256) DO UPDATE SET
                  mime_type=excluded.mime_type,
                  body_path=excluded.body_path,
                  status=CASE WHEN media_jobs.status='completed'
                    THEN media_jobs.status ELSE 'queued' END,
                  next_retry_at=CASE WHEN media_jobs.status='completed'
                    THEN media_jobs.next_retry_at ELSE 0 END,
                  updated_at=excluded.updated_at
                """,
                (filename, mime_type or "application/octet-stream", content_hash, str(body_path), now, now),
            )
            row = connection.execute(
                "SELECT job_id FROM media_jobs WHERE filename=? AND content_sha256=?",
                (filename, content_hash),
            ).fetchone()
        if not row:
            raise RuntimeError("Universe media queue failed to persist a job")
        return int(row[0])

    def pending_ids(self, limit: int = 100_000) -> list[int]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT job_id FROM media_jobs
                WHERE status IN ('queued','retry') AND next_retry_at<=?
                ORDER BY job_id LIMIT ?
                """,
                (time.time(), max(1, min(1_000_000, limit))),
            ).fetchall()
        return [int(row[0]) for row in rows]

    def claim(self, job_id: int) -> UniverseMediaJob | None:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT job_id,filename,mime_type,content_sha256,body_path,attempts
                FROM media_jobs
                WHERE job_id=? AND status IN ('queued','retry') AND next_retry_at<=?
                """,
                (job_id, time.time()),
            ).fetchone()
            if not row:
                connection.rollback()
                return None
            connection.execute(
                "UPDATE media_jobs SET status='processing',updated_at=? WHERE job_id=?",
                (time.time(), job_id),
            )
            connection.commit()
            return UniverseMediaJob(
                job_id=int(row[0]),
                filename=str(row[1]),
                mime_type=str(row[2]),
                content_sha256=str(row[3]),
                body_path=str(row[4]),
                attempts=int(row[5]),
            )
        finally:
            connection.close()

    def complete(self, job_id: int) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE media_jobs SET status='completed',last_error=NULL,updated_at=? WHERE job_id=?",
                (time.time(), job_id),
            )

    def fail(self, job_id: int, message: str) -> bool:
        with self._connect() as connection:
            row = connection.execute("SELECT attempts FROM media_jobs WHERE job_id=?", (job_id,)).fetchone()
            if not row:
                return False
            attempts = int(row[0]) + 1
            terminal = attempts >= self.maximum_attempts
            retry_at = time.time() + min(3600, 5 * (2 ** min(10, attempts)))
            connection.execute(
                """
                UPDATE media_jobs SET attempts=?,status=?,next_retry_at=?,
                  last_error=?,updated_at=? WHERE job_id=?
                """,
                (
                    attempts,
                    "failed" if terminal else "retry",
                    retry_at,
                    str(message)[:512],
                    time.time(),
                    job_id,
                ),
            )
        return not terminal

    def health(self) -> dict:
        with self._connect() as connection:
            counts = {
                str(row[0]): int(row[1])
                for row in connection.execute("SELECT status,COUNT(*) FROM media_jobs GROUP BY status").fetchall()
            }
            oldest = connection.execute(
                """
                SELECT CAST(MAX(?-created_at) AS INTEGER) FROM media_jobs
                WHERE status IN ('queued','retry','processing')
                """,
                (time.time(),),
            ).fetchone()
            sources = [
                {
                    "source_name": str(row[0]),
                    "cursor_value": int(row[1]),
                    "high_watermark": int(row[2]),
                    "scanned": int(row[3]),
                    "enqueued": int(row[4]),
                    "missing": int(row[5]),
                    "decode_failures": int(row[6]),
                    "status": str(row[7]),
                    "last_error": row[8],
                }
                for row in connection.execute("""
                    SELECT source_name,cursor_value,high_watermark,scanned,
                           enqueued,missing,decode_failures,status,last_error
                    FROM media_backfill_sources ORDER BY source_name
                    """).fetchall()
            ]
        terminal = counts.get("failed", 0)
        incomplete_sources = sum(1 for source in sources if source["status"] != "complete")
        return {
            "ready": terminal == 0 and incomplete_sources == 0,
            "counts": counts,
            "terminal": terminal,
            "oldest_pending_seconds": max(0, int(oldest[0] or 0)),
            "incomplete_sources": incomplete_sources,
            "sources": sources,
        }

    def backfill_source(self, source_name: str) -> dict | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT source_name,cursor_value,high_watermark,scanned,enqueued,
                       missing,decode_failures,status,last_error
                FROM media_backfill_sources WHERE source_name=?
                """,
                (source_name,),
            ).fetchone()
        if not row:
            return None
        return {
            "source_name": str(row[0]),
            "cursor_value": int(row[1]),
            "high_watermark": int(row[2]),
            "scanned": int(row[3]),
            "enqueued": int(row[4]),
            "missing": int(row[5]),
            "decode_failures": int(row[6]),
            "status": str(row[7]),
            "last_error": row[8],
        }

    def update_backfill_source(
        self,
        source_name: str,
        *,
        cursor_value: int,
        high_watermark: int,
        scanned: int,
        enqueued: int,
        missing: int,
        decode_failures: int,
        status: str,
        last_error: str | None = None,
    ) -> None:
        if status not in {"pending", "running", "complete", "error"}:
            raise ValueError("Invalid Universe media backfill status")
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO media_backfill_sources
                  (source_name,cursor_value,high_watermark,scanned,enqueued,
                   missing,decode_failures,status,last_error,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(source_name) DO UPDATE SET
                  cursor_value=excluded.cursor_value,
                  high_watermark=excluded.high_watermark,
                  scanned=excluded.scanned,
                  enqueued=excluded.enqueued,
                  missing=excluded.missing,
                  decode_failures=excluded.decode_failures,
                  status=excluded.status,
                  last_error=excluded.last_error,
                  updated_at=excluded.updated_at
                """,
                (
                    source_name,
                    cursor_value,
                    high_watermark,
                    scanned,
                    enqueued,
                    missing,
                    decode_failures,
                    status,
                    str(last_error)[:512] if last_error else None,
                    time.time(),
                ),
            )
