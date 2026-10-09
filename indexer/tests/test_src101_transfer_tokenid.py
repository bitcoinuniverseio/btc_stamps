"""SRC-101 TRANSFER owner rows: list tokenids and the single-string form both update one row per name."""

from unittest import mock

import pytest

from index_core import src101


def _transfer(tokenid, tokenid_utf8):
    return {
        "valid": 1,
        "p": "SRC-101",
        "op": "TRANSFER",
        "deploy_hash": "d" * 64,
        "tokenid": tokenid,
        "tokenid_utf8": tokenid_utf8,
        "src101_owner": "tb1qowner",
        "src101_preowner": "tb1qprev",
        "expire_timestamp": 2000000000,
    }


@pytest.mark.parametrize(
    ("tokenid", "tokenid_utf8"),
    [(["YWxpY2U="], ["alice"]), ("YWxpY2U=", "alice")],
)
def test_transfer_updates_one_owner_row_per_name(tokenid, tokenid_utf8):
    with mock.patch.object(src101, "update_owner_table") as update:
        rows = src101.update_src101_owners(mock.MagicMock(), 2139, [_transfer(tokenid, tokenid_utf8)])
    assert [(r["tokenid"], r["tokenid_utf8"], r["owner"]) for r in rows] == [("YWxpY2U=", "alice", "tb1qowner")]
    update.assert_called_once()
