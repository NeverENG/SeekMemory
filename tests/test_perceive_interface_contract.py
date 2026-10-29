"""Protect explicit extraction entries and protocol identity.

保护明确的抽取入口及协议身份。
"""
from __future__ import annotations

import importlib
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

EXPORTS = {
    "ExtractionPlan": "absorb", "build_plan": "absorb", "dialogue_of": "absorb",
    "recover_parents": "absorb", "worth_now": "absorb", "Buffer": "buffer",
    "log_call": "calls", "build_compress_prompt": "compress", "parse_compress": "compress",
    "build_prompt": "extract", "ExtractionParseError": "extract", "parse_response": "extract",
    "parse_response_checked": "extract", "filter_duplicates": "extract",
    "MIN_IMPORTANCE_SCORE": "importance", "TopicImportance": "importance", "score_topic": "importance",
    "rank_topics": "importance", "select_important_topics": "importance", "select_ranked_topics": "importance",
    "ProviderChatModel": "model",
}


class PerceiveInterfaceContractTest(unittest.TestCase):
    def test_supported_exports_keep_original_objects(self):
        domain = importlib.import_module("perceive.domain")
        self.assertEqual(set(domain.__all__), set(EXPORTS))
        for name, owner in EXPORTS.items():
            self.assertIs(getattr(domain, name), getattr(importlib.import_module("perceive." + owner), name))

    def test_existing_required_protocols_are_reused(self):
        from app import ports as app_ports
        from perceive import ports

        for name in ("ArtifactCache", "SourceStore", "ExtractionStore", "ChatModel"):
            self.assertIs(getattr(ports, name), getattr(app_ports, name))

    def test_parser_and_dialogue_compatibility_aliases_keep_identity(self):
        from perceive import absorb, extract, dialogue_evidence, response_parser, duplicate_policy

        self.assertIs(absorb.dialogue_of, dialogue_evidence.dialogue_of)
        self.assertIs(absorb.recover_parents, dialogue_evidence.recover_parents)
        self.assertIs(extract.parse_response_checked, response_parser.parse_response_checked)
        self.assertIs(extract.ExtractionParseError, response_parser.ExtractionParseError)
        self.assertIs(extract.filter_duplicates, duplicate_policy.filter_duplicates)


if __name__ == "__main__":
    unittest.main()
