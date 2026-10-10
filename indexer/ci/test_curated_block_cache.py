import hashlib
import json
import sys
import tempfile
import unittest
import urllib.request
from pathlib import Path

from bitcoin import params

sys.path.insert(0, str(Path(__file__).resolve().parent))
from curated_block_cache import GENESIS, CuratedBlockCache, verify_block
from fetch_curated_block_cache import ArtifactRedirect


class CuratedCacheControls(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "blocks").mkdir()
        self.raw = params.GENESIS_BLOCK.serialize()
        self.file = self.root / "blocks" / (GENESIS + ".bin")
        self.file.write_bytes(self.raw)
        self.baseline = self.root / "baseline.json"
        self.baseline.write_text(json.dumps({"hashes": {"0": {"block_hash": GENESIS}}}))
        self.record = {"blockHash": GENESIS, "bytes": len(self.raw), "sha256": hashlib.sha256(self.raw).hexdigest()}
        self.manifest = {
            "genesisHash": GENESIS,
            "baselineSHA256": hashlib.sha256(self.baseline.read_bytes()).hexdigest(),
            "records": {"0": self.record},
        }
        self.save_manifest()

    def save_manifest(self):
        (self.root / "capture-receipt.json").write_text(json.dumps(self.manifest))

    def cache(self):
        return CuratedBlockCache(self.root, self.baseline)

    def test_exact_real_genesis_and_absent_height(self):
        cache = self.cache()
        self.assertEqual(cache.block_hash(0), GENESIS)
        self.assertEqual(cache.block_bytes(GENESIS), self.raw)
        with self.assertRaises(KeyError):
            cache.block_hash(1)

    def test_transaction_tampering_fails_even_with_original_header_and_replaced_digest(self):
        bad = self.raw[:-1] + bytes([self.raw[-1] ^ 1])
        self.file.write_bytes(bad)
        self.record["sha256"] = hashlib.sha256(bad).hexdigest()
        self.save_manifest()
        with self.assertRaisesRegex(ValueError, "Merkle"):
            self.cache().block_bytes(GENESIS)

    def test_truncation_and_content_digest_mismatch(self):
        self.file.write_bytes(self.raw[:-1])
        with self.assertRaisesRegex(ValueError, "size"):
            self.cache().block_bytes(GENESIS)
        self.file.write_bytes(self.raw)
        self.record["sha256"] = "0" * 64
        self.save_manifest()
        with self.assertRaisesRegex(ValueError, "digest"):
            self.cache().block_bytes(GENESIS)

    def test_header_hash_mismatch(self):
        with self.assertRaisesRegex(ValueError, "header"):
            verify_block(self.raw, "0" * 64)

    def test_network_baseline_and_membership_changes_refused(self):
        for field in ["genesisHash", "baselineSHA256"]:
            original = self.manifest[field]
            self.manifest[field] = "0" * 64
            self.save_manifest()
            with self.assertRaisesRegex(ValueError, "network/baseline"):
                self.cache()
            self.manifest[field] = original
        self.manifest["records"]["1"] = self.record
        self.save_manifest()
        with self.assertRaisesRegex(ValueError, "exact curated baseline"):
            self.cache()

    def test_duplicate_manifest_keys_refused(self):
        (self.root / "capture-receipt.json").write_text('{"records": {}, "records": {}}')
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            self.cache()

    def test_redirect_strips_authorization_and_refuses_other_origins(self):
        request = urllib.request.Request("https://api.github.com/example", headers={"Authorization": "test-only"})
        redirect = ArtifactRedirect()
        result = redirect.redirect_request(
            request, None, 302, "Found", {}, "https://release-assets.githubusercontent.com/example"
        )
        self.assertIsNone(result.get_header("Authorization"))
        for url in [
            "https://example.com/asset",
            "http://api.github.com/asset",
            "https://api.github.com:444/asset",
            "https://user@api.github.com/asset",
        ]:
            with self.assertRaisesRegex(ValueError, "origin"):
                redirect.redirect_request(request, None, 302, "Found", {}, url)


if __name__ == "__main__":
    unittest.main()
