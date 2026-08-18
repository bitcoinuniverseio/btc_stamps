#!/usr/bin/env python3
"""Durably backfill historical Bitcoin Stamps into Universe media storage.

The scan is keyset-paginated and resumable. Exact bytes are decoded from the
consensus ``stamp_base64`` column, written to the content-addressed local spool,
and then uploaded through the same verified central ingestion API used by live
indexing. Rows whose exact bytes are unavailable are counted as unresolved and
prevent a successful completion status.

Examples:
    poetry run python tools/backfill_universe_media.py --dry-run
    poetry run python tools/backfill_universe_media.py --drain
    poetry run python tools/backfill_universe_media.py --drain --retry-incomplete
"""

from __future__ import annotations

import argparse
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pymysql

_INDEXER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_INDEXER_DIR / "src"))

import config  # noqa: E402
from index_core.base64_utils import lenient_b64decode  # noqa: E402
from index_core.universe_media import upload_universe_media  # noqa: E402
from index_core.universe_media_queue import UniverseMediaQueue  # noqa: E402

SOURCE_NAME = "stamps:StampTableV4"

MIME_SUFFIXES = {
    "application/gzip": "gz",
    "application/javascript": "js",
    "application/json": "json",
    "audio/mpeg": "mp3",
    "image/avif": "avif",
    "image/gif": "gif",
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/svg+xml": "svg",
    "image/webp": "webp",
    "text/html": "html",
    "text/plain": "txt",
}


def connect():
    return pymysql.connect(
        host=os.environ.get("RDS_HOSTNAME", os.environ.get("MYSQL_HOST", "localhost")),
        port=int(os.environ.get("RDS_PORT", os.environ.get("MYSQL_PORT", 3306))),
        user=os.environ.get("RDS_USER", os.environ.get("MYSQL_USER", "root")),
        password=os.environ.get("RDS_PASSWORD", os.environ.get("MYSQL_PASSWORD", "")),
        database=os.environ.get("RDS_DATABASE", os.environ.get("MYSQL_DATABASE", "btc_stamps")),
        charset="utf8mb4",
        autocommit=True,
        read_timeout=600,
        cursorclass=pymysql.cursors.SSCursor,
    )


def decode_exact_media(value: str | bytes | None) -> bytes | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        try:
            value = value.decode("ascii")
        except UnicodeDecodeError:
            return None
    if not value:
        return None
    try:
        return lenient_b64decode(value)
    except Exception:
        return None


def media_filename(tx_hash: str, stamp_url: str | None, mime_type: str | None) -> str:
    if stamp_url:
        path = unquote(urlsplit(stamp_url).path)
        marker = "/assets/stamps/"
        if marker in path:
            candidate = path.split(marker, 1)[1].split("/content", 1)[0]
        else:
            candidate = Path(path).name
        if candidate and "/" not in candidate and candidate not in {".", ".."}:
            return candidate
    suffix = MIME_SUFFIXES.get((mime_type or "").lower(), "bin")
    return f"{tx_hash}.{suffix}"


def canonical_mime(body: bytes, stored_mime: str | None) -> str:
    if body.startswith(b"\x1f\x8b"):
        return "application/gzip"
    return stored_mime or "application/octet-stream"


def drain_jobs(queue: UniverseMediaQueue, workers: int, limit: int = 1000) -> int:
    job_ids = queue.pending_ids(limit=limit)
    if not job_ids:
        return 0

    def process(job_id: int) -> None:
        job = queue.claim(job_id)
        if job is None:
            return
        try:
            body = Path(job.body_path).read_bytes()
            upload_universe_media(job.filename, job.mime_type, BytesIO(body))
            queue.complete(job.job_id)
        except Exception as error:
            queue.fail(job.job_id, str(error))

    with ThreadPoolExecutor(max_workers=max(1, min(32, workers))) as executor:
        list(executor.map(process, job_ids))
    return len(job_ids)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--batch-size", type=int, default=250)
    parser.add_argument("--max-rows", type=int, default=0, help="Stop after N rows; 0 scans to the high watermark")
    parser.add_argument("--workers", type=int, default=5)
    parser.add_argument("--drain", action="store_true", help="Upload queued jobs as the scan progresses")
    parser.add_argument("--dry-run", action="store_true", help="Read and decode without changing the durable spool")
    parser.add_argument(
        "--retry-incomplete",
        action="store_true",
        help="Rescan from the beginning to retry rows whose exact bytes were previously unavailable",
    )
    parser.add_argument(
        "--allow-incomplete",
        action="store_true",
        help="Return zero even if exact source bytes remain unavailable (health remains not ready)",
    )
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    if not args.dry_run and not config.UNIVERSE_MEDIA_ENABLED:
        raise RuntimeError("UNIVERSE_MEDIA_ENABLED must be true for a durable backfill")

    queue = UniverseMediaQueue(config.UNIVERSE_MEDIA_SPOOL_DIR, config.UNIVERSE_MEDIA_QUEUE_MAX_ATTEMPTS)
    db = connect()
    try:
        with db.cursor() as cursor:
            cursor.execute("SELECT MIN(stamp),MAX(stamp),COUNT(*) FROM StampTableV4")
            minimum, maximum, total = cursor.fetchone()
        if total == 0:
            print("StampTableV4 is empty")
            return 1

        existing = queue.backfill_source(SOURCE_NAME)
        if existing and not args.retry_incomplete:
            cursor_value = existing["cursor_value"]
            scanned = existing["scanned"]
            enqueued = existing["enqueued"]
            missing = existing["missing"]
            decode_failures = existing["decode_failures"]
        else:
            cursor_value = int(minimum) - 1
            scanned = enqueued = missing = decode_failures = 0
        high_watermark = int(maximum)
        processed_this_run = 0

        while cursor_value < high_watermark:
            limit = max(1, min(10_000, args.batch_size))
            if args.max_rows:
                remaining = args.max_rows - processed_this_run
                if remaining <= 0:
                    break
                limit = min(limit, remaining)
            with db.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT stamp,tx_hash,stamp_base64,stamp_mimetype,stamp_url,file_size_bytes
                    FROM StampTableV4
                    WHERE stamp > %s AND stamp <= %s
                    ORDER BY stamp LIMIT %s
                    """,
                    (cursor_value, high_watermark, limit),
                )
                rows = list(cursor.fetchall())
            if not rows:
                break

            for stamp, tx_hash, encoded, mime_type, stamp_url, file_size_bytes in rows:
                cursor_value = int(stamp)
                scanned += 1
                processed_this_run += 1
                if encoded is None or encoded == "" or encoded == b"":
                    # Not every StampTable row represents a stored media
                    # object. Only an absent payload that previously produced
                    # a URL/size is an unresolved migration gap.
                    if stamp_url or int(file_size_bytes or 0) > 0:
                        missing += 1
                    continue
                body = decode_exact_media(encoded)
                if not body:
                    decode_failures += 1
                    continue
                filename = media_filename(str(tx_hash), stamp_url, mime_type)
                if not args.dry_run:
                    queue.enqueue(filename, canonical_mime(body, mime_type), body)
                enqueued += 1

            if not args.dry_run:
                queue.update_backfill_source(
                    SOURCE_NAME,
                    cursor_value=cursor_value,
                    high_watermark=high_watermark,
                    scanned=scanned,
                    enqueued=enqueued,
                    missing=missing,
                    decode_failures=decode_failures,
                    status="running",
                )
                if args.drain:
                    drain_jobs(queue, args.workers)
            print(
                f"cursor={cursor_value}/{high_watermark} scanned={scanned} "
                f"enqueued={enqueued} missing={missing} decode_failures={decode_failures}",
                flush=True,
            )

        if args.drain and not args.dry_run:
            while drain_jobs(queue, args.workers):
                pass

        health = queue.health()
        fully_scanned = cursor_value >= high_watermark
        unresolved = missing + decode_failures
        pending = sum(health["counts"].get(name, 0) for name in ("queued", "retry", "processing"))
        complete = fully_scanned and unresolved == 0 and pending == 0 and health["terminal"] == 0
        if not args.dry_run:
            queue.update_backfill_source(
                SOURCE_NAME,
                cursor_value=cursor_value,
                high_watermark=high_watermark,
                scanned=scanned,
                enqueued=enqueued,
                missing=missing,
                decode_failures=decode_failures,
                status="complete" if complete else "pending",
                last_error=None if complete else "Backfill has unresolved source rows or upload jobs",
            )
        print(
            f"complete={complete} total_rows={total} scanned={scanned} enqueued={enqueued} "
            f"unresolved={unresolved} pending={pending} terminal={health['terminal']}"
        )
        return 0 if complete or args.dry_run or args.allow_incomplete else 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
