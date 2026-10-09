"""Network profile: Mainnet unchanged, Signet as an explicit deployment, fail closed on mismatch."""

import json
import os
import subprocess  # nosec B404 - runs this interpreter on a fixed module import
import sys

import pytest

from exceptions import ConfigurationError
from network_profile import (
    ACTIVATION_HEIGHT_KEYS,
    MAINNET_ACTIVATION_HEIGHTS,
    resolve_profile,
    verify_bitcoin_core,
    verify_counterparty,
)

CHALLENGE = "5121" + "02" + "11" * 32 + "51ae"
SIGNET_HEIGHTS = {key: 2000 for key in ACTIVATION_HEIGHT_KEYS}
SIGNET_ENV = {
    "STAMPS_NETWORK": "signet",
    "STAMPS_SIGNET_CHALLENGE": CHALLENGE,
    "STAMPS_ACTIVATION_HEIGHTS": json.dumps(SIGNET_HEIGHTS),
}
SRC = os.path.join(os.path.dirname(__file__), "..", "src")


def test_mainnet_is_the_default_and_keeps_protocol_heights():
    profile = resolve_profile({})
    assert profile.name == "mainnet"
    assert profile.bech32_hrp == "bc"
    assert profile.activation_heights == MAINNET_ACTIVATION_HEIGHTS
    assert profile.block_first == 779652
    assert profile.activation_heights["BTC_SRC20_GENESIS_BLOCK"] == 793068
    assert profile.activation_heights["BTC_SRC101_GENESIS_BLOCK"] == 870652


def test_mainnet_heights_cannot_be_overridden():
    with pytest.raises(ConfigurationError):
        resolve_profile({"STAMPS_ACTIVATION_HEIGHTS": json.dumps(SIGNET_HEIGHTS)})
    with pytest.raises(ConfigurationError):
        resolve_profile({"STAMPS_SIGNET_CHALLENGE": CHALLENGE})


def test_signet_profile_uses_deployment_parameters():
    profile = resolve_profile(SIGNET_ENV)
    assert profile.name == "signet"
    assert profile.bech32_hrp == "tb"
    assert (profile.p2pkh_version, profile.p2sh_version) == (0x6F, 0xC4)
    assert profile.signet_challenge == CHALLENGE
    assert profile.block_first == 2000
    assert profile.activation_heights == SIGNET_HEIGHTS


@pytest.mark.parametrize(
    "change",
    [
        {"STAMPS_SIGNET_CHALLENGE": ""},
        {"STAMPS_SIGNET_CHALLENGE": "xyz"},
        {"STAMPS_ACTIVATION_HEIGHTS": ""},
        {"STAMPS_ACTIVATION_HEIGHTS": "[1]"},
        {
            "STAMPS_ACTIVATION_HEIGHTS": json.dumps(
                {k: v for k, v in SIGNET_HEIGHTS.items() if k != "BTC_SRC101_GENESIS_BLOCK"}
            )
        },
        {"STAMPS_ACTIVATION_HEIGHTS": json.dumps({**SIGNET_HEIGHTS, "EXTRA": 1})},
        {"STAMPS_ACTIVATION_HEIGHTS": json.dumps({**SIGNET_HEIGHTS, "STRIP_WHITESPACE": -1})},
        {"STAMPS_ACTIVATION_HEIGHTS": json.dumps({**SIGNET_HEIGHTS, "STRIP_WHITESPACE": "1"})},
        {"STAMPS_ACTIVATION_HEIGHTS": json.dumps({**SIGNET_HEIGHTS, "BTC_SRC20_GENESIS_BLOCK": 10})},
        {"STAMPS_ACTIVATION_HEIGHTS": json.dumps({**SIGNET_HEIGHTS, "CP_SRC20_END_BLOCK": 1999})},
        {"TESTNET": "1"},
        {"STAMPS_NETWORK": "testnet4"},
    ],
)
def test_signet_profile_fails_closed_on_incomplete_or_ambiguous_config(change):
    with pytest.raises(ConfigurationError):
        resolve_profile({**SIGNET_ENV, **change})


def test_bitcoin_core_chain_and_challenge_must_match():
    signet = resolve_profile(SIGNET_ENV)
    verify_bitcoin_core(signet, {"chain": "signet", "signet_challenge": CHALLENGE.upper()})
    with pytest.raises(ConfigurationError):
        verify_bitcoin_core(signet, {"chain": "signet", "signet_challenge": "512103" + "22" * 32 + "51ae"})
    with pytest.raises(ConfigurationError):
        verify_bitcoin_core(signet, {"chain": "main"})
    mainnet = resolve_profile({})
    verify_bitcoin_core(mainnet, {"chain": "main"})
    with pytest.raises(ConfigurationError):
        verify_bitcoin_core(mainnet, {"chain": "signet", "signet_challenge": CHALLENGE})


def test_counterparty_network_must_match():
    signet = resolve_profile(SIGNET_ENV)
    verify_counterparty(signet, "local", {"result": {"network": "signet"}})
    for root in ({"result": {"network": "mainnet"}}, {"result": {}}, {}):
        with pytest.raises(ConfigurationError):
            verify_counterparty(signet, "local", root)
    verify_counterparty(resolve_profile({}), "public", {"result": {"network": "mainnet"}})


def _import_config(env):
    """Import config.py in a fresh interpreter with exactly this profile environment."""
    clean = {k: v for k, v in os.environ.items() if not k.startswith(("STAMPS_", "CP_")) and k != "TESTNET"}
    clean.update({"RPC_USER": "u", "RPC_PASSWORD": "p", "RPC_IP": "127.0.0.1", "RPC_PORT": "1", "TESTING": "1", **env})
    code = (
        "import json, config; print(json.dumps({'network': config.NETWORK, 'first': config.BLOCK_FIRST_SIGNET, "
        "'stamp': config.CP_STAMP_GENESIS_BLOCK, 'src101': config.BTC_SRC101_GENESIS_BLOCK, "
        "'nodes': [n['url'] for n in config.XCP_V2_NODES]}))"
    )
    return subprocess.run([sys.executable, "-c", code], cwd=SRC, env=clean, capture_output=True, text=True)  # nosec B603


def test_signet_config_has_no_public_counterparty_fallback():
    result = _import_config({**SIGNET_ENV, "CP_RPC_URL": "http://127.0.0.1:38356/v2"})
    assert result.returncode == 0, result.stderr
    loaded = json.loads(result.stdout.strip().splitlines()[-1])
    assert loaded == {
        "network": "signet",
        "first": 2000,
        "stamp": 2000,
        "src101": 2000,
        "nodes": ["http://127.0.0.1:38356/v2"],
    }


def test_signet_config_without_counterparty_node_refuses_to_load():
    result = _import_config(SIGNET_ENV)
    assert result.returncode != 0
    assert "requires its own Counterparty node" in result.stderr


def test_mainnet_config_still_adds_the_public_fallback():
    result = _import_config({"CP_RPC_URL": "http://127.0.0.1:4000"})
    assert result.returncode == 0, result.stderr
    loaded = json.loads(result.stdout.strip().splitlines()[-1])
    assert loaded["network"] == "mainnet" and loaded["stamp"] == 779652
    assert loaded["nodes"] == ["http://127.0.0.1:4000/v2", "https://api.counterparty.io:4000/v2"]
