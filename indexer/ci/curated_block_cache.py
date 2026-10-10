"""Read verified, content-addressed CI inputs; never synthesizes chain data."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from bitcoin.core import CBlock, Hash

GENESIS = "000000000019d6689c085ae165831e934ff763ae46a2a6c172b3f1b60a8ce26f"


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate cache manifest key")
        result[key] = value
    return result


def verify_block(raw: bytes, expected_hash: str) -> CBlock:
    if not 81 <= len(raw) <= 4_194_304:
        raise ValueError("Invalid cached block size")
    digest = hashlib.sha256(hashlib.sha256(raw[:80]).digest()).digest()[::-1].hex()
    if digest != expected_hash:
        raise ValueError("Cached block header hash mismatch")
    block = CBlock.deserialize(raw)
    if block.hashMerkleRoot != block.calc_merkle_root():
        raise ValueError("Cached block transaction Merkle root mismatch")
    if block.vWitnessMerkleTree:
        stack = block.vtx[0].wit.vtxinwit[0].scriptWitness.stack
        if len(stack) != 1 or len(stack[0]) != 32:
            raise ValueError("Invalid cached coinbase witness nonce")
        output = block.vtx[0].vout[block.get_witness_commitment_index()]
        commitment = bytes(output.scriptPubKey)[6:38]
        if commitment != Hash(block.calc_witness_merkle_root() + stack[0]):
            raise ValueError("Cached block witness commitment mismatch")
    return block


class CuratedBlockCache:
    def __init__(self, root: Path, baseline_file: Path | None = None):
        self.root = root
        manifest_file = root / "capture-receipt.json"
        if root.is_symlink() or manifest_file.is_symlink() or manifest_file.stat().st_size > 65_536:
            raise ValueError("Invalid cache manifest path")
        self.manifest = json.loads(manifest_file.read_bytes(), object_pairs_hook=_unique)
        baseline_file = baseline_file or Path(__file__).resolve().parents[1] / "snapshots" / "ci_consensus_hashes.json"
        # Git text checkout may use CRLF; the packaged baseline digest pins LF.
        baseline_raw = baseline_file.read_bytes().replace(b"\r\n", b"\n")
        baseline = json.loads(baseline_raw, object_pairs_hook=_unique)["hashes"]
        records = self.manifest["records"]
        if (
            self.manifest["genesisHash"] != GENESIS
            or self.manifest["baselineSHA256"] != hashlib.sha256(baseline_raw).hexdigest()
        ):
            raise ValueError("Cache network/baseline mismatch")
        if set(records) != set(baseline) or any(records[h]["blockHash"] != baseline[h]["block_hash"] for h in records):
            raise ValueError("Cache does not cover the exact curated baseline")
        self.hashes = {int(height): record["blockHash"] for height, record in records.items()}
        self.records = {record["blockHash"]: record for record in records.values()}

    def block_hash(self, height: int) -> str:
        return self.hashes[height]

    def block_bytes(self, block_hash: str) -> bytes:
        record = self.records[block_hash]
        file = self.root / "blocks" / (block_hash + ".bin")
        if file.is_symlink() or not 81 <= record["bytes"] <= 4_194_304:
            raise ValueError("Invalid cached block path/size")
        fd = os.open(file, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            before = os.fstat(fd)
            if before.st_size != record["bytes"]:
                raise ValueError("Cached block size mismatch")
            with os.fdopen(fd, "rb", closefd=False) as stream:
                raw = stream.read(4_194_305)
            after = os.fstat(fd)
            if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
            ):
                raise ValueError("Cached block changed during read")
        finally:
            os.close(fd)
        if len(raw) != record["bytes"] or hashlib.sha256(raw).hexdigest() != record["sha256"]:
            raise ValueError("Cached block content digest mismatch")
        verify_block(raw, block_hash)
        return raw


def configured_cache():
    root = os.environ.get("CI_CURATED_BLOCK_CACHE", "")
    return CuratedBlockCache(Path(root)) if root else None
