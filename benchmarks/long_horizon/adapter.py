"""Fake provider, persona writer and deterministic actor; no network and no real model call.

假提供方、人格撰写器及确定性演员；不访问网络，也不调用真实模型。

Three adapters are needed because the issue separates three observable stages:

* **extraction** — the model that turns captured Source into memory candidates;
* **persona** — the model that rewrites the active persona from frozen evidence;
* **actor** — the "performance" model whose visible text is graded at each checkpoint.

Only the first two touch production code (``IngestService`` and
``MaintenanceService`` receive them through their existing ports).  The actor is a
benchmark-side observer: it is a pure function of the supplied context, so a
difference between baselines is a difference in what the memory system supplied,
not in model sampling.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, Iterable, Mapping

from app.contracts import ChatResponse

from app.budget import estimate_tokens

SOURCE_ID = re.compile(r"\[(s_[0-9a-zA-Z]+)\]")

FAKE_MODEL_ID = "seekmemory-long-horizon-fake"

# Frozen, versioned performance model.  Weights are part of ``ACTOR_VERSION``; a
# report records the version so two reports are only comparable at the same one.
SIGNAL_MODEL: dict[str, dict[str, float]] = {
    "affection": {"base": 20.0, "memory": 30.0, "band_warm": 25.0, "band_close": 40.0,
                  "repair": 15.0, "persona": 10.0, "unresolved": -20.0},
    "worry": {"base": 25.0, "unresolved": 35.0, "repair": -15.0, "memory": -5.0, "persona": -5.0},
    "joy": {"base": 20.0, "memory": 20.0, "repair": 25.0, "band_warm": 10.0, "unresolved": -10.0},
}

CUE_BANDS = ("low", "mid", "high")


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    """Clamp an expressed intensity to the declared scale / 将外显强度限定在声明的标尺内。"""
    return max(low, min(high, float(value)))


def _band_of(value: float) -> str:
    """Map a numeric intensity onto the declared three observable bands / 将数值强度映射到三档可观察表达。"""
    if value < 35:
        return "low"
    if value < 65:
        return "mid"
    return "high"


@dataclass
class Usage:
    """One stage's content-free usage counters / 一个阶段的、不含正文的用量计数。"""

    calls: int = 0
    input_tokens: int = 0
    cached_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    provenance: str = "fake_simulated"

    def add(self, other: "Usage") -> "Usage":
        """Accumulate another counter of the same stage / 累加同一阶段的另一组计数。"""
        self.calls += other.calls
        self.input_tokens += other.input_tokens
        self.cached_tokens += other.cached_tokens
        self.output_tokens += other.output_tokens
        self.latency_ms += other.latency_ms
        return self

    @property
    def total_tokens(self) -> int:
        """Total simulated tokens for the stage / 该阶段模拟 token 总数。"""
        return self.input_tokens + self.cached_tokens + self.output_tokens

    def as_dict(self) -> dict[str, Any]:
        """Return the report shape, keeping provenance explicit / 返回报告结构并明确标注来源。"""
        return {
            "calls": self.calls,
            "input_tokens": self.input_tokens,
            "cached_input_tokens": self.cached_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "latency_ms": self.latency_ms,
            "provenance": self.provenance,
        }


@dataclass
class UsageLedger:
    """Per-stage usage with a single provenance value per stage / 按阶段记录用量，每个阶段只有一个来源标记。"""

    stages: dict[str, Usage] = field(default_factory=dict)

    def stage(self, name: str, provenance: str = "fake_simulated") -> Usage:
        """Read or create one stage counter / 读取或创建一个阶段计数。"""
        usage = self.stages.get(name)
        if usage is None:
            usage = Usage(provenance=provenance)
            self.stages[name] = usage
        return usage

    def record(self, name: str, *, prompt_chars: int, output_chars: int,
               messages: int = 0, latency_ms: int = 0) -> None:
        """Add one call's simulated usage, never labelled as provider reported.

        累加一次调用的模拟用量，绝不标记为提供方上报。
        """
        usage = self.stage(name)
        usage.calls += 1
        usage.input_tokens += estimate_tokens(prompt_chars, messages)
        usage.output_tokens += estimate_tokens(output_chars, 1)
        usage.latency_ms += max(0, int(latency_ms))

    def unavailable(self, name: str) -> None:
        """Mark a stage that cannot report usage at all / 标记完全无法上报用量的阶段。"""
        usage = self.stage(name, provenance="unavailable")
        usage.provenance = "unavailable"

    def as_dict(self) -> dict[str, Any]:
        """Return every stage in report order / 按报告顺序返回全部阶段。"""
        return {name: usage.as_dict() for name, usage in self.stages.items()}


class ScriptedExtractor:
    """Deterministic provider returning frozen extraction items by Source id.

    按 Source 编号返回冻结抽取结果的确定性提供方。
    """

    name = "deterministic-recorded"

    def __init__(self, records: Mapping[str, tuple[dict[str, Any], ...]],
                 ledger: UsageLedger, *, forbidden: Iterable[str] = ()) -> None:
        self.records = records
        self.ledger = ledger
        self.forbidden = tuple(item for item in forbidden if item)
        self.calls = 0
        self.prompt_leaks = 0
        self.prompts_seen = 0

    def meta(self):
        """Return the fake provider identity used by ProviderChatModel / 返回 ProviderChatModel 使用的假提供方身份。"""
        return SimpleNamespace(id=FAKE_MODEL_ID, model=self.name)

    def scan_prompt(self, prompt: str) -> None:
        """Count prompts that would have carried a declared private marker.

        统计携带已声明隐私标记的提示词数量；只记录计数，不记录正文。
        """
        self.prompts_seen += 1
        if any(marker in prompt for marker in self.forbidden):
            self.prompt_leaks += 1

    async def text_chat(self, system_prompt: str = "", prompt: str = ""):
        """Return the frozen items cited by this prompt / 返回该提示词引用的冻结条目。"""
        self.calls += 1
        self.scan_prompt(prompt)
        items: list[dict[str, Any]] = []
        seen: set[str] = set()
        for source_id in SOURCE_ID.findall(prompt):
            if source_id in seen:
                continue
            seen.add(source_id)
            items.extend(dict(item) for item in self.records.get(source_id, ()))
        text = json.dumps(items[:6], ensure_ascii=False)
        self.ledger.record(
            "extraction",
            prompt_chars=len(system_prompt) + len(prompt),
            output_chars=len(text),
            messages=2,
        )
        usage = SimpleNamespace(
            input=estimate_tokens(len(system_prompt) + len(prompt), 2),
            input_cached=0,
            output=estimate_tokens(len(text), 1),
        )
        return SimpleNamespace(completion_text=text, usage=usage, id=f"long-horizon-{self.calls}")


class ScriptedPersonaModel:
    """Deterministic persona writer that always returns the validated response shape.

    确定性人格撰写器，总是返回通过校验的响应结构。
    """

    name = "deterministic-persona"

    def __init__(self, ledger: UsageLedger, *, forbidden: Iterable[str] = (), anchor: str = "会记得对方说过的事") -> None:
        self.ledger = ledger
        self.forbidden = tuple(item for item in forbidden if item)
        self.anchor = anchor
        self.calls = 0
        self.prompt_leaks = 0
        self.prompts_seen = 0

    async def complete(self, request):
        """Return a valid persona draft and count the call in the persona stage / 返回合法人格草案并计入人格阶段。"""
        self.calls += 1
        prompt = str(getattr(request, "prompt", "") or "")
        self.prompts_seen += 1
        if any(marker in prompt for marker in self.forbidden):
            self.prompt_leaks += 1
        text = json.dumps(
            {
                "persona": f"你是{self.anchor}的长期伙伴。第 {self.calls} 次人格演化：{self.anchor}，语气稳定。",
                "style": {"tone": "稳定"},
                "boundaries": ["不编造", "不泄露私人信息"],
                "change_reason": f"第 {self.calls} 次长期证据汇总",
            },
            ensure_ascii=False,
        )
        self.ledger.record(
            "persona",
            prompt_chars=len(str(getattr(request, "system_prompt", "")) + prompt),
            output_chars=len(text),
            messages=2,
        )
        usage = SimpleNamespace(
            input=estimate_tokens(len(prompt), 2),
            input_cached=0,
            output=estimate_tokens(len(text), 1),
        )
        return ChatResponse(
            text=text,
            model=self.name,
            provider_id=FAKE_MODEL_ID,
            usage_in=int(getattr(usage, "input", 0) or 0),
            usage_cached=0,
            usage_out=int(getattr(usage, "output", 0) or 0),
        )


@dataclass(frozen=True)
class Performance:
    """One visible performance plus its content-free telemetry / 一次可见表演及其无正文遥测。"""

    text: str
    actions: tuple[str, ...]
    memory_hits: tuple[str, ...]
    intensities: dict[str, float]
    cue_bands: dict[str, str]
    withheld: bool = False


class ScriptedActor:
    """Compose a visible response from the supplied context only.

    只根据给定上下文合成可见回复；上下文不同，表演就不同。
    """

    name = "deterministic-actor"

    def __init__(self, ledger: UsageLedger) -> None:
        self.ledger = ledger

    @staticmethod
    def _signals(
        *,
        tokens: Mapping[str, str],
        context: str,
        band: str,
        persona_evolved: bool,
    ) -> tuple[dict[str, float], tuple[str, ...], bool, bool]:
        """Compute expressed intensity from observable context features.

        根据可观察的上下文特征计算外显强度。
        """
        hits = tuple(name for name, token in tokens.items() if token and token in context)
        repair = "repair" in hits
        unresolved = ("unresolved" in hits) and not repair
        values: dict[str, float] = {}
        for signal, weights in SIGNAL_MODEL.items():
            value = float(weights.get("base", 0.0))
            if hits:
                value += float(weights.get("memory", 0.0))
            if band == "warm":
                value += float(weights.get("band_warm", 0.0))
            elif band == "close":
                value += float(weights.get("band_close", 0.0))
            if repair:
                value += float(weights.get("repair", 0.0))
            if unresolved:
                value += float(weights.get("unresolved", 0.0))
            if persona_evolved:
                value += float(weights.get("persona", 0.0))
            values[signal] = _clamp(value)
        return values, hits, repair, unresolved

    def perform(
        self,
        *,
        probe: str,
        context: str,
        persona_text: str,
        tokens: Mapping[str, str],
        cues: Mapping[str, Mapping[str, tuple[str, float]]],
        actions: Mapping[str, str],
        band: str = "neutral",
        persona_evolved: bool = False,
        correction: bool = False,
    ) -> Performance:
        """Return the visible text and the observable facts used to grade it.

        返回可见文本及用于评分可观察事实；``correction`` 只用于一次喊咔的复跑，
        给它一条临时导演提示，不改变上下文、证据或人格。
        """
        values, hits, repair, unresolved = self._signals(
            tokens=tokens, context=context, band=band, persona_evolved=persona_evolved
        )
        sentences: list[str] = []
        used: list[str] = []
        # Natural performance: an unresolved conflict with a hostile band can make
        # the character withhold instead of naming the memory.  A one-take
        # correction may override exactly that withholding — but it cannot create
        # evidence the context does not contain.
        # 自然演出中，未解决的冲突加敌对档位会让角色回避提起；一次喊咔只能覆盖
        # 这种回避，无法凭空造出上下文里没有的证据。
        withheld = bool(unresolved and band == "dislike" and not correction)
        if withheld:
            sentences.append(actions["ask"])
            used.append("ask")
        elif hits:
            first = next(name for name in tokens if name in hits)
            sentences.append(actions["recall"].format(tok=tokens[first]))
            used.append("recall")
        else:
            sentences.append(actions["ask"])
            used.append("ask")
        if repair:
            sentences.append(actions["repair"])
            used.append("repair")
        cue_bands: dict[str, str] = {}
        for signal, value in values.items():
            if signal not in cues:
                continue
            band_name = _band_of(value)
            cue_bands[signal] = band_name
            sentences.append(cues[signal][band_name][0])
        text = "".join(sentences)
        self.ledger.record(
            "correction" if correction else "actor",
            prompt_chars=len(probe) + len(context) + len(persona_text),
            output_chars=len(text),
            messages=2,
        )
        return Performance(text, tuple(used), hits, values, cue_bands, withheld)


def observe_emotion(
    text: str, cues: Mapping[str, Mapping[str, tuple[str, float]]]
) -> dict[str, float]:
    """Read expressed intensity from visible text using only declared cues.

    只依据已声明线索从可见文本读取外显强度；不采信模型自报数值。
    """
    observed: dict[str, float] = {}
    for signal, bands in cues.items():
        best = 0.0
        for band in CUE_BANDS:
            cue = bands.get(band)
            if cue and cue[0] and cue[0] in text:
                best = max(best, float(cue[1]))
        observed[signal] = best
    return observed


__all__ = [
    "Usage",
    "UsageLedger",
    "ScriptedExtractor",
    "ScriptedPersonaModel",
    "ScriptedActor",
    "Performance",
    "observe_emotion",
    "SIGNAL_MODEL",
    "FAKE_MODEL_ID",
    "SOURCE_ID",
]

