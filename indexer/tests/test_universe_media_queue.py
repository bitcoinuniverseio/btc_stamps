import hashlib
import sqlite3
from pathlib import Path

from index_core.universe_media_queue import UniverseMediaQueue


def test_queue_persists_exact_bytes_and_recovers_processing_jobs(tmp_path):
    body = b"durable canonical bytes"
    content_hash = hashlib.sha256(body).hexdigest()
    queue = UniverseMediaQueue(str(tmp_path))
    job_id = queue.enqueue("asset.png", "image/png", body)
    job = queue.claim(job_id)

    assert job is not None
    assert job.content_sha256 == content_hash
    assert Path(job.body_path).read_bytes() == body

    recovered = UniverseMediaQueue(str(tmp_path))
    assert recovered.pending_ids() == [job_id]
    retried = recovered.claim(job_id)
    assert retried is not None
    recovered.complete(job_id)
    assert recovered.pending_ids() == []


def test_queue_globally_deduplicates_spooled_bytes(tmp_path):
    body = b"same bytes"
    queue = UniverseMediaQueue(str(tmp_path))
    first = queue.enqueue("one.svg", "image/svg+xml", body)
    second = queue.enqueue("two.svg", "image/svg+xml", body)

    first_job = queue.claim(first)
    second_job = queue.claim(second)
    assert first_job is not None and second_job is not None
    assert first_job.body_path == second_job.body_path
    assert len(list((tmp_path / "objects" / "sha256").rglob(hashlib.sha256(body).hexdigest()))) == 1


def test_queue_uses_bounded_retry_and_terminal_failure(tmp_path, monkeypatch):
    queue = UniverseMediaQueue(str(tmp_path), maximum_attempts=2)
    job_id = queue.enqueue("asset.bin", "application/octet-stream", b"body")
    assert queue.claim(job_id) is not None
    assert queue.fail(job_id, "temporary") is True
    monkeypatch.setattr("index_core.universe_media_queue.time.time", lambda: 10_000_000_000)
    assert queue.claim(job_id) is not None
    assert queue.fail(job_id, "terminal") is False
    assert queue.pending_ids() == []
    assert queue.health()["ready"] is False
    assert queue.health()["terminal"] == 1


def test_queue_tracks_backfill_source_readiness(tmp_path):
    queue = UniverseMediaQueue(str(tmp_path))
    queue.update_backfill_source(
        "stamps:StampTableV4",
        cursor_value=10,
        high_watermark=20,
        scanned=10,
        enqueued=9,
        missing=1,
        decode_failures=0,
        status="running",
    )

    assert queue.health()["ready"] is False
    assert queue.health()["incomplete_sources"] == 1
    assert queue.backfill_source("stamps:StampTableV4")["missing"] == 1

    queue.update_backfill_source(
        "stamps:StampTableV4",
        cursor_value=20,
        high_watermark=20,
        scanned=20,
        enqueued=20,
        missing=0,
        decode_failures=0,
        status="complete",
    )
    assert queue.health()["ready"] is True


def test_queue_closes_short_lived_connections(tmp_path, monkeypatch):
    queue = UniverseMediaQueue(str(tmp_path))
    opened = []
    connect = queue._connect

    def tracked_connect():
        connection = connect()
        opened.append(connection)
        return connection

    monkeypatch.setattr(queue, "_connect", tracked_connect)

    for _ in range(20):
        assert queue.pending_ids() == []

    assert len(opened) == 20
    for connection in opened:
        try:
            connection.execute("SELECT 1")
        except sqlite3.ProgrammingError as error:
            assert "closed" in str(error).lower()
        else:
            raise AssertionError("Universe media queue left a SQLite connection open")
