"""Record actual parser source bytes and effective rules, without claiming approval."""
import hashlib
import json
import os
import re
from pathlib import Path

import config


def collect_indexer_source_metadata(source_root=None):
    source_root = Path(source_root) if source_root is not None else Path(__file__).resolve().parents[1]
    source_files = {}
    for path in sorted(source_root.rglob("*.py")):
        if path.is_symlink():
            raise ValueError("Parser source attestation cannot follow symbolic links")
        relative = "indexer/src/" + path.relative_to(source_root).as_posix()
        source_files[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    if not source_files:
        raise ValueError("Parser source attestation found no source files")
    canonical = json.dumps(source_files, sort_keys=True, separators=(",", ":")).encode("utf-8")
    build_id = os.environ.get("STAMPS_APPROVED_BUILD_ID")
    if build_id is not None and not re.fullmatch(r"[A-Za-z0-9_.:/+-]{1,160}", build_id):
        raise ValueError("Parser build identifier has invalid syntax")
    activations = {
        name: value for name, value in vars(config).items()
        if name.isupper() and re.search(r"(?:_BLOCK|_BLOCK_START|_BLOCK_END)$", name)
        and isinstance(value, int) and not isinstance(value, bool)
    }
    return {
        "schema": "stamps-parser-source-v1",
        "build_id": build_id,
        "source_digest_sha256": hashlib.sha256(canonical).hexdigest(),
        "source_files": source_files,
        "effective_protocol": {
            "activations": activations,
            "testnet": getattr(config, "TESTNET", None),
            "regtest": getattr(config, "REGTEST", None),
            "network_profile": os.environ.get("STAMPS_NETWORK"),
            "signet_challenge": os.environ.get("STAMPS_SIGNET_CHALLENGE"),
        },
    }
