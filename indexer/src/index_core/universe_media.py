"""Client for the single Universe content-addressed media service."""

import hashlib
import logging
import time
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

import requests

import config

logger = logging.getLogger(__name__)


def _sha256(file_obj: BytesIO) -> str:
    file_obj.seek(0)
    digest = hashlib.sha256(file_obj.read()).hexdigest()
    file_obj.seek(0)
    return digest


def _transaction_id(filename: str) -> str | None:
    stem = Path(filename).stem.lower()
    return stem if len(stem) == 64 and all(character in "0123456789abcdef" for character in stem) else None


def public_universe_media_url(filename: str) -> str:
    """Return the stable public identity URL that redirects to immutable bytes."""
    if not filename:
        raise ValueError("Universe media filename is required")
    endpoint = urlsplit(config.UNIVERSE_MEDIA_INGEST_URL)
    if endpoint.scheme not in {"http", "https"} or not endpoint.netloc:
        raise RuntimeError("Universe media ingestion URL is invalid")
    origin = urlunsplit((endpoint.scheme, endpoint.netloc, "", "", ""))
    return f"{origin}/universe-media/v1/assets/stamps/{quote(filename, safe='')}/content?role=display"


def upload_universe_media(filename: str, mime_type: str, file_obj: BytesIO) -> dict[str, Any]:
    """Upload exact Stamp bytes through the shared verified B2 ingestion API."""
    if not config.UNIVERSE_MEDIA_ENABLED:
        raise RuntimeError("Universe media ingestion is not enabled")
    body = file_obj.getvalue()
    if not body:
        raise ValueError("Universe media body is empty")
    content_hash = _sha256(file_obj)
    transaction_id = _transaction_id(filename)
    headers = {
        "Authorization": f"Bearer {config.UNIVERSE_MEDIA_INGEST_TOKEN}",
        "Content-Type": mime_type or "application/octet-stream",
        "X-Universe-Media-Network": "bitcoin",
        "X-Universe-Media-Protocol": "stamps",
        "X-Universe-Media-Asset-Id": filename,
        "X-Universe-Media-Role": "original",
        "X-Universe-Media-Canonical": "true",
        "X-Universe-Media-Sha256": content_hash,
        "X-Universe-Media-Source-Revision": transaction_id or content_hash,
    }
    if transaction_id:
        headers["X-Universe-Media-Transaction-Id"] = transaction_id

    last_error: Exception | None = None
    for attempt in range(1, config.UNIVERSE_MEDIA_UPLOAD_ATTEMPTS + 1):
        try:
            response = requests.post(
                config.UNIVERSE_MEDIA_INGEST_URL,
                data=body,
                headers=headers,
                timeout=(config.UNIVERSE_MEDIA_CONNECT_TIMEOUT, config.UNIVERSE_MEDIA_READ_TIMEOUT),
            )
            response.raise_for_status()
            result = response.json()
            if (
                not isinstance(result, dict)
                or result.get("contentHash") != content_hash
                or result.get("byteSize") != len(body)
            ):
                raise RuntimeError("Universe media service returned invalid verification evidence")
            return result
        except (requests.RequestException, ValueError, RuntimeError) as error:
            last_error = error
            if attempt < config.UNIVERSE_MEDIA_UPLOAD_ATTEMPTS:
                time.sleep(min(8.0, 0.25 * (2 ** (attempt - 1))))
    raise RuntimeError("Universe media upload failed after bounded retries") from last_error
