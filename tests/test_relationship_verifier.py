"""Evidence and semantic verdict boundaries for relationship observations."""

from __future__ import annotations

import json
import subprocess
import os
import sys
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.contracts import ChatResponse
from core.relationship_rules import (
    ConversationScope, RelationshipCandidate, RelationshipReason,
    RelationshipStrength, VerifiedRelationshipEvent,
)
from core.source import Source
from benchmarks.relationship_eval import evaluate, load_cases
from perceive.relationship import verify_relationship


class VerdictModel:
    def __init__(self, **fields: object) -> None:
        self.fields = fields

    async def complete(self, request) -> ChatResponse:
        return ChatResponse(text=json.dumps(self.fields))


def source(source_id: str, role: str, text: str, minute: int, speaker: str = "u1") -> Source:
    return Source(
        source_id, source_id, "private:u1", speaker, role, text,
        f"2026-10-26T08:{minute:02d}:00+00:00",
    )


def candidate(reason: RelationshipReason, primary: str, *ids: str) -> RelationshipCandidate:
    return RelationshipCandidate(
        "u1", reason, RelationshipStrength.STRONG, primary, ids,
        "private:u1", ConversationScope.PRIVATE,
    )



class RelationshipVerifierTest(unittest.IsolatedAsyncioTestCase):
    async def test_other_target_and_uncited_source_cannot_verify_insult(self) -> None:
        actor = source("s1", "user", "鱼，你真蠢。", 2)
        proposed = candidate(RelationshipReason.INSULT, actor.id, actor.id)
        wrong_target = VerdictModel(
            decision="verified", reason="insult", source_ids=[actor.id], target="other",
        )
        uncited_source = VerdictModel(
            decision="verified", reason="insult", source_ids=["s_unknown"], target="assistant",
        )
        wrong_reason = VerdictModel(
            decision="verified", reason="disrespect", source_ids=[actor.id], target="assistant",
        )
        self.assertEqual((await verify_relationship(proposed, (actor,), wrong_target)).status, "abstain")
        self.assertEqual((await verify_relationship(proposed, (actor,), uncited_source)).status, "abstain")
        self.assertEqual((await verify_relationship(proposed, (actor,), wrong_reason)).status, "abstain")

    async def test_repair_requires_verified_same_subject_earlier_negative_event(self) -> None:
        apology = source("s_apology", "user", "鱼，刚才辱骂你是我的错，对不起。", 5)
        proposed = candidate(RelationshipReason.REPAIR, apology.id, apology.id)
        model = VerdictModel(
            decision="verified", reason="repair", source_ids=[apology.id],
            target="assistant", repair_of="re_negative",
        )
        pending = SimpleNamespace(
            event_id="re_negative", subject_id="u1", reason="insult",
            status="pending", event_at="2026-10-26T08:00:00+00:00",
        )
        other_subject = SimpleNamespace(
            event_id="re_negative", subject_id="u2", reason="insult",
            status="verified", event_at="2026-10-26T08:00:00+00:00",
        )
        self.assertEqual((await verify_relationship(proposed, (apology,), model, (pending,))).status, "abstain")
        self.assertEqual((await verify_relationship(proposed, (apology,), model, (other_subject,))).status, "abstain")
        self.assertEqual((await verify_relationship(proposed, (apology,), model)).status, "abstain")
        future = SimpleNamespace(
            event_id="re_negative", subject_id="u1", reason="insult",
            status="verified", event_at="2026-10-26T08:06:00+00:00",
        )
        self.assertEqual((await verify_relationship(proposed, (apology,), model, (future,))).status, "abstain")
        prior = VerifiedRelationshipEvent(
            "re_negative", "u1", RelationshipReason.INSULT,
            RelationshipStrength.STRONG, ConversationScope.PRIVATE,
            datetime(2026, 10, 26, 8, tzinfo=timezone.utc), "s_prior", ("s_prior",),
        )
        verdict = await verify_relationship(proposed, (apology,), model, (prior,))
        self.assertEqual((verdict.status, verdict.repair_of), ("verified", "re_negative"))
        missing_reference = VerdictModel(
            decision="verified", reason="repair", source_ids=[apology.id], target="assistant",
        )
        self.assertEqual(
            (await verify_relationship(proposed, (apology,), missing_reference, (prior,))).status,
            "abstain",
        )

    async def test_repair_selects_latest_three_by_instant_when_four_priors_exist(self) -> None:
        apology = source("s_apology", "user", "鱼，刚才辱骂你是我的错，对不起。", 5)
        proposed = candidate(RelationshipReason.REPAIR, apology.id, apology.id)
        priors = tuple(
            SimpleNamespace(
                event_id=event_id, subject_id="u1", reason="insult",
                status="verified", event_at=at,
            )
            for event_id, at in (
                ("n1", "2026-10-26T08:00:00+00:00"),
                ("n2", "2026-10-26T08:01:00+00:00"),
                ("n3", "2026-10-26T09:02:00+01:00"),
                ("n4", "2026-10-26T07:03:00-01:00"),
            )
        )
        latest = VerdictModel(
            decision="verified", reason="repair", source_ids=[apology.id],
            target="assistant", repair_of="n4",
        )
        old = VerdictModel(
            decision="verified", reason="repair", source_ids=[apology.id],
            target="assistant", repair_of="n1",
        )
        verdict = await verify_relationship(proposed, (apology,), latest, priors)
        self.assertEqual((verdict.status, verdict.repair_of), ("verified", "n4"))
        self.assertEqual((await verify_relationship(proposed, (apology,), old, priors)).status, "abstain")

    async def test_harassment_requires_assistant_stop_between_user_sources(self) -> None:
        first = source("s_first", "user", "鱼，你真蠢。", 0)
        stop = source("s_stop", "assistant", "请停止辱骂我。", 1, "fish")
        repeat = source("s_repeat", "user", "我继续骂你，鱼，你真蠢。", 2)
        proposed = candidate(RelationshipReason.HARASSMENT, repeat.id, first.id, stop.id, repeat.id)
        model = VerdictModel(
            decision="verified", reason="harassment",
            source_ids=[first.id, stop.id, repeat.id], target="assistant", stop_source_id=stop.id,
        )
        verdict = await verify_relationship(proposed, (first, stop, repeat), model)
        self.assertEqual(verdict.status, "verified")
        missing_stop = VerdictModel(
            decision="verified", reason="harassment", target="assistant",
            source_ids=[first.id, stop.id, repeat.id],
        )
        self.assertEqual(
            (await verify_relationship(proposed, (first, stop, repeat), missing_stop)).status,
            "abstain",
        )
        no_stop = source(stop.id, "assistant", "今天天气不错。", 1, "fish")
        self.assertEqual(
            (await verify_relationship(proposed, (first, no_stop, repeat), model)).status,
            "abstain",
        )
        fake_stop = source(stop.id, "user", "请停止辱骂我。", 1)
        self.assertEqual(
            (await verify_relationship(proposed, (first, fake_stop, repeat), model)).status,
            "abstain",
        )
        late_stop = source(stop.id, "assistant", "请停止辱骂我。", 3, "fish")
        self.assertEqual(
            (await verify_relationship(proposed, (first, late_stop, repeat), model)).status,
            "abstain",
        )

    async def test_model_failures_are_not_decided_as_abstentions(self) -> None:
        class FailingModel:
            async def complete(self, request) -> ChatResponse:
                raise RuntimeError("model unavailable")

        actor = source("s1", "user", "鱼，你真蠢。", 2)
        with self.assertRaisesRegex(RuntimeError, "model unavailable"):
            await verify_relationship(candidate(RelationshipReason.INSULT, actor.id, actor.id), (actor,), FailingModel())


    async def test_unzoned_actor_does_not_trigger_semantic_approval(self) -> None:
        actor = Source("s_naive", "t", "private:u1", "u1", "user", "鱼，你真蠢", "2026-10-26T08:00:00")
        proposed = candidate(RelationshipReason.INSULT, actor.id, actor.id)
        verdict = await verify_relationship(proposed, (actor,), VerdictModel(
            decision="verified", reason="insult", source_ids=[actor.id], target="assistant",
        ))
        self.assertEqual(verdict.status, "abstain")

    async def test_benchmark_counts_verifier_false_positives_instead_of_fixed_zero(self) -> None:
        class OververifyingModel:
            model = "fixture"

            async def complete(self, request) -> ChatResponse:
                proposed = json.loads(request.prompt)["candidate"]
                return ChatResponse(text=json.dumps({
                    "decision": "verified", "reason": proposed["reason"],
                    "source_ids": proposed["source_ids"], "target": "assistant",
                }))

        cases = load_cases(os.path.join(os.path.dirname(__file__), "..", "benchmarks", "relationship_cases.jsonl"))
        report = await evaluate(cases[:3], OververifyingModel())
        self.assertEqual(report["negative_cases"], 2)
        self.assertEqual(report["negative_false_positives"], 2)
        self.assertEqual(report["negative_false_positive_rate"], 1.0)
        self.assertEqual(report["status"], "measured")

class RelationshipPackageModeTest(unittest.TestCase):
    def test_pending_event_is_verified_when_loaded_as_plugin_package(self) -> None:
        script = """
import asyncio
import json
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, sys.argv[1])
from SeekMemory.adapters.relationship_policy import RelationshipReader
from SeekMemory.core.source import Source
from SeekMemory.core.relationship_rules import VERIFIER_VERSION
from SeekMemory.services.maintenance_service import MaintenanceService
from SeekMemory.store import open_store
from SeekMemory.store.cache import Cache

with tempfile.TemporaryDirectory() as directory:
    db = open_store(str(Path(directory) / "memory.db"))
    try:
        source = Source("s1", "t1", "bot:FriendMessage:u1", "u1", "user",
                        "鱼，谢谢你帮我理清问题", "2026-10-26T12:00:00+00:00")
        db.sources.append_sources([source])
        db.relationship_events.record_pending({
            "event_id": "event1", "verifier_version": VERIFIER_VERSION,
            "subject_id": "u1", "reason": "gratitude", "strength": "mild",
            "scope": "private", "event_at": source.at,
            "primary_source_id": source.id, "source_ids": (source.id,),
        })

        class Provider:
            async def text_chat(self, **_kwargs):
                return SimpleNamespace(completion_text=json.dumps({
                    "reason": "gratitude", "source_ids": [source.id],
                    "target": "assistant", "decision": "verified",
                }))

        async def provider_for(_session):
            return Provider()
        class Journal:
            @contextmanager
            def span(self, *_args, **_kwargs):
                yield {}

            def record(self, *_args, **_kwargs):
                pass

        cache = Cache(db.artifacts)

        service = MaintenanceService(
            artifacts=db.artifacts, sources=db.sources, cache=cache, journal=Journal(),
            task_id=lambda: "test", logger=SimpleNamespace(
                info=lambda *_: None, warning=lambda *_: None),
            clock=lambda: datetime.fromisoformat(source.at),
            relationship_events=db.relationship_events, provider_for=provider_for,
        )
        assert asyncio.run(service.weekly())["relationships"] == 1
        assert db.relationship_events.pending(10) == ()
        assert RelationshipReader(cache).get("u1").warmth > 0
    finally:
        db.close()
"""
        result = subprocess.run(
            [sys.executable, "-I", "-c", script, str(Path(__file__).resolve().parents[2])],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
if __name__ == "__main__":
    unittest.main()
