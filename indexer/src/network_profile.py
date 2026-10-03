"""Bitcoin network profile for the Stamps indexer.

Mainnet is the default and keeps the protocol's published activation heights
(Stamps / SRC-20 / SRC-721 / SRC-101 and the consensus feature flags) exactly as
they were. Any other chain is a separate deployment whose activation heights are
deployment parameters: a Signet profile must name its challenge, its own
Counterparty origin and every activation height explicitly. Nothing is inferred
from mainnet, and the indexer refuses to start when the Bitcoin backend or the
Counterparty node reports a different chain than the one configured.

Environment:
  STAMPS_NETWORK            mainnet (default) | signet
  STAMPS_SIGNET_CHALLENGE   hex signet challenge script (signet only, required)
  STAMPS_ACTIVATION_HEIGHTS JSON object with every key of ACTIVATION_HEIGHT_KEYS
                            (signet only, required; refused on mainnet)
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional

from exceptions import ConfigurationError

# Mainnet activation heights (Bitcoin Stamps protocol history; unchanged).
MAINNET_ACTIVATION_HEIGHTS: Dict[str, int] = {
    "CP_STAMP_GENESIS_BLOCK": 779652,  # first valid Classic Stamp (Counterparty issuance)
    "CP_SRC20_GENESIS_BLOCK": 788041,  # first SRC-20 on Counterparty
    "BTC_SRC20_GENESIS_BLOCK": 793068,  # first SRC-20 without Counterparty encoding
    "BTC_SRC20_OLGA_BLOCK": 865000,  # first SRC-20 with P2WSH OLGA encoding
    "CP_SRC721_GENESIS_BLOCK": 792370,  # first SRC-721
    "BTC_SRC101_GENESIS_BLOCK": 870652,  # first SRC-101
    "BTC_SRC101_IMG_OPTIONAL_BLOCK": 872200,
    "BTC_SRC101_OLGA_BLOCK": 940000,  # P2WSH/OLGA encoding for SRC-101
    "CP_SRC20_END_BLOCK": 796000,  # last SRC-20 on Counterparty
    "CP_BMN_FEAT_BLOCK_START": 815130,  # BMN audio file support
    "CP_P2WSH_FEAT_BLOCK_START": 833000,  # OLGA / P2WSH stamps
    "CP_SUBASSET_FEAT_BLOCK_START": 866000,  # subassets without XCP fees
    "STRIP_WHITESPACE": 797200,
    "STOP_BASE64_REPAIR": 784550,
    "SVG_GZIP_DETECTION_V2": 999999,
    "ENHANCED_MIME_DETECTION": 999999,
}
ACTIVATION_HEIGHT_KEYS = tuple(MAINNET_ACTIVATION_HEIGHTS.keys())

# Bitcoin Core `getblockchaininfo().chain` per profile.
_BITCOIN_CORE_CHAIN = {"mainnet": "main", "signet": "signet"}
# Counterparty Core v2 `GET /v2/` `network` per profile.
_COUNTERPARTY_NETWORK = {"mainnet": "mainnet", "signet": "signet"}
_HEX = re.compile(r"^(?:[0-9a-f]{2})+$")


@dataclass(frozen=True)
class NetworkProfile:
    name: str
    bech32_hrp: str
    p2pkh_version: int
    p2sh_version: int
    activation_heights: Dict[str, int] = field(default_factory=dict)
    signet_challenge: Optional[str] = None

    @property
    def is_mainnet(self) -> bool:
        return self.name == "mainnet"

    @property
    def bitcoin_core_chain(self) -> str:
        return _BITCOIN_CORE_CHAIN[self.name]

    @property
    def counterparty_network(self) -> str:
        return _COUNTERPARTY_NETWORK[self.name]

    @property
    def block_first(self) -> int:
        return self.activation_heights["CP_STAMP_GENESIS_BLOCK"]


def _parse_heights(raw: str) -> Dict[str, int]:
    try:
        value = json.loads(raw)
    except ValueError as exc:
        raise ConfigurationError(f"STAMPS_ACTIVATION_HEIGHTS is not valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ConfigurationError("STAMPS_ACTIVATION_HEIGHTS must be a JSON object")
    missing = [key for key in ACTIVATION_HEIGHT_KEYS if key not in value]
    unknown = sorted(set(value) - set(ACTIVATION_HEIGHT_KEYS))
    if missing or unknown:
        raise ConfigurationError(
            f"STAMPS_ACTIVATION_HEIGHTS must name exactly {list(ACTIVATION_HEIGHT_KEYS)}; "
            f"missing {missing}, unknown {unknown}"
        )
    heights: Dict[str, int] = {}
    for key in ACTIVATION_HEIGHT_KEYS:
        height = value[key]
        if isinstance(height, bool) or not isinstance(height, int) or height < 0:
            raise ConfigurationError(f"STAMPS_ACTIVATION_HEIGHTS.{key} must be a non-negative integer")
        heights[key] = height
    if heights["CP_SRC20_END_BLOCK"] < heights["CP_SRC20_GENESIS_BLOCK"]:
        raise ConfigurationError("STAMPS_ACTIVATION_HEIGHTS: CP_SRC20_END_BLOCK precedes CP_SRC20_GENESIS_BLOCK")
    first = heights["CP_STAMP_GENESIS_BLOCK"]
    for key in ("CP_SRC20_GENESIS_BLOCK", "BTC_SRC20_GENESIS_BLOCK", "CP_SRC721_GENESIS_BLOCK", "BTC_SRC101_GENESIS_BLOCK"):
        if heights[key] < first:
            raise ConfigurationError(
                f"STAMPS_ACTIVATION_HEIGHTS.{key} precedes CP_STAMP_GENESIS_BLOCK (indexing starts there)"
            )
    return heights


def resolve_profile(env: Mapping[str, str]) -> NetworkProfile:
    """Resolve the one network this deployment indexes; refuse anything ambiguous."""
    name = (env.get("STAMPS_NETWORK") or "mainnet").strip().lower()
    challenge = (env.get("STAMPS_SIGNET_CHALLENGE") or "").strip().lower()
    heights_raw = (env.get("STAMPS_ACTIVATION_HEIGHTS") or "").strip()
    legacy_testnet = (env.get("TESTNET") or "").strip()
    if name == "mainnet":
        if challenge:
            raise ConfigurationError("STAMPS_SIGNET_CHALLENGE is only valid with STAMPS_NETWORK=signet")
        if heights_raw:
            raise ConfigurationError("STAMPS_ACTIVATION_HEIGHTS cannot override the Mainnet protocol activation heights")
        return NetworkProfile(
            name="mainnet",
            bech32_hrp="bc",
            p2pkh_version=0x00,
            p2sh_version=0x05,
            activation_heights=dict(MAINNET_ACTIVATION_HEIGHTS),
        )
    if name == "signet":
        if legacy_testnet:
            raise ConfigurationError("TESTNET cannot be combined with STAMPS_NETWORK=signet")
        if not _HEX.match(challenge):
            raise ConfigurationError("STAMPS_NETWORK=signet requires STAMPS_SIGNET_CHALLENGE (hex challenge script)")
        if not heights_raw:
            raise ConfigurationError(
                "STAMPS_NETWORK=signet requires STAMPS_ACTIVATION_HEIGHTS (deployment activation heights)"
            )
        return NetworkProfile(
            name="signet",
            bech32_hrp="tb",
            p2pkh_version=0x6F,
            p2sh_version=0xC4,
            activation_heights=_parse_heights(heights_raw),
            signet_challenge=challenge,
        )
    raise ConfigurationError(f"Unsupported STAMPS_NETWORK {name!r} (mainnet or signet)")


def verify_bitcoin_core(profile: NetworkProfile, blockchain_info: Mapping[str, Any]) -> None:
    """Fail closed unless Bitcoin Core serves exactly the configured chain."""
    chain = str((blockchain_info or {}).get("chain") or "")
    if chain != profile.bitcoin_core_chain:
        raise ConfigurationError(f"Bitcoin backend serves chain {chain!r}, but this indexer is configured for {profile.name}")
    if profile.signet_challenge is not None:
        observed = str((blockchain_info or {}).get("signet_challenge") or "").strip().lower()
        if observed != profile.signet_challenge:
            raise ConfigurationError("Bitcoin backend Signet challenge does not match STAMPS_SIGNET_CHALLENGE")


def verify_counterparty(profile: NetworkProfile, node_name: str, root: Mapping[str, Any]) -> None:
    """Fail closed unless the Counterparty node reports the configured network."""
    result = (root or {}).get("result", root) or {}
    network = str(result.get("network") or "")
    if network != profile.counterparty_network:
        raise ConfigurationError(
            f"Counterparty node {node_name} serves network {network!r}, but this indexer is configured for {profile.name}"
        )
