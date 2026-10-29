"""Protect the supported core/application import direction.

保护已支持的领域及应用导入方向。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ast

class ImportBoundaryTest(unittest.TestCase):
    def _imports(self, path):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        out = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                out.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                out.append(node.module)
        return out
    def test_core_and_app_do_not_import_adapters(self):
        root = Path(__file__).resolve().parents[1]
        forbidden = ("astrbot", "store", "recall", "perceive", "maintain", "main")
        for folder in (root / "core", root / "app"):
            for path in folder.glob("*.py"):
                for name in self._imports(path):
                    self.assertFalse(name.split(".")[0] in forbidden, f"{path}: {name}")


if __name__ == "__main__":
    unittest.main()
