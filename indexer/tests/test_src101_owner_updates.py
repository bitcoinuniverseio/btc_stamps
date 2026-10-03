"""Owner row regressions; run with the repository test environment."""
from copy import deepcopy
from unittest.mock import patch

import pytest

from index_core.src101 import Src101Validator, update_src101_owners


@pytest.fixture
def transfer():
    row = {
        "p": "SRC-101", "op": "TRANSFER", "valid": 1,
        "deploy_hash": "a" * 64, "tokenid": "YWxpY2U=",
        "src101_owner": "new-owner", "src101_preowner": "prior-owner",
        "expire_timestamp": 2_000_000_000,
    }
    validator = Src101Validator(row)
    validator._process_tokenid_value("tokenid", row["tokenid"])
    assert not validator.validation_errors
    return row


def apply(rows):
    with patch("index_core.src101.update_owner_table") as writer:
        result = update_src101_owners(None, 940001, deepcopy(rows))
    if result:
        writer.assert_called_once_with(None, result, 940001)
    else:
        writer.assert_not_called()
    return result


def test_scalar_transfer_preserves_entire_identity(transfer):
    row, = apply([transfer])
    assert (row["tokenid"], row["tokenid_utf8"]) == ("YWxpY2U=", "alice")
    assert row["owner"] == "new-owner"
    assert row["preowner"] == "prior-owner"
    assert row["expire_timestamp"] == 2_000_000_000
    assert row["prim"] is False
    assert all(row[key] is None for key in ("address_btc", "address_eth", "txt_data"))


def test_repeated_transfer_is_scalar_and_uses_last_owner(transfer):
    later = dict(transfer, src101_owner="last-owner", src101_preowner="new-owner")
    row, = apply([transfer, later])
    assert row["owner"] == "last-owner"
    assert row["preowner"] == "new-owner"
    assert type(row["owner"]) is str


def test_renew_after_transfer_keeps_expiry_scalar(transfer):
    later = dict(transfer, op="RENEW", expire_timestamp=2_031_536_000)
    row, = apply([transfer, later])
    assert row["expire_timestamp"] == 2_031_536_000
    assert type(row["expire_timestamp"]) is int


def test_mint_then_transfer_retains_image_and_clears_records(transfer):
    mint = dict(transfer, op="MINT", tokenid=["YWxpY2U="], tokenid_utf8=["alice"],
                src101_owner="prior-owner", src101_preowner=[None],
                txt_data={"old": "record"}, prim=True, img=["https://example.invalid/alice.png"])
    row, = apply([mint, transfer])
    assert row["owner"] == "new-owner"
    assert row["img"] == "https://example.invalid/alice.png"
    assert row["prim"] is False
    assert all(row[key] is None for key in ("address_btc", "address_eth", "txt_data"))


def test_record_then_transfer_resets_primary_and_records(transfer):
    record = dict(transfer, op="SETRECORD", txt_data={"old": "record"},
                  address_btc="old-address", address_eth="old-eth", prim=True)
    row, = apply([record, transfer])
    assert row["prim"] is False
    assert all(row[key] is None for key in ("address_btc", "address_eth", "txt_data"))


def test_transfer_then_record_updates_primary(transfer):
    record = dict(transfer, op="SETRECORD", txt_data={"new": "record"},
                  address_btc="new-address", address_eth=None, prim=True)
    row, = apply([transfer, record])
    assert row["prim"] is True
    assert row["address_btc"] == "new-address"
    assert row["txt_data"] == {"new": "record"}


def test_invalid_transfer_produces_no_owner_write(transfer):
    assert apply([dict(transfer, valid=0)]) == []


def test_same_token_in_distinct_deployments_stays_distinct(transfer):
    other = dict(transfer, deploy_hash="b" * 64, src101_owner="other-owner")
    rows = apply([transfer, other])
    assert len(rows) == 2
    assert {row["deploy_hash"] for row in rows} == {"a" * 64, "b" * 64}
