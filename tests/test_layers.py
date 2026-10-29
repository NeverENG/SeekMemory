from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from layers import ALL_LAYERS, _layer_for, files_for  # noqa: E402


class LayerMapTest(unittest.TestCase):
    def test_every_test_file_has_a_layer(self) -> None:
        mapped = set(files_for("all"))
        actual = {path.name for path in ROOT.glob("tests/test_*.py")}
        self.assertEqual(sorted(actual - mapped), [])
        self.assertEqual(sorted(mapped - actual), [])

    def test_every_layer_has_at_least_one_test(self) -> None:
        for layer in ALL_LAYERS:
            self.assertTrue(files_for(layer), layer)

    def test_layers_partition_all_files_without_duplicates(self) -> None:
        found = [name for layer in ALL_LAYERS for name in files_for(layer)]
        self.assertEqual(len(found), len(set(found)))
        self.assertEqual(set(found), set(files_for("all")))

    def test_explicit_suffix_overrides_legacy_integration_markers(self) -> None:
        for layer in ALL_LAYERS:
            self.assertEqual(_layer_for(Path(f"test_runtime_recall_{layer}.py")), layer)


if __name__ == "__main__":
    unittest.main()
