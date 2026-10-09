from unittest.mock import patch

import pytest

from index_core.util import decode_address


@pytest.mark.parametrize(
    ("script_hex", "expected"),
    [
        (
            "76a91477bff20c60e522dfaa3350c39b030a5d004e839a88ac",
            "1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2",
        ),
        (
            "a914b472a266d0bd89c13706a4132ccfb16f7c3b9fcb87",
            "3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy",
        ),
    ],
)
def test_decode_legacy_mainnet_address(script_hex, expected):
    with patch("index_core.util.config.TESTNET", False):
        assert decode_address(bytes.fromhex(script_hex)) == expected


def test_decode_address_rejects_unknown_script():
    with pytest.raises(ValueError, match="Unsupported scriptPubKey format"):
        decode_address(b"\x6a\x01\x00")


@pytest.mark.parametrize(
    ("script_hex", "expected"),
    [
        # BIP-173 P2WPKH test vector, Signet/Testnet human-readable part.
        ("0014751e76e8199196d454941c45d1b3a323f1433bd6", "tb1qw508d6qejxtdg4y5r3zarvary0c5xw7kxpjzsx"),
        # P2PKH and P2SH on the test-chain version bytes.
        ("76a914000102030405060708090a0b0c0d0e0f1011121388ac", "mfWyW5fc9NUj75YAnFgoRLrjxgLDn2MMth"),
        ("a914000102030405060708090a0b0c0d0e0f1011121387", "2MsFFCK16VhsCcvPXruztdzzcTZEQCbNKjJ"),
    ],
)
def test_decode_signet_address_uses_test_chain_encoding(script_hex, expected):
    with patch("index_core.util.config.TESTNET", None), patch("index_core.util.config.SIGNET", True):
        assert decode_address(bytes.fromhex(script_hex)) == expected
