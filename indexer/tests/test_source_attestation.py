"""Actual byte attestation never substitutes a version label for source identity."""
import hashlib
import json

import pytest
from index_core.source_attestation import collect_indexer_source_metadata


def test_source_digest_tracks_bytes_and_is_order_independent(tmp_path, monkeypatch):
    monkeypatch.setenv('STAMPS_APPROVED_BUILD_ID', 'candidate/native-v1')
    (tmp_path/'z.py').write_text('z = 1\n')
    (tmp_path/'a.py').write_text('a = 1\n')
    first=collect_indexer_source_metadata(tmp_path)
    expected={f'indexer/src/{name}':hashlib.sha256((tmp_path/name).read_bytes()).hexdigest() for name in ['a.py','z.py']}
    assert first['source_files'] == expected
    assert first['source_digest_sha256'] == hashlib.sha256(json.dumps(expected,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    (tmp_path/'a.py').write_text('a = 2\n')
    assert collect_indexer_source_metadata(tmp_path)['source_digest_sha256'] != first['source_digest_sha256']


def test_no_build_id_does_not_claim_approval(tmp_path,monkeypatch):
    monkeypatch.delenv('STAMPS_APPROVED_BUILD_ID',raising=False)
    (tmp_path/'parser.py').write_text('pass\n')
    metadata=collect_indexer_source_metadata(tmp_path)
    assert metadata['build_id'] is None and 'approved' not in metadata
    monkeypatch.setenv('STAMPS_APPROVED_BUILD_ID','unsafe\nidentity')
    with pytest.raises(ValueError,match='invalid syntax'):collect_indexer_source_metadata(tmp_path)


def test_empty_source_cannot_attest(tmp_path):
    with pytest.raises(ValueError,match='no source files'):collect_indexer_source_metadata(tmp_path)


def test_actual_selected_network_and_start_rule_overrides_are_attested(tmp_path,monkeypatch):
    import bitcoin
    import config
    (tmp_path/'parser.py').write_text('pass\n')
    original=bitcoin.params.NAME
    try:
        bitcoin.SelectParams('testnet')
        monkeypatch.setattr(config,'TESTNET',None)
        monkeypatch.setattr(config,'BLOCK_FIRST',2979826)
        first=collect_indexer_source_metadata(tmp_path)
        assert first['effective_protocol']['bitcoin_network'] == 'testnet'
        assert first['effective_protocol']['testnet'] is None
        assert first['effective_protocol']['parser_start_height'] == 2979826
        monkeypatch.setattr(config,'BLOCK_FIRST',3000000)
        monkeypatch.setattr(config,'DEBUG_SKIP_REBUILD_BALANCES',True)
        second=collect_indexer_source_metadata(tmp_path)
        assert first['source_digest_sha256'] == second['source_digest_sha256']
        assert first['effective_protocol'] != second['effective_protocol']
        assert second['effective_protocol']['validation']['skip_rebuild_balances'] is True
    finally:
        bitcoin.SelectParams(original)
