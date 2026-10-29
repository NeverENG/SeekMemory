"""Core domain and required-port interface contracts."""

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

from core import domain, ports  # noqa: E402


# Approved interface surface; private definitions do not automatically become exports.
# 已认可的接口清单；内部新增定义不会自动变成导出。
EXPORTS = {
    "artifact": (
        'FAMILIES', 'Artifact', 'Header', 'Lineage',
        'Strength', 'TimeSpan', 'make', 'revise',
        'validate', 'content_of',
    ),
    "source": (
        'ROLES', 'Source', 'content_hash', 'make_source_id',
    ),
    "versioning": (
        'OPS', 'CHECKPOINT_OPS', 'StateEvent', 'VersionError',
        'assert_next_revision', 'is_semantic_change',
    ),
    "retrieval": (
        'RetrievalCandidate',
    ),
    "strength": (
        'BASE_DAYS', 'HIT_STEP', 'COOLDOWN', 'SHAPE_FACTORS',
        'REINFORCE_DELTAS', 'retention', 'decayed_weight', 'reinforce',
        'hit_cooldown_ok',
    ),
    "disclosure": (
        'FULL_MIN', 'PARAPHRASE_MIN', 'HINT_MIN', 'DisclosureLevel',
        'RecallScene', 'DisclosureDecision', 'scope_prior', 'sensitivity_of',
        'context_affinity', 'audience_overlap', 'subject_fit', 'exposure',
        'decide', 'safe_text',
    ),
    "graph": (
        'ArtifactEdge', 'Graph', 'KINDS',
    ),
    "capacity": (
        'NORMAL', 'PRESSURED', 'SATURATED', 'PROTECTIVE',
        'ENV_PREFIX', 'CapacityThresholds', 'CapacitySnapshot', 'CapacityDecision',
        'CapacityGovernor', 'load_thresholds',
    ),
    "persona": (
        'PERSONA_ORIGIN_SEED', 'PERSONA_ORIGIN_DREAM', 'PERSONA_SYNTHESIS_VERSION', 'PERSONA_ORIGINS',
        'MIN_CORPUS_EXAMPLES', 'MIN_CORPUS_CHARS', 'normalize_persona_file', 'persona_payload_from_file',
        'compose_seed_evolution', 'seed_evolution_matches',
    ),
    "persona_artwork": (
        'MAX_ARTWORK_BYTES', 'PNG_SIGNATURE', 'validate_artwork',
    ),
    "persona_pack": (
        'PACK_FORMAT', 'MAX_PACK_BYTES', 'MAX_SEED_BYTES', 'normalize_pack',
    ),
    "bot_behavior": (
        'SELF_SUBJECT', 'MIN_EVIDENCE', 'MIN_CONFIDENCE', 'BEHAVIOR_TEXT',
        'BEHAVIORS', 'confident', 'compose_behaviors', 'trusted_self_impression',
        'trusted_self_persona',
    ),
    "relationship": (
        'RELATIONSHIP_POLICY_VERSION', 'HARD_GATE_CONFIDENCE', 'RelationshipBand', 'RelationshipSnapshot',
        'relationship_id', 'summary_for', 'band_for', 'snapshot_from_payload',
    ),
    "relationship_rules": (
        'RelationshipSignal', 'RelationshipReason', 'RelationshipStrength', 'ConversationScope',
        'EvidenceRule', 'EVIDENCE_RULES', 'RelationshipObservation', 'RelationshipScoringPolicy',
        'ScoredRelationshipEvidence', 'RelationshipRevisionPlan', 'score_observation', 'plan_relationship_revision',
    ),
    "interaction_policy": (
        'INTERACTION_POLICY_VERSION', 'LOW_REPLY_CHARS', 'DISLIKE_REPLY_CHARS', 'CLOSE_PROACTIVE_KINDS',
        'ReplyStyle', 'AffectionScope', 'InteractionRule', 'InteractionContext',
        'InteractionGate', 'InteractionPolicySettings', 'stable_sample', 'decide_interaction',
    ),
    "trace": (
        'EVENTS', 'FILTERS', 'STATUSES', 'ID_LIMIT',
        'ids', 'count', 'choice', 'recall_data',
        'clean_event', 'project_runs',
    ),
}

class CoreInterfaceContractTest(unittest.TestCase):
    def test_every_export_resolves_without_placeholder_operations(self) -> None:
        """Exports are the existing values/functions, not empty stubs / 导出沿用原对象，不是空函数。"""
        self.assertTrue(set(domain.__all__).isdisjoint(ports.__all__))
        for entry in (domain, ports):
            self.assertEqual(len(entry.__all__), len(set(entry.__all__)))
            self.assertTrue(set(entry.__all__).issubset(dir(entry)))
            for name in entry.__all__:
                with self.subTest(entry=entry.__name__, name=name):
                    self.assertIsNotNone(getattr(entry, name))
        art = domain.make("memory", {"text": "a fact", "level": "fact"})
        domain.validate(art)
        changed = domain.revise(art, {"text": "updated", "level": "fact"})
        self.assertEqual(domain.content_of(changed), "updated")
        self.assertEqual(changed.header.id, art.header.id)
        self.assertEqual(changed.header.revision, 2)
        self.assertEqual(art.payload["text"], "a fact")

    def test_existing_public_symbols_keep_identity_through_the_interface(self) -> None:
        """One entry exposes the existing domain surface / 单一入口导出已有领域能力。"""
        approved = {name for names in EXPORTS.values() for name in names}
        self.assertEqual(set(domain.__all__), approved)
        for owner, names in EXPORTS.items():
            module = importlib.import_module(f"core.{owner}")
            for name in names:
                with self.subTest(module=module.__name__, name=name):
                    self.assertIs(getattr(domain, name), getattr(module, name))

    def test_graph_protocol_import_is_an_alias_of_the_single_declaration(self) -> None:
        """Graph keeps its existing protocol import / 图保留原接口导入路径。"""
        from core.graph import GraphArtifactStore

        self.assertIs(GraphArtifactStore, ports.GraphArtifactStore)
        self.assertEqual(GraphArtifactStore.__module__, "core.ports")

    def test_storage_protocol_call_shapes_match_the_existing_implementations(self) -> None:
        """Moving declarations keeps call arguments unchanged / 迁移声明不改变调用参数。"""
        from store.artifacts import ArtifactRepository
        from store.cache import Cache
        from app.ports import TreeArtifactStore, TreeCache

        for protocol, implementation in (
            (ports.GraphArtifactStore, ArtifactRepository),
            (TreeArtifactStore, ArtifactRepository),
            (TreeCache, Cache),
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
        for filename in ("domain.py", "ports.py"):
            tree = ast.parse((ROOT / "core" / filename).read_text(encoding="utf-8"))
            for node in tree.body:
                self.assertIsInstance(node, (ast.Expr, ast.ImportFrom, ast.ClassDef, ast.Assign))
                if isinstance(node, ast.Expr):
                    self.assertIsInstance(node.value, ast.Constant)
                elif isinstance(node, ast.ClassDef):
                    self.assertEqual(filename, "ports.py")
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
        for name in ("graph",):
            old = ast.parse((ROOT / "core" / f"{name}.py").read_text(encoding="utf-8"))
            self.assertFalse([
                node.name for node in old.body if isinstance(node, ast.ClassDef)
                and any(ast.unparse(base) == "Protocol" for base in node.bases)
            ])

    def test_core_does_not_import_application_services_or_storage(self) -> None:
        """Moving tree orchestration must not create an upward dependency."""
        forbidden = {"app", "services", "store", "adapters", "astrbot"}
        for path in sorted((ROOT / "core").rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module or ""]
                else:
                    continue
                for name in names:
                    self.assertNotIn(name.split(".")[0], forbidden, f"{path}: {name}")

    def test_unknown_export_raises_attribute_error(self) -> None:
        """Unknown names retain normal Python import behavior / 未知名称保持正常导入行为。"""
        for entry in (domain, ports):
            with self.subTest(entry=entry.__name__), self.assertRaises(AttributeError):
                getattr(entry, "not_a_core_operation")

    def test_import_order_and_plugin_package_names_do_not_create_cycles(self) -> None:
        """Core and service imports work in either order and under plugin packages."""
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
def qualify(name):
    return prefix + '.' + name if prefix else name
for name in sys.argv[2:]:
    importlib.import_module(qualify(name))
api = importlib.import_module(qualify('core.domain'))
core_ports = importlib.import_module(qualify('core.ports'))
graph = importlib.import_module(qualify('core.graph'))
ports = importlib.import_module(qualify('app.ports'))
service = importlib.import_module(qualify('services.tree_service'))
services = importlib.import_module(qualify('services'))
assert api.Graph is graph.Graph
assert api.ArtifactEdge is graph.ArtifactEdge
assert core_ports.GraphArtifactStore is graph.GraphArtifactStore
assert set(api.__all__).isdisjoint(core_ports.__all__)
assert services.TreeService is service.TreeService
assert ports.TreeArtifactStore is service.TreeArtifactStore
assert ports.TreeCache is service.TreeCache
assert not {'Tree', 'EDGE_PREFIX', 'LEVELS', 'TreeArtifactStore', 'TreeCache'} & set(api.__all__)
for name in api.__all__:
    getattr(api, name)
"""
        for prefix in ("", "_seekmemory_interface_test"):
            for order in (
                ("core.domain", "core.graph", "services.tree_service"),
                ("core.graph", "services.tree_service", "core.domain"),
                ("services.tree_service", "app.ports", "core.domain"),
                ("app.ports", "services.tree_service", "core.domain"),
                ("core.ports", "core.graph", "core.domain"),
                ("core.domain", "core.ports", "core.graph"),
                ("core.families.relationship", "core.relationship", "core.domain"),
                ("core.trace", "core.disclosure", "core.domain"),
            ):
                with self.subTest(prefix=prefix, order=order):
                    result = subprocess.run(
                        [sys.executable, "-X", "utf8", "-B", "-c", probe, prefix, *order],
                        cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                    )
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
