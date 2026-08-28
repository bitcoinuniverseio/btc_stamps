import base64
import importlib.util
from pathlib import Path

_SCRIPT = Path(__file__).parents[1] / "tools" / "backfill_universe_media.py"
_SPEC = importlib.util.spec_from_file_location("backfill_universe_media", _SCRIPT)
backfill = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(backfill)


def test_decode_exact_media_preserves_bytes():
    body = b"\x1f\x8b\x08\x00exact-chain-bytes"
    assert backfill.decode_exact_media(base64.b64encode(body).decode()) == body
    assert backfill.canonical_mime(body, "image/svg+xml") == "application/gzip"


def test_media_filename_supports_central_and_legacy_urls():
    tx_hash = "a" * 64
    assert (
        backfill.media_filename(
            tx_hash,
            f"https://core.example/universe-media/v1/assets/stamps/{tx_hash}.svg/content?role=display",
            "image/svg+xml",
        )
        == f"{tx_hash}.svg"
    )
    assert backfill.media_filename(tx_hash, f"https://legacy.example/stamps/{tx_hash}.png", "image/png") == (f"{tx_hash}.png")


def test_media_filename_has_deterministic_fallback():
    tx_hash = "b" * 64
    assert backfill.media_filename(tx_hash, None, "image/webp") == f"{tx_hash}.webp"
