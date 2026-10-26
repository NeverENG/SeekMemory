"""人格文件 bootstrap 与召回注入的回归测试。

覆盖两件事：
1. 人格文件写入后是唯一、可信的 seed 人格链（不产生 Source）；
2. 召回常驻层注入的是完整人格文本，不会被单条记忆的 180 字上限截断。
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import tempfile
import unittest
from pathlib import Path

from persona_support import PersonaCase
from services.management_service import ManagementService

ROOT = Path(__file__).resolve().parents[1]


def corpus() -> list[dict[str, str]]:
    """够门槛的最小语料：12 对 / 1200 字以上。"""
    return [
        {
            "user": (
                f"第{i}个场景：今天发生了很多事情，我有点累，想和你说说心里话。"
                "工作上的压力、生活里的琐事都挤在一起，我现在只想安静待一会儿。"
            ),
            "assistant": (
                f"先缓一缓嘛，我在听。第{i}次也会陪着你，不用一个人扛着。"
                "你可以慢慢讲，不想说也没关系，我会一直在这里等你。"
            ),
        }
        for i in range(12)
    ]


LONG_PERSONA = (
    "你是大肥鱼。" + "你说话短、有分寸，对熟人亲近，对生人客气。" * 20
    + " 最后一条规则：无论什么时候都保持这个语气。"
)


def seed_file(text: str = LONG_PERSONA) -> dict:
    return {
        "id": "big_fish",
        "version": "1.0.0",
        "name": "大肥鱼",
        "persona": text,
        "style": {"tone": "短句、有分寸"},
        "boundaries": ["不伪造用户经历"],
        "corpus": corpus(),
        "license": "CC0-1.0",
        "source": "original",
        "content_rating": "general",
        "locale": "zh-CN",
    }


class PersonaInjectionTest(PersonaCase):
    def service(self) -> ManagementService:
        return ManagementService(
            self.db.artifacts, self.db.sources, self.db.ledger, self.cache, None
        )

    def recall(self, budget: int = 1600) -> str:
        from core.graph import Graph
        from recall.pipeline import build_block

        conf = {"budget_chars": budget}.get
        block, _ = build_block(
            self.cache,
            Graph(self.db.artifacts),
            self.db.artifacts,
            self.db.sources,
            "owner",
            "你还记得我上次说的事吗",
            True,
            lambda key, default: conf(key, default),
            "owner",
            speaker="owner",
            dry_run=True,
        )
        return block

    def test_persona_injection_keeps_the_whole_text(self) -> None:
        self.service().bootstrap_persona(seed_file())
        block = self.recall()
        self.assertIn("最后一条规则：无论什么时候都保持这个语气", block)
        self.assertGreater(len(block), 300)

    def test_bootstrap_revises_one_chain_and_keeps_seed_provenance(self) -> None:
        first = self.service().bootstrap_persona(seed_file())
        second = self.service().bootstrap_persona(seed_file(LONG_PERSONA + " 补充。"))
        self.assertEqual(first["id"], second["id"])
        self.assertGreater(second["revision"], first["revision"])
        active = self.cache.active("persona")
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0].payload["seed_id"], "big_fish")


class PersonaScriptTest(unittest.TestCase):
    def _load_script(self):
        path = ROOT / "scripts" / "bootstrap_persona.py"
        spec = importlib.util.spec_from_file_location("bootstrap_persona", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_dry_run_validates_without_writing(self) -> None:
        module = self._load_script()
        with tempfile.TemporaryDirectory() as tmp:
            seed_path = Path(tmp) / "seed.json"
            seed_path.write_text(
                __import__("json").dumps(seed_file(), ensure_ascii=False),
                encoding="utf-8",
            )
            with contextlib.redirect_stdout(io.StringIO()):
                code = module.main(
                    ["--db", str(Path(tmp) / "missing.db"), "--file", str(seed_path), "--dry-run"]
                )
            self.assertEqual(code, 0)

    def test_missing_file_returns_error(self) -> None:
        module = self._load_script()
        with contextlib.redirect_stderr(io.StringIO()):
            code = module.main(["--db", "/tmp/x.db", "--file", "/tmp/nope.json"])
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
