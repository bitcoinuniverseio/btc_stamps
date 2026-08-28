import hashlib
from io import BytesIO
from unittest.mock import Mock

import pytest

import index_core.universe_media as universe_media


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setattr(universe_media.config, "UNIVERSE_MEDIA_ENABLED", True)
    monkeypatch.setattr(
        universe_media.config,
        "UNIVERSE_MEDIA_INGEST_URL",
        "https://media.example/universe-media/v1/objects",
    )
    monkeypatch.setattr(universe_media.config, "UNIVERSE_MEDIA_INGEST_TOKEN", "t" * 48)
    monkeypatch.setattr(universe_media.config, "UNIVERSE_MEDIA_UPLOAD_ATTEMPTS", 3)
    monkeypatch.setattr(universe_media.config, "UNIVERSE_MEDIA_CONNECT_TIMEOUT", 5.0)
    monkeypatch.setattr(universe_media.config, "UNIVERSE_MEDIA_READ_TIMEOUT", 90.0)


def test_upload_binds_exact_stamp_bytes_and_transaction_identity(monkeypatch, enabled):
    body = b"canonical stamp bytes"
    content_hash = hashlib.sha256(body).hexdigest()
    transaction_id = "a" * 64
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"contentHash": content_hash, "byteSize": len(body)}
    post = Mock(return_value=response)
    monkeypatch.setattr(universe_media.requests, "post", post)

    result = universe_media.upload_universe_media(f"{transaction_id}.png", "image/png", BytesIO(body))

    assert result["contentHash"] == content_hash
    _, kwargs = post.call_args
    assert kwargs["data"] == body
    assert kwargs["headers"] == {
        "Authorization": "Bearer " + "t" * 48,
        "Content-Type": "image/png",
        "X-Universe-Media-Network": "bitcoin",
        "X-Universe-Media-Protocol": "stamps",
        "X-Universe-Media-Asset-Id": f"{transaction_id}.png",
        "X-Universe-Media-Role": "original",
        "X-Universe-Media-Canonical": "true",
        "X-Universe-Media-Sha256": content_hash,
        "X-Universe-Media-Source-Revision": transaction_id,
        "X-Universe-Media-Transaction-Id": transaction_id,
    }


def test_upload_retries_but_never_accepts_unverified_evidence(monkeypatch, enabled):
    body = b"canonical stamp bytes"
    bad_response = Mock()
    bad_response.raise_for_status.return_value = None
    bad_response.json.return_value = {"contentHash": "0" * 64, "byteSize": len(body)}
    monkeypatch.setattr(universe_media.requests, "post", Mock(return_value=bad_response))
    monkeypatch.setattr(universe_media.time, "sleep", Mock())

    with pytest.raises(RuntimeError, match="bounded retries"):
        universe_media.upload_universe_media("stamp.svg", "image/svg+xml", BytesIO(body))

    assert universe_media.requests.post.call_count == 3


def test_public_url_uses_central_stable_identity(monkeypatch, enabled):
    monkeypatch.setattr(
        universe_media.config,
        "UNIVERSE_MEDIA_INGEST_URL",
        "https://api.bitcoinuniverse.io/universe-media/v1/objects",
    )

    assert universe_media.public_universe_media_url("stamp name.svg") == (
        "https://api.bitcoinuniverse.io/universe-media/v1/assets/stamps/" "stamp%20name.svg/content?role=display"
    )
