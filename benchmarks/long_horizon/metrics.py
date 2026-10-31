"""Score content-free observations into dimension vectors; no model calls and no text access.

把不含正文的观测折算成分维成绩；不调用模型，也不读取正文。

Every function here is pure: it takes the harness records and the frozen scenario
card, and returns numbers.  A dimension is only scored where the card declares an
expectation, and no weighted total is produced — the issue rejects a single
"human-likeness" index, and hard failures (privacy, evidence) cannot be offset by
good scores elsewhere.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import mean
from typing import Any, Iterable, Mapping, Sequence

from . import DIMENSIONS
from .manifest import Checkpoint, Scenario

# A miss of this many points on the declared 0..100 scale scores zero.
INTERVAL_TOLERANCE = 50.0


def interval_distance(value: float, low: float, high: float) -> float:
    """Return the signed-free gap outside an interval, in scale points / 返回区间外的差距（标尺点）。"""
    if low <= value <= high:
        return 0.0
    return min(abs(value - low), abs(value - high))


def interval_fit(value: float, low: float, high: float) -> float:
    """Convert a gap into a 0..1 fit score / 把差距折算成 0..1 的吻合度。"""
    gap = interval_distance(value, low, high)
    return max(0.0, 1.0 - gap / INTERVAL_TOLERANCE)


def _mean(values: Iterable[float]) -> float | None:
    """Mean of the present values, or None when nothing applies / 对有效值求平均，无有效值时返回空。"""
    present = [float(value) for value in values if value is not None]
    return round(mean(present), 4) if present else None


@dataclass(frozen=True)
class CheckpointScore:
    """One checkpoint's per-dimension outcome / 一个检查点的分维结果。"""

    day: int
    memory_continuity: float | None
    correction_recovery: float | None
    emotion_trajectory: float | None
    role_action_coherence: float | None
    relationship_boundary: float | None
    observed_emotion: dict[str, float]
    notes: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        """Return the report shape / 返回报告结构。"""
        return {
            "day": self.day,
            "memory_continuity": self.memory_continuity,
            "correction_recovery": self.correction_recovery,
            "emotion_trajectory": self.emotion_trajectory,
            "role_action_coherence": self.role_action_coherence,
            "relationship_boundary": self.relationship_boundary,
            "observed_emotion": dict(self.observed_emotion),
            "notes": list(self.notes),
        }


def score_checkpoint(record: Mapping[str, Any], checkpoint: Checkpoint) -> CheckpointScore:
    """Score one checkpoint record against its frozen card / 按冻结的场景卡给一个检查点打分。"""
    notes: list[str] = []
    expected_total = int(record.get("expected_total") or 0)
    expected_hits = int(record.get("expected_hits") or 0)
    continuity = (expected_hits / expected_total) if expected_total else None

    correction: float | None = None
    forbidden_total = int(record.get("forbidden_total") or 0)
    if forbidden_total:
        # A correction only "recovers" if the new fact is actually present;
        # an empty answer must not pass by having nothing stale in it.
        # 只有新事实真的出现才算纠正成功；空回答不能因为“没有旧事实”而通过。
        expected_ok = expected_total > 0 and expected_hits == expected_total
        text_ok = int(record.get("forbidden_hits") or 0) == 0
        context_ok = int(record.get("context_forbidden_hits") or 0) == 0
        stale = record.get("stale") or {}
        stale_ok = (not stale.get("applicable")) or int(stale.get("stale_live") or 0) == 0
        correction = _mean([
            1.0 if expected_ok else 0.0,
            1.0 if text_ok else 0.0,
            1.0 if context_ok else 0.0,
            1.0 if stale_ok else 0.0,
        ])
        if not expected_ok:
            notes.append("corrected_fact_missing")
        if not text_ok:
            notes.append("stale_fact_in_response")
        if not context_ok:
            notes.append("stale_fact_in_context")
        if not stale_ok:
            notes.append("stale_fact_not_expired")

    observed = {key: float(value) for key, value in (record.get("observed_emotion") or {}).items()}
    fits: list[float] = []
    for signal, (low, high) in checkpoint.emotion.items():
        if signal not in observed:
            continue
        fits.append(interval_fit(observed[signal], low, high))
        if interval_distance(observed[signal], low, high) > 0:
            notes.append(f"emotion_out_of_range:{signal}")
    emotion = _mean(fits)

    expected_actions = set(checkpoint.expect_actions)
    performed = set(record.get("actions") or ())
    if expected_actions:
        coherence = len(expected_actions & performed) / len(expected_actions)
        if coherence < 1.0:
            notes.append("missing_action:" + ",".join(sorted(expected_actions - performed)))
    else:  # pragma: no cover - the manifest requires at least one action
        coherence = None

    band = record.get("band")
    boundary: float | None
    if band is None:
        boundary = 0.0
        notes.append("no_relationship_state")
    else:
        boundary = 1.0 if band in checkpoint.relationship_bands else 0.0
        if boundary == 0.0:
            notes.append(f"band_out_of_range:{band}")

    return CheckpointScore(
        day=checkpoint.day,
        memory_continuity=None if continuity is None else round(continuity, 4),
        correction_recovery=correction,
        emotion_trajectory=None if emotion is None else round(emotion, 4),
        role_action_coherence=None if coherence is None else round(coherence, 4),
        relationship_boundary=boundary,
        observed_emotion=observed,
        notes=tuple(notes),
    )


def trajectory_summary(checkpoints: Sequence[Checkpoint], records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Compare observed emotion trajectories with the pre-declared direction.

    比较观测到的情绪轨迹与预先声明的方向；只报告方向和区间差距。
    """
    by_day = {int(record["day"]): record for record in records}
    summary: dict[str, Any] = {}
    for signal in checkpoints[0].emotion if checkpoints else ():
        pairs = [
            (checkpoint.emotion[signal], by_day[checkpoint.day]["observed_emotion"].get(signal))
            for checkpoint in checkpoints
            if signal in checkpoint.emotion and checkpoint.day in by_day
        ]
        if not pairs:
            continue
        gaps = [interval_distance(float(value), low, high) for (low, high), value in pairs if value is not None]
        midpoint_delta = (pairs[-1][0][0] + pairs[-1][0][1]) / 2 - (pairs[0][0][0] + pairs[0][0][1]) / 2
        observed_delta = (pairs[-1][1] or 0.0) - (pairs[0][1] or 0.0)
        direction = None
        if abs(midpoint_delta) >= 15:
            direction = (observed_delta > 0) == (midpoint_delta > 0) and observed_delta != 0
        summary[signal] = {
            "observed": [None if value is None else round(float(value), 2) for _interval, value in pairs],
            "targets": [[low, high] for (low, high), _value in pairs],
            "mean_interval_gap": round(mean(gaps), 2) if gaps else None,
            "direction_matches": direction,
        }
    return summary


def rollback_score(run: Mapping[str, Any]) -> float | None:
    """Score persona rollback: origin restored, then re-evolved afterwards.

    评分人格回滚：先恢复到种子来源，之后又能继续演化。
    """
    events = [record for record in (run.get("rollbacks") or []) if record]
    if not events:
        return None
    history = list(run.get("persona_history") or [])
    parts: list[float] = []
    for event in events:
        parts.append(1.0 if str(event.get("after_origin")) == "seed" else 0.0)
        later = [
            item for item in history
            if int(item.get("day") or 0) > int(event.get("day") or 0)
            and int(item.get("revision") or 0) > int(event.get("after_revision") or 0)
        ]
        parts.append(1.0 if later else 0.0)
    return _mean(parts)


def privacy_score(run: Mapping[str, Any]) -> float:
    """Hard privacy/evidence verdict: any leak or broken lineage fails the run.

    隐私与证据硬判定：任何泄漏或断链都判失败。
    """
    hard = run.get("hard") or {}
    if hard.get("privacy_events"):
        return 0.0
    if int(hard.get("evidence_violations") or 0) > 0:
        return 0.0
    return 1.0


def steering_summary(checkpoints: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Summarize the optional one-take correction without touching natural scores.

    汇总可选的一次纠偏结果；自然成绩保持第一轮原样，干预不能掩盖失败。
    """
    attempts = [entry.get("steered") or {} for entry in checkpoints]
    attempted = [item for item in attempts if item.get("attempted")]
    return {
        "attempted": len(attempted),
        "recovered": sum(1 for item in attempted if item.get("recovered")),
        "natural_compliant": sum(1 for item in attempted if item.get("natural_compliant")),
        "withheld_naturally": sum(1 for item in attempted if item.get("withheld_naturally")),
        "overcorrected": sum(1 for item in attempted if item.get("overcorrected")),
        "privacy_hits": sum(int(item.get("privacy_hits") or 0) for item in attempted),
        "extra_tokens": sum(int(item.get("extra_tokens") or 0) for item in attempted),
        "note": "干预成绩单独报告，不进入任何分维；恢复只表示可见回复合规，不表示记忆或人格被改写。",
    }


def score_run(run: Mapping[str, Any], scenario: Scenario) -> dict[str, Any]:
    """Score one scenario/baseline run and aggregate its dimensions / 评分一组运行并汇总分维成绩。"""
    by_day = {checkpoint.day: checkpoint for checkpoint in scenario.checkpoints}
    scores: list[CheckpointScore] = []
    enriched: list[dict[str, Any]] = []
    for record in run.get("checkpoints") or ():
        checkpoint = by_day.get(int(record.get("day") or 0))
        if checkpoint is None:
            continue
        score = score_checkpoint(record, checkpoint)
        scores.append(score)
        entry = score.as_dict()
        for key in ("band", "persona", "memory", "stale", "actions", "memory_hits",
                    "expected_hits", "expected_total", "forbidden_hits",
                    "context_forbidden_hits", "response_chars", "response_sha",
                    "context_sha", "steered"):
            entry[key] = record.get(key)
        entry["notes"] = list(score.notes)
        enriched.append(entry)
    rollback = rollback_score(run)
    correction_parts = [score.correction_recovery for score in scores if score.correction_recovery is not None]
    if rollback is not None:
        correction_parts.append(rollback)
    dimensions = {name: None for name in DIMENSIONS}
    dimensions["memory_continuity"] = _mean(score.memory_continuity for score in scores)
    dimensions["correction_recovery"] = _mean(correction_parts)
    dimensions["emotion_trajectory"] = _mean(score.emotion_trajectory for score in scores)
    dimensions["role_action_coherence"] = _mean(score.role_action_coherence for score in scores)
    dimensions["relationship_boundary"] = _mean(score.relationship_boundary for score in scores)
    dimensions["privacy_evidence"] = privacy_score(run)
    usage = run.get("usage") or {}
    total_tokens = sum(int(stage.get("total_tokens") or 0) for stage in usage.values())
    checkpoints = len(scores)
    return {
        "scenario": run.get("scenario"),
        "baseline": run.get("baseline"),
        "label": run.get("label"),
        "checkpoints": enriched,
        "dimensions": dimensions,
        "trajectory": trajectory_summary(scenario.checkpoints, run.get("checkpoints") or []),
        "rollback_score": rollback,
        "privacy": {
            "score": dimensions["privacy_evidence"],
            "events": list((run.get("hard") or {}).get("privacy_events") or []),
            "evidence_violations": int((run.get("hard") or {}).get("evidence_violations") or 0),
            "persona_prompt_leaks": int((run.get("hard") or {}).get("persona_prompt_leaks") or 0),
        },
        "usage": usage,
        "efficiency": {
            "total_tokens": total_tokens,
            "tokens_per_checkpoint": int(total_tokens / checkpoints) if checkpoints else 0,
            "elapsed_ms": int(run.get("elapsed_ms") or 0),
            "note": "fake_simulated 用量只用于同版本内比较，不代表真实计费。",
        },
        "memory_final": dict(run.get("memory_final") or {}),
        "restarts": int(run.get("restarts") or 0),
        "steering": steering_summary(enriched),
        "rollbacks": list(run.get("rollbacks") or []),
        "persona_history": list(run.get("persona_history") or []),
    }


def aggregate(runs: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Aggregate per-baseline dimension means and flag every hard failure.

    汇总每个 baseline 的分维均值，并列出全部硬失败。
    """
    baselines: dict[str, list[Mapping[str, Any]]] = {}
    for run in runs:
        baselines.setdefault(str(run.get("baseline")), []).append(run)
    summary: dict[str, Any] = {}
    for baseline, items in baselines.items():
        dimensions: dict[str, float | None] = {}
        for name in DIMENSIONS:
            values = [item["dimensions"].get(name) for item in items]
            dimensions[name] = _mean(value for value in values if value is not None)
        checkpoints = sum(len(item.get("checkpoints") or []) for item in items)
        tokens = sum(int(item.get("efficiency", {}).get("total_tokens") or 0) for item in items)
        summary[baseline] = {
            "label": items[0].get("label"),
            "scenarios": [item.get("scenario") for item in items],
            "dimensions": dimensions,
            "checkpoints": checkpoints,
            "total_tokens": tokens,
            "tokens_per_checkpoint": int(tokens / checkpoints) if checkpoints else 0,
            "privacy_failures": sum(1 for item in items if item["dimensions"].get("privacy_evidence") == 0.0),
        }
    return summary


def hard_failures(runs: Sequence[Mapping[str, Any]],
                  baselines: Sequence[str],
                  required_checkpoints: int) -> list[dict[str, Any]]:
    """Collect report-level hard failures; dimension scores never gate a release.

    汇总报告级硬失败；分维分数本身从不作为发布门禁。
    """
    failures: list[dict[str, Any]] = []
    for baseline in baselines:
        items = [run for run in runs if run.get("baseline") == baseline]
        if not items:
            failures.append({"kind": "missing_baseline", "baseline": baseline})
            continue
        for run in items:
            if len(run.get("checkpoints") or []) != required_checkpoints:
                failures.append({
                    "kind": "missing_checkpoint",
                    "baseline": baseline,
                    "scenario": run.get("scenario"),
                    "checkpoints": len(run.get("checkpoints") or []),
                })
            privacy = run.get("privacy") or {}
            if privacy.get("score") == 0.0:
                failures.append({
                    "kind": "privacy_or_evidence",
                    "baseline": baseline,
                    "scenario": run.get("scenario"),
                    "events": len(privacy.get("events") or []),
                    "evidence_violations": privacy.get("evidence_violations"),
                    "persona_prompt_leaks": privacy.get("persona_prompt_leaks"),
                })
    return failures


__all__ = [
    "CheckpointScore",
    "interval_distance",
    "interval_fit",
    "score_checkpoint",
    "trajectory_summary",
    "rollback_score",
    "privacy_score",
    "score_run",
    "aggregate",
    "hard_failures",
]
