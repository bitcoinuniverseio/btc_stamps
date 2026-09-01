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
