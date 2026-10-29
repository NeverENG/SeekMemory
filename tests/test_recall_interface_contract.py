"""Protect the explicit recall interface and reused external protocols.

保护明确的召回接口及复用的外部协议。
"""
from __future__ import annotations

import importlib
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

EXPORTS = {
    "build_block": "pipeline", "query_block": "pipeline", "record_context": "context_recording",
    "GraphRetriever": "retriever", "HybridRetriever": "retriever", "BM25Index": "bm25",
    "build": "assemble", "build_with_meta": "assemble", "SourceHit": "source_query",
    "query_recent": "source_query", "owner_of": "scope", "visible": "scope",
    "deliverable": "designated", "mark_given": "designated", "seeds": "seed",
    "bigrams": "seed", "overlap": "seed", "dice": "seed", "tags_of": "seed",
    "score": "score", "select": "score", "filter_valid": "temporal",
    "query_window": "temporal", "in_window": "temporal",
}


class RecallInterfaceContractTest(unittest.TestCase):
    def test_exports_keep_supported_objects(self):
        domain = importlib.import_module("recall.domain")
        self.assertEqual(set(domain.__all__), set(EXPORTS))
        for name, owner in EXPORTS.items():
            self.assertIs(getattr(domain, name), getattr(importlib.import_module("recall." + owner), name))

    def test_required_ports_keep_identity(self):
        from app import ports as app_ports
        from recall import ports

        for name in ports.__all__:
            self.assertIs(getattr(ports, name), getattr(app_ports, name))

    def test_context_recording_port_is_shared_and_optional(self):
        import inspect
        from app.ports import MemoryContextRecorder
        from app.runtime import AgentRuntime
        from app.runtime.contracts import MemoryContextRecorder as runtime_port

        self.assertIs(MemoryContextRecorder, runtime_port)
        parameter = inspect.signature(AgentRuntime).parameters["context_recorder"]
        self.assertIsNone(parameter.default)
        self.assertEqual(parameter.kind, inspect.Parameter.KEYWORD_ONLY)


if __name__ == "__main__":
    unittest.main()
