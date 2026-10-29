"""Architecture guardrails for application ownership boundaries."""

from __future__ import annotations

import ast
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.access_service import AccessPolicy  # noqa: E402
from services.background_service import BackgroundService  # noqa: E402


class AccessPolicyTest(unittest.TestCase):
    def test_owner_and_trusted_modes(self) -> None:
        policy = AccessPolicy(
            mode="owner_and_trusted",
            owner_umo="bot:owner",
            trusted_ids=frozenset({"trusted"}),
            observe_groups=True,
        )
        self.assertTrue(policy.may_remember("bot:owner", "owner"))
        self.assertTrue(policy.may_remember("bot:friend:trusted", "trusted"))
        self.assertFalse(policy.may_remember("bot:friend:other", "other"))
        self.assertTrue(policy.may_observe("bot:GroupMessage:g1", "other"))
        self.assertFalse(policy.may_recall("bot:FriendMessage:other", "other"))

    def test_group_detection_is_explicit(self) -> None:
        self.assertTrue(AccessPolicy.is_group("bot:GroupMessage:g1"))
        self.assertFalse(AccessPolicy.is_group("bot:FriendMessage:u1"))


class MainOwnershipTest(unittest.TestCase):
    def setUp(self) -> None:
        self.source = (ROOT / "main.py").read_text(encoding="utf-8")

    def test_main_contains_no_host_extra_protocol(self) -> None:
        self.assertNotIn("_seekmemory_", self.source)

    def test_main_does_not_write_memory_or_episode_state_directly(self) -> None:
        forbidden = (
            "self.recorder.",
            "db.sources.append_sources(",
            "buffer.add(",
            "make_source_id(",
        )
        for fragment in forbidden:
            self.assertNotIn(fragment, self.source)

    def test_main_stays_a_composition_and_hook_shell(self) -> None:
        self.assertLessEqual(len(self.source.splitlines()), 40)

    def test_main_only_contains_lifecycle_entrypoints(self) -> None:
        tree = ast.parse(self.source)
        definitions = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        self.assertEqual(definitions, {"__init__", "initialize", "terminate"})

    def test_main_has_explicit_hook_bindings(self) -> None:
        for name in (
            "inject_memory", "buffer_message", "capture_reply",
            "record_delivery", "observe_agent_begin", "observe_agent_done",
            "observe_tool", "observe_tool_result", "start_jobs",
        ):
            self.assertIn(f"{name} = _HOOKS[\"{name}\"]", self.source)
        self.assertNotIn("locals().update", self.source)

    def test_each_hook_wrapper_has_a_unique_name(self) -> None:
        """AstrBot 用 module+__name__ 生成 handler 唯一名，闭包同名会互相覆盖。"""
        hooks_source = (ROOT / "adapters" / "astrbot" / "hooks.py").read_text()
        self.assertIn("handler.__name__ = name", hooks_source)

    def test_service_collection_is_a_typed_bundle(self) -> None:
        from dataclasses import fields
        from services.service_collection import ServiceCollection

        names = {field.name for field in fields(ServiceCollection)}
        self.assertEqual(
            names,
            {
                "access_service", "recall_service", "ingest_service",
                "capacity_service", "maintenance_service", "management_service",
                "status_service", "background_service", "runtime",
                "runtime_worker",
            },
        )

    def test_main_only_composes_host_adapter_modules(self) -> None:
        tree = ast.parse(self.source)
        imported = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
        self.assertTrue(all(
            name.startswith("astrbot") or name.startswith("adapters")
            or name == "__future__" for name in imported
        ))

    def test_start_jobs_remains_the_astrbot_loaded_hook(self) -> None:
        hooks = (ROOT / "adapters" / "astrbot" / "hooks.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('"start_jobs": _register(', hooks)
        self.assertIn("filter.on_astrbot_loaded()", hooks)


class BackgroundServiceLifecycleTest(unittest.TestCase):
    def test_start_and_stop_are_idempotent(self) -> None:
        class Journal:
            def __init__(self):
                self.rows = []

            def record(self, *args, **kwargs):
                self.rows.append((args, kwargs))

        class RuntimeWorker:
            async def run_forever(self):
                await asyncio.Event().wait()

        class Dummy:
            pass

        async def run():
            background = BackgroundService(
                jobs=Dummy(),
                checkpoint=None,
                buffer=None,
                capacity=Dummy(),
                ingest=Dummy(),
                maintenance=Dummy(),
                dream=None,
                runtime_worker=RuntimeWorker(),
                journal=Journal(),
                config=lambda key, default: default,
                logger=Dummy(),
            )
            self.assertTrue(background.start())
            self.assertFalse(background.start())
            tasks = list(background.tasks)
            await background.stop()
            self.assertTrue(all(task.done() for task in tasks))
            self.assertEqual(background.tasks, [])
            await background.stop()

        import asyncio

        asyncio.run(run())


class LayerDependencyTest(unittest.TestCase):
    def _imports(self, root: Path) -> list[str]:
        values: list[str] = []
        for path in root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    values.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    values.append(node.module)
        return values

    def test_runtime_does_not_import_astrbot(self) -> None:
        imports = self._imports(ROOT / "app" / "runtime")
        self.assertFalse([item for item in imports if item.startswith("astrbot")])

    def test_astrbot_event_and_attention_use_injected_clock(self) -> None:
        for name in ("events.py", "attention.py"):
            source = (ROOT / "adapters" / "astrbot" / name).read_text(
                encoding="utf-8"
            )
            self.assertNotIn("time.time(", source)

    def test_webui_stays_host_neutral(self) -> None:
        for path in (ROOT / "webui").glob("*.py"):
            self.assertNotIn("astrbot", path.read_text(encoding="utf-8").lower())

    def test_store_composition_is_only_repository_bundle(self) -> None:
        source = (ROOT / "store" / "__init__.py").read_text(encoding="utf-8")
        for keyword in ("SELECT ", "INSERT ", "UPDATE ", "DELETE "):
            self.assertNotIn(keyword, source)
        self.assertLessEqual(len(source.splitlines()), 100)

    def test_store_exposes_repositories_not_domain_methods(self) -> None:
        import sys

        sys.path.insert(0, str(ROOT))
        from store import open_store

        store = open_store(":memory:")
        self.addCleanup(store.close)
        for name in ("artifacts", "sources", "extraction", "runtime_state",
                     "runtime_episodes", "dreams", "ledger", "metrics"):
            self.assertTrue(hasattr(store, name), name)
        for name in ("commit", "append_sources", "enqueue_extraction",
                     "get_runtime_state", "append_runtime_episode"):
            self.assertFalse(hasattr(store, name), name)

    def test_store_does_not_import_host_or_adapters(self) -> None:
        imports = self._imports(ROOT / "store")
        self.assertFalse(
            [
                item for item in imports
                if item.startswith("astrbot") or item.startswith("adapters")
                or item.startswith("app")
            ]
        )

    def test_no_public_db_dependency_outside_store(self) -> None:
        self.assertFalse((ROOT / "store" / "db.py").exists())
        paths = [ROOT / "main.py"]
        for folder in ("app", "adapters", "core", "services", "recall",
                       "perceive", "maintain", "webui", "scripts",
                       "benchmarks", "tests"):
            paths.extend((ROOT / folder).rglob("*.py"))
        for path in paths:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    if module.endswith("store.db"):
                        self.fail(f"imports store.db: {path}")
                    if module.endswith("store"):
                        self.assertNotIn(
                            "DB", {alias.name for alias in node.names}, str(path)
                        )
                elif isinstance(node, ast.Import):
                    self.assertFalse(
                        any(alias.name.startswith("store.db") for alias in node.names),
                        str(path),
                    )

    def test_engines_and_services_do_not_import_aggregate_store(self) -> None:
        for folder in ("app", "core", "services", "recall", "perceive",
                       "maintain", "webui"):
            for path in (ROOT / folder).rglob("*.py"):
                tree = ast.parse(path.read_text(encoding="utf-8"))
                for node in ast.walk(tree):
                    if isinstance(node, ast.ImportFrom):
                        module = node.module or ""
                        if module in ("store", "..store") or module.endswith("store"):
                            names = {alias.name for alias in node.names}
                            self.assertNotIn("Store", names, str(path))
                            self.assertNotIn("open_store", names, str(path))

    def test_capacity_delegates_maintenance_writes(self) -> None:
        source = (ROOT / "services" / "capacity_service.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("from ..maintain", source)
        self.assertNotIn("from maintain", source)
        self.assertIn("self.maintenance.compact_artifacts()", source)
        self.assertIn("self.maintenance.forget_expired()", source)

    def test_webui_preview_uses_recall_service(self) -> None:
        source = (ROOT / "services" / "management_service.py").read_text(encoding="utf-8")
        self.assertNotIn("recall.pipeline", source)
        self.assertNotIn("build_block", source)
        self.assertIn("self.recall_service.preview(", source)

    def test_ingest_service_is_the_only_production_plan_consumer(self) -> None:
        from perceive import absorb

        self.assertFalse(hasattr(absorb, "absorb"))
        callers = []
        for folder in ("app", "adapters", "services", "core", "recall",
                       "perceive", "maintain", "webui"):
            for path in (ROOT / folder).rglob("*.py"):
                source = path.read_text(encoding="utf-8")
                tree = ast.parse(source, filename=str(path))
                if any(isinstance(node, ast.Call)
                       and isinstance(node.func, ast.Name)
                       and node.func.id == "build_plan" for node in ast.walk(tree)):
                    callers.append(path)
        self.assertEqual(callers, [ROOT / "services" / "ingest_service.py"])

    def test_importance_triage_is_pure_and_local(self) -> None:
        path = ROOT / "perceive" / "importance.py"
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        modules = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                modules.append(node.module)
            elif isinstance(node, ast.Import):
                modules.extend(alias.name for alias in node.names)
        self.assertFalse([
            module for module in modules
            if module.startswith(("store", "adapters", "astrbot", "services"))
        ])
        for fragment in ("ChatRequest(", "complete(", "text_chat(", ".commit("):
            self.assertNotIn(fragment, source, str(path))

    def test_no_raw_source_render_path(self) -> None:
        self.assertFalse((ROOT / "recall" / "source_context.py").exists())
        for folder in ("app", "core", "recall", "services"):
            for path in (ROOT / folder).rglob("*.py"):
                source = path.read_text(encoding="utf-8")
                self.assertNotIn("render_same_session", source, str(path))
                self.assertNotIn("decide_source", source, str(path))

    def test_conversion_module_has_no_persistence(self) -> None:
        source = (ROOT / "perceive" / "absorb.py").read_text(encoding="utf-8")
        self.assertNotIn("async def absorb(", source)
        for fragment in (
            ".commit(", "cache.put(", "link_new(", "revise_impression(",
            "_supersede(", "ChatRequest(",
        ):
            self.assertNotIn(fragment, source)

    def test_ingest_extract_owns_write_side_effects(self) -> None:
        source = (ROOT / "services" / "ingest_service.py").read_text(
            encoding="utf-8"
        )
        for fragment in (
            "async def extract(", "build_plan(", ".commit(",
            "cache.put(", "link_new(", "revise_impression(", "self._supersede(",
        ):
            self.assertIn(fragment, source)

    def test_engine_and_service_layers_do_not_import_store(self) -> None:
        for folder in ("app", "core", "services", "recall", "perceive",
                       "maintain", "webui"):
            for path in (ROOT / folder).rglob("*.py"):
                tree = ast.parse(path.read_text(encoding="utf-8"))
                for node in ast.walk(tree):
                    modules = []
                    if isinstance(node, ast.ImportFrom) and node.module:
                        modules.append(node.module)
                    elif isinstance(node, ast.Import):
                        modules.extend(alias.name for alias in node.names)
                    for module in modules:
                        self.assertFalse(
                            module == "store" or module.startswith("store."),
                            f"{path} imports {module}",
                        )

    def test_engine_and_service_functions_do_not_take_aggregate_db(self) -> None:
        for folder in ("core", "services", "recall", "perceive", "maintain"):
            for path in (ROOT / folder).rglob("*.py"):
                tree = ast.parse(path.read_text(encoding="utf-8"))
                for node in ast.walk(tree):
                    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        continue
                    arguments = [
                        *node.args.posonlyargs,
                        *node.args.args,
                        *node.args.kwonlyargs,
                    ]
                    self.assertNotIn("db", {arg.arg for arg in arguments}, str(path))
                    self.assertNotIn("store", {arg.arg for arg in arguments}, str(path))

    def test_relationship_policy_stays_out_of_recall_and_store(self) -> None:
        self.assertFalse((ROOT / "services" / "relationship_service.py").exists())
        schema = (ROOT / "store" / "schema.sql").read_text(encoding="utf-8")
        self.assertNotIn("CREATE TABLE relationship", schema)
        imports = self._imports(ROOT / "recall")
        self.assertFalse([
            item for item in imports
            if item.endswith("core.relationship")
            or item.endswith("runtime.relationship")
        ])

    def test_services_do_not_import_host_or_adapters(self) -> None:
        imports = self._imports(ROOT / "services")
        self.assertFalse(
            [
                item for item in imports
                if item.startswith("astrbot") or item.startswith("adapters")
            ]
        )


if __name__ == "__main__":
    unittest.main()
