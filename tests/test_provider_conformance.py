"""Normalize a fake provider through the real model adapter.

通过真实模型适配器整理假提供方响应。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import asyncio
from app.contracts import ChatRequest
from perceive.model import ProviderChatModel

class FakeProvider:
    async def text_chat(self, system_prompt="", prompt=""):
        class Usage:
            input = 10
            input_cached = 2
            output = 3
        class Resp:
            completion_text = "ok"
            id = "r1"
            usage = Usage()
        return Resp()

    def meta(self):
        class Meta:
            id = "p1"
            model = "m1"
        return Meta()


class ModelBoundaryTest(unittest.TestCase):
    def test_provider_adapter_normalizes(self):
        model = ProviderChatModel(FakeProvider())
        got = asyncio.run(model.complete(ChatRequest("s1", "sys", "hi")))
        self.assertEqual(got.text, "ok")
        self.assertEqual(got.usage_in, 10)
        self.assertEqual(got.provider_id, "p1")


if __name__ == "__main__":
    unittest.main()
