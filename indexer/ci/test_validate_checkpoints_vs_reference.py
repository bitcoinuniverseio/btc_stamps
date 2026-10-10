import tempfile
import unittest
from pathlib import Path

from validate_checkpoints_vs_reference import parse_checkpoints


class MainnetProfileCheckpoints(unittest.TestCase):
    def test_profile_height_is_read_without_executing_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "network_profile.py").write_text(
                'raise RuntimeError("must not execute")\n' 'MAINNET_ACTIVATION_HEIGHTS: dict[str, int] = {"GENESIS": 779652}\n'
            )
            (root / "config.py").write_text(
                'raise RuntimeError("must not execute")\n'
                "_HEIGHTS = NETWORK_PROFILE.activation_heights\n"
                'GENESIS: int = _HEIGHTS["GENESIS"]\n'
            )
            (root / "check.py").write_text('CHECKPOINTS_MAINNET = {config.GENESIS: {"txlist_hash": "expected"}}\n')
            self.assertEqual(
                parse_checkpoints(root / "check.py", root / "config.py"),
                {779652: {"txlist_hash": "expected"}},
            )
            (root / "network_profile.py").write_text('MAINNET_ACTIVATION_HEIGHTS: dict[str, int] = {"GENESIS": 1}\n')
            self.assertEqual(set(parse_checkpoints(root / "check.py", root / "config.py")), {1})

    def test_missing_profile_height_refuses_instead_of_using_mainnet_literal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "config.py").write_text('_HEIGHTS = NETWORK_PROFILE.activation_heights\nGENESIS = _HEIGHTS["GENESIS"]\n')
            (root / "check.py").write_text("CHECKPOINTS_MAINNET = {config.GENESIS: {}}\n")
            with self.assertRaisesRegex(RuntimeError, "activation height GENESIS not found"):
                parse_checkpoints(root / "check.py", root / "config.py")


if __name__ == "__main__":
    unittest.main()
