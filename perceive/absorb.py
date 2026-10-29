"""Coordinate parsing, evidence validation, deduplication and Artifact construction; read cache only, never call models or persist memory.

协调解析、证据校验、去重及记忆构造，仅查询缓存，不调用模型或写入记忆。
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from contextlib import AbstractContextManager, nullcontext
from collections.abc import Callable
from typing import Any

try:  # Plugin namespace / 插件命名空间。
    from ..app.contracts import DialogueTurn, WriteOutcome
    from ..core.artifact import Artifact, Lineage, Strength, TimeSpan, content_of, make, validate
    from ..core.relationship import RELATIONSHIP_POLICY_VERSION
    from ..perceive.behavior import (
        DEFAULT_BEHAVIOR_CONFIDENCE,
        behavior_boundary,
        behavior_of,
        check_payload,
        dedupe_behaviors,
        evidence_ids,
        is_behavior,
        is_behavior_key,
        payload_of,
        validate_evidence,
    )
    from ..perceive.extract import (
        ExtractionParseError,
        filter_duplicates,
        parse_response_checked,
    )
    from ..perceive.relationship import (
        is_relationship_observation,
        observation_boundary,
        validate_observation,
    )
    from ..app.ports import ArtifactCache, SourceStore
except ImportError:  # Top-level package / 顶层包。
    from app.contracts import DialogueTurn, WriteOutcome
    from core.artifact import Artifact, Lineage, Strength, TimeSpan, content_of, make, validate
    from core.relationship import RELATIONSHIP_POLICY_VERSION
    from app.ports import ArtifactCache, SourceStore

    from perceive.behavior import (
        DEFAULT_BEHAVIOR_CONFIDENCE,
        behavior_boundary,
        behavior_of,
        check_payload,
        dedupe_behaviors,
        evidence_ids,
        is_behavior,
        is_behavior_key,
        payload_of,
        validate_evidence,
    )
    from perceive.extract import (
        ExtractionParseError,
        filter_duplicates,
        parse_response_checked,
    )
    from perceive.relationship import (
        is_relationship_observation,
        observation_boundary,
        validate_observation,
    )

MAX_ITEMS = 6

Log = Callable[[str], None]

from .extraction_rules import (
    _parse_time, _date_or_none, _event_at, _subject_id, _num, strength_of, worth_now, _boundary,
    _PLAN, _FACT, _STRONG, _NOT_WORTH,
)
from .dialogue_evidence import _dialog_rows, dialogue_of, recover_parents


def existing_texts(cache: ArtifactCache | None) -> list[str]:
    """Read cached memory text for compatibility deduplication / 读取供兼容去重使用的缓存记忆正文。"""
    if cache is None:
        return []
    try:
        return [content_of(a) for a in cache.active("memory")]
    except Exception:  # noqa: BLE001 - Unavailable history stays empty / 历史不可用时按空处理。
        return []


def existing_texts_by_subject(cache: ArtifactCache | None) -> dict[str, list[str]]:
    """Read deduplication history by subject, scope and behavior/relationship evidence / 按主体、范围及行为或关系证据读取去重历史。"""
    if cache is None:
        return {}
    out: dict[str, list[str]] = {}
    try:
        for art in cache.active("memory"):
            boundary = _boundary(str(art.header.scope or "private"),
                                 str(art.header.subject_id or ""))
            if is_behavior(art.payload):
                boundary = behavior_boundary(
                    boundary,
                    behavior_of(art.payload),
                    art.header.lineage.sources,
                )
            elif is_relationship_observation(art.payload):
                boundary = observation_boundary(
                    boundary,
                    art.payload,
                    art.header.lineage.sources,
                )
            out.setdefault(boundary, []).append(content_of(art))
    except Exception:  # noqa: BLE001 - Unavailable cache history stays empty / 缓存历史不可用时按空处理。
        return {}
    return out


def owner_of(items: list[DialogueTurn]) -> str:
    """Read the sole nonempty input session, otherwise return empty / 读取输入中唯一非空的会话，否则返回空。"""
    sessions = {turn.session_id for turn in items if turn.session_id}
    return next(iter(sessions)) if len(sessions) == 1 else ""


@dataclass(frozen=True)
class ExtractionPlan:
    """Hold validated memory candidates and failures without owning persistence / 保存验证后的候选记忆及失败信息，不负责持久化。"""
    artifacts: tuple[Artifact, ...] = ()
    skipped: int = 0
    errors: tuple[str, ...] = ()
    retryable: bool = False
    outcome: WriteOutcome | None = None


def build_plan(
    items: list[DialogueTurn],
    context: list[DialogueTurn],
    raw: str,
    cache: ArtifactCache | None,
    owner_id: str = "",
    log: Log = lambda _msg: None,
    *,
    strict: bool = False,
    require_evidence: bool = False,
    stage: Callable[[str], AbstractContextManager[object]] = lambda _name: (
        nullcontext()
    ),
) -> ExtractionPlan:
    """Read supplied context/cache and prepare candidates; never commit, link or mutate cache / 读取给定上下文及缓存并准备候选，不提交、建联或修改缓存。"""
    owner = owner_of(items)
    available = {turn.source_id: turn for turn in context if turn.source_id}
    source_ids = tuple(turn.source_id for turn in items if turn.source_id)
    group = ":GroupMessage:" in owner
    scope = "shared" if group or not owner else "private"
    senders = {turn.speaker_id for turn in items if turn.speaker_id}
    user_senders = {
        turn.speaker_id for turn in context
        if turn.speaker_id and turn.role == "user"
    }
    said_by = "owner"
    if group:
        said_by = next(iter(user_senders)) if len(user_senders) == 1 else "group"
    default_subject = (
        next(iter(user_senders)) if len(user_senders) == 1
        else owner_id or owner or ""
    )

    def boundary_of(item: dict) -> str:
        base = _boundary(scope, _subject_id(item, owner, default_subject, owner_id))
        if is_behavior(item):
            return behavior_boundary(base, behavior_of(item), evidence_ids(item))
        if is_relationship_observation(item):
            return observation_boundary(base, item, evidence_ids(item))
        return base

    try:
        with stage("response.parse"):
            parsed = parse_response_checked(raw)
    except ExtractionParseError as exc:
        if strict:
            raise
        return ExtractionPlan(outcome=WriteOutcome(
            errors=(f"parse: {exc}",), model_failed=True, retryable=True
        ))

    checked: list[tuple[dict, tuple[str, ...]]] = []
    for item in parsed[:MAX_ITEMS]:
        candidate = {**item, "owner_umo": owner} if owner else dict(item)
        try:
            check_payload(candidate)
            validate_observation(candidate)
            evidence = validate_evidence(candidate, available, session_id=owner)
            if is_relationship_observation(candidate) and not evidence:
                raise ValueError("relationship observation requires evidence_source_ids")
            if require_evidence:
                if not evidence:
                    raise ValueError(
                        "evidence_source_ids required for multi-topic batch"
                    )
                evidence_topics = {
                    str(getattr(available[value], "topic_id", "") or "").strip()
                    for value in evidence
                }
                evidence_topics.discard("")
                if len(evidence_topics) > 1:
                    raise ValueError(
                        "evidence_source_ids cross topics in multi-topic batch"
                    )
        except ValueError as exc:
            log(f"evidence validation failed: {type(exc).__name__}")
            return ExtractionPlan(outcome=WriteOutcome(
                errors=(f"evidence: {exc}",), model_failed=True, retryable=True
            ))
        checked.append((candidate, evidence))
    evidence_of = {id(item): evidence for item, evidence in checked}
    parsed = [item for item, _ in checked]

    with stage("memory.deduplicate"):
        existing = existing_texts_by_subject(cache)
        repeated = {key for key in existing if is_behavior_key(key)}
        parsed = dedupe_behaviors(
            parsed, existing_keys=repeated, boundary_of=boundary_of
        )
        parsed = filter_duplicates(
            parsed,
            existing_by_subject=existing,
            subject_of=boundary_of,
        )
    if not parsed:
        return ExtractionPlan(outcome=WriteOutcome(skipped=len(items)))

    artifacts: list[Artifact] = []
    skipped = 0
    errors: list[str] = []
    retryable = False
    for item in parsed:
        evidence = evidence_of.get(id(item), ())
        try:
            payload = payload_of(item)
            if is_relationship_observation(item):
                payload["relationship_policy_version"] = RELATIONSHIP_POLICY_VERSION
            if group and len(senders) > 1:
                payload["speakers"] = sorted(senders)
            strength = strength_of(item)
            if not source_ids:
                payload["legacy_no_source"] = True
                strength["confidence"] = min(
                    float(strength.get("confidence", 1.0)), 0.5
                )
            with stage("artifact.validate"):
                art = make(
                    "memory",
                    payload,
                    strength=strength,
                    scope=scope,
                    said_by=said_by,
                    subject_id=_subject_id(item, owner, default_subject, owner_id),
                    lineage=Lineage(sources=evidence or source_ids),
                    time=TimeSpan(
                        created=_event_at(item, context),
                        valid_from=_date_or_none(item.get("valid_from")),
                        valid_to=_date_or_none(item.get("valid_to")),
                    ),
                )
                validate(art)
            artifacts.append(art)
        except Exception as exc:
            skipped += 1
            retryable = True
            errors.append(f"construct: {exc}")
            log(f"artifact validation failed: {type(exc).__name__}")
    return ExtractionPlan(tuple(artifacts), skipped, tuple(errors), retryable)
