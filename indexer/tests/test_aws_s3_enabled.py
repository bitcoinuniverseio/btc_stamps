"""Regression coverage for the single Universe media backend cutover."""

import io

import pytest

from index_core import files


def _mock(monkeypatch, name):
    from unittest.mock import MagicMock

    value = MagicMock()
    monkeypatch.setattr(files, name, value)
    return value


def test_legacy_s3_configuration_cannot_select_a_parallel_backend(monkeypatch):
    monkeypatch.setattr(files.config, "STORE_FILES", True)
    monkeypatch.setattr(files.config, "UNIVERSE_MEDIA_ENABLED", False)
    monkeypatch.setattr(files.config, "AWS_S3_ENABLED", True)
    monkeypatch.setattr(files.config, "USE_ASYNC_UPLOADS", True)
    async_upload = _mock(monkeypatch, "async_check_existing_and_upload_to_s3")
    disk = _mock(monkeypatch, "store_files_to_disk")

    with pytest.raises(RuntimeError, match="shared Universe media"):
        files.store_files(None, "test.txt", b"data", "text/plain")

    async_upload.assert_not_called()
    disk.assert_not_called()


def test_central_async_path_preserves_existing_call_contract(monkeypatch):
    monkeypatch.setattr(files.config, "STORE_FILES", True)
    monkeypatch.setattr(files.config, "UNIVERSE_MEDIA_ENABLED", True)
    monkeypatch.setattr(files.config, "USE_ASYNC_UPLOADS", True)
    async_upload = _mock(monkeypatch, "async_check_existing_and_upload_to_s3")
    disk = _mock(monkeypatch, "store_files_to_disk")

    md5_hash, filename = files.store_files(None, "test.txt", b"data", "text/plain")

    call = async_upload.call_args[0]
    assert call[0] == "test.txt"
    assert call[1] == "text/plain"
    assert isinstance(call[2], io.BytesIO)
    assert call[3] == md5_hash
    assert filename == "test.txt"
    disk.assert_not_called()
