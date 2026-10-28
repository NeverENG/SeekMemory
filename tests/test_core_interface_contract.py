"""Core interface compatibility / core 统一接口的兼容性约定。"""

from __future__ import annotations

import ast
import importlib
import inspect
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import interfaces  # noqa: E402


class CoreInterfaceContractTest(unittest.TestCase):
    def test_every_export_resolves_without_placeholder_operations(self) -> None:
        """Exports are the existing values/functions, not empty stubs / 导出沿用原对象，不是空函数。"""
        self.assertEqual(len(interfaces.__all__), len(set(interfaces.__all__)))
        self.assertTrue(set(interfaces.__all__).issubset(dir(interfaces)))
        for name in interfaces.__all__:
            with self.subTest(name=name):
                self.assertIsNotNone(getattr(interfaces, name))
        art = interfaces.make("memory", {"text": "a fact", "level": "fact"})
        interfaces.validate(art)
        changed = interfaces.revise(art, {"text": "updated", "level": "fact"})
        self.assertEqual(interfaces.content_of(changed), "updated")
        self.assertEqual(changed.header.id, art.header.id)
        self.assertEqual(changed.header.revision, 2)
        self.assertEqual(art.payload["text"], "a fact")

    def test_existing_public_symbols_keep_identity_through_the_interface(self) -> None:
        """One entry exposes the existing domain surface / 单一入口导出已有领域能力。"""
        for path in sorted((ROOT / "core").glob("*.py")):
            if path.stem.startswith("_") or path.stem == "interfaces":
                continue
            module = importlib.import_module(f"core.{path.stem}")
            tree = ast.parse(path.read_text(encoding="utf-8"))
            names = []
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                    names.append(node.name)
                elif isinstance(node, ast.Assign):
                    names.extend(t.id for t in node.targets if isinstance(t, ast.Name))
                elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                    names.append(node.target.id)
            for name in names:
                if not name.startswith("_"):
                    with self.subTest(module=module.__name__, name=name):
                        self.assertIn(name, interfaces.__all__)
                        self.assertIs(getattr(interfaces, name), getattr(module, name))

    def test_previous_protocol_imports_are_aliases_of_the_single_declaration(self) -> None:
        """Legacy protocol imports remain valid / 原接口导入路径继续有效。"""
        from core.graph import GraphArtifactStore
        from core.tree import TreeArtifactStore, TreeCache

        for old in (GraphArtifactStore, TreeArtifactStore, TreeCache):
            self.assertIs(old, getattr(interfaces, old.__name__))
            self.assertEqual(old.__module__, "core.interfaces")

    def test_storage_protocol_call_shapes_match_the_existing_implementations(self) -> None:
        """Moving declarations keeps call arguments unchanged / 迁移声明不改变调用参数。"""
        from store.artifacts import ArtifactRepository
        from store.cache import Cache

        for protocol, implementation in (
            (interfaces.GraphArtifactStore, ArtifactRepository),
            (interfaces.TreeArtifactStore, ArtifactRepository),
            (interfaces.TreeCache, Cache),
        ):
            for name, method in vars(protocol).items():
                if name.startswith("_") or not inspect.isfunction(method):
                    continue
                declared = inspect.signature(method).parameters
                actual = inspect.signature(getattr(implementation, name)).parameters
                with self.subTest(protocol=protocol.__name__, method=name):
                    self.assertEqual(list(declared), list(actual))
                    for parameter in declared:
                        self.assertEqual(declared[parameter].kind, actual[parameter].kind)
                        self.assertEqual(declared[parameter].default, actual[parameter].default)

    def test_interface_file_contains_only_declarations_and_exports(self) -> None:
        """The main interface file has no executable function bodies / 主接口文件没有函数实现。"""
        tree = ast.parse((ROOT / "core" / "interfaces.py").read_text(encoding="utf-8"))
        for node in tree.body:
            self.assertIsInstance(node, (ast.Expr, ast.ImportFrom, ast.If, ast.ClassDef, ast.Assign))
            if isinstance(node, ast.Expr):
                self.assertIsInstance(node.value, ast.Constant)
            elif isinstance(node, ast.If):
                self.assertEqual(ast.unparse(node.test), "TYPE_CHECKING")
                self.assertTrue(all(isinstance(child, ast.ImportFrom) for child in node.body))
            elif isinstance(node, ast.ClassDef):
                self.assertEqual([ast.unparse(base) for base in node.bases], ["Protocol"])
                for method in node.body:
                    if isinstance(method, ast.FunctionDef):
                        self.assertIsNotNone(ast.get_docstring(method))
                        self.assertTrue(all(
                            isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant)
                            and (isinstance(stmt.value.value, str) or stmt.value.value is Ellipsis)
                            for stmt in method.body
                        ))
            elif isinstance(node, ast.Assign):
                self.assertEqual([ast.unparse(t) for t in node.targets], ["__all__"])
                self.assertIsInstance(node.value, ast.List)
        for name in ("graph", "tree"):
            old = ast.parse((ROOT / "core" / f"{name}.py").read_text(encoding="utf-8"))
            self.assertFalse([
                node.name for node in old.body if isinstance(node, ast.ClassDef)
                and any(ast.unparse(base) == "Protocol" for base in node.bases)
            ])

    def test_unknown_export_raises_attribute_error(self) -> None:
        """Unknown names retain normal Python import behavior / 未知名称保持正常导入行为。"""
        with self.assertRaises(AttributeError):
            getattr(interfaces, "not_a_core_operation")

    def test_import_order_and_plugin_package_names_do_not_create_cycles(self) -> None:
        """Both legacy-first and interface-first imports work / 新旧入口顺序和插件包导入均可用。"""
        probe = """
import importlib
from pathlib import Path
import sys
import types
prefix = sys.argv[1]
if prefix:
    package = types.ModuleType(prefix)
    package.__path__ = [str(Path.cwd())]
    sys.modules[prefix] = package
root = prefix + '.core' if prefix else 'core'
for name in sys.argv[2:]:
    importlib.import_module(root + '.' + name)
api = importlib.import_module(root + '.interfaces')
graph = importlib.import_module(root + '.graph')
tree = importlib.import_module(root + '.tree')
assert api.Graph is graph.Graph
assert api.Tree is tree.Tree
assert api.ArtifactEdge is graph.ArtifactEdge
assert api.GraphArtifactStore is graph.GraphArtifactStore
assert api.TreeArtifactStore is tree.TreeArtifactStore
assert api.TreeCache is tree.TreeCache
for name in api.__all__:
    getattr(api, name)
"""
        for prefix in ("", "_seekmemory_interface_test"):
            for order in (("interfaces", "graph", "tree"), ("graph", "tree", "interfaces"),
                          ("tree", "graph", "interfaces")):
                with self.subTest(prefix=prefix, order=order):
                    result = subprocess.run(
                        [sys.executable, "-X", "utf8", "-B", "-c", probe, prefix, *order],
                        cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                    )
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
