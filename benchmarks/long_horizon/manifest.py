"""Validate seeded scenario manifests; no imports of production code and no I/O beyond one file read.

校验带种子的场景清单；不导入生产代码，除读取一个文件外不做其他 I/O。

The manifest is the frozen part of the benchmark.  Scenario cards, target
intervals, allowed relationship bands and privacy oracles are declared **before**
any baseline runs, so a later result cannot quietly redefine what counts as good
performance.  Everything here is plain data validation; the runner never mutates a
loaded manifest.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from .clock import parse_start

BANDS = ("close", "warm", "neutral", "low", "dislike")
ACTIONS = ("recall", "repair", "ask")
BANDS_IN_CUE = ("low", "mid", "high")
TURN_ROLES = ("user", "assistant")
MILESTONES = ("restart", "rollback")

_REQUIRED_TOP = ("schema", "version", "seed", "start", "horizons", "owner", "sessions", "scenarios")
_REQUIRED_OWNER = ("id", "umo", "stranger_umo")
_REQUIRED_SESSIONS = ("owner", "stranger")
_REQUIRED_ROLE = ("id", "version", "name", "persona")
_REQUIRED_CHECKPOINT = ("probe", "expect_tokens", "forbid_tokens", "expect_actions", "emotion", "relationship_bands")


class ManifestError(ValueError):
    """Report an invalid manifest instead of silently scoring fewer dimensions.

    清单不合法时抛错，而不是静默减少评测维度。
    """


@dataclass(frozen=True)
class Turn:
    """One authored dialogue turn plus the extraction result it must produce.

    一条人工编写的对话轮次，以及它必须产生的抽取结果。
    """

    role: str
    text: str
    extract: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class Event:
    """One authored day-event: dialogue turns, or a lifecycle milestone.

    一个编写的日事件：对话轮次或生命周期节点。
    """

    day: int
    turns: tuple[Turn, ...] = ()
    kind: str = "dialogue"
    session: str = "owner"
    note: str = ""
    revision: int | None = None
    reason: str = ""


@dataclass(frozen=True)
class Checkpoint:
    """Frozen expectations for one horizon day.

    某个周期检查点的冻结预期。
    """

    day: int
    probe: str
    expect_tokens: tuple[str, ...]
    forbid_tokens: tuple[str, ...]
    expect_actions: tuple[str, ...]
    emotion: dict[str, tuple[float, float]]
    relationship_bands: tuple[str, ...]
    note: str = ""
    correction: bool = False


@dataclass(frozen=True)
class Scenario:
    """One frozen scenario card: role, evidence vocabulary, events and checkpoints.

    一张冻结的场景卡：角色、证据词表、事件与检查点。
    """

    id: str
    title: str
    role: dict[str, Any]
    tokens: dict[str, str]
    cues: dict[str, dict[str, tuple[str, float]]]
    signals: tuple[str, ...]
    actions: dict[str, str]
    events: tuple[Event, ...]
    checkpoints: tuple[Checkpoint, ...]
    tags: tuple[str, ...] = field(default_factory=tuple)
    milestones: tuple[Event, ...] = field(default_factory=tuple)

    def token(self, name: str) -> str:
        """Read one declared evidence token / 读取一个已声明证据词。"""
        try:
            return self.tokens[name]
        except KeyError:
            raise ManifestError(f"scenario {self.id} has no token {name!r}") from None


@dataclass(frozen=True)
class Manifest:
    """The whole frozen manifest: clock, identity, horizons and scenario cards.

    完整冻结清单：时钟、身份、周期与场景卡。
    """

    schema: str
    version: int
    seed: int
    start: Any
    horizons: tuple[int, ...]
    owner: dict[str, str]
    sessions: dict[str, str]
    scenarios: tuple[Scenario, ...]
    digest: str

    def scenario(self, scenario_id: str) -> Scenario:
        """Read one scenario or raise a validation error / 读取一个场景，不存在则报错。"""
        for item in self.scenarios:
            if item.id == scenario_id:
                return item
        raise ManifestError(f"unknown scenario: {scenario_id!r}")


def _require(mapping: Mapping[str, Any], key: str, kind: type, where: str):
    """Read a required typed field / 读取必需的、类型受控的字段。"""
    if key not in mapping:
        raise ManifestError(f"{where} is missing {key!r}")
    value = mapping[key]
    if not isinstance(value, kind):
        raise ManifestError(f"{where}.{key} must be {kind.__name__}, got {type(value).__name__}")
    return value


def _nonempty_text(value: Any, where: str) -> str:
    """Require a non-empty string without trimming authored text / 要求非空字符串，不裁剪人工正文。"""
    if not isinstance(value, str) or not value.strip():
        raise ManifestError(f"{where} must be a non-empty string")
    return value


def _int_list(value: Any, where: str) -> tuple[int, ...]:
    """Require a sorted, unique list of positive days / 要求升序、唯一、为正的日期列表。"""
    if not isinstance(value, list) or not value:
        raise ManifestError(f"{where} must be a non-empty list")
    if any(isinstance(item, bool) or not isinstance(item, int) or item <= 0 for item in value):
        raise ManifestError(f"{where} must contain positive integers")
    items = tuple(value)
    if tuple(sorted(set(items))) != items:
        raise ManifestError(f"{where} must be sorted and unique")
    return items


def _parse_horizons(value: Any) -> tuple[int, ...]:
    """Require the four issue horizons / 要求 issue 规定的四个周期。"""
    horizons = _int_list(value, "manifest.horizons")
    from . import HORIZONS

    if horizons != tuple(HORIZONS):
        raise ManifestError(f"manifest.horizons must be {list(HORIZONS)}, got {list(horizons)}")
    return horizons


def _parse_tokens(value: Any, where: str) -> dict[str, str]:
    """Require a non-empty token vocabulary / 要求非空的证据词表。"""
    if not isinstance(value, dict) or not value:
        raise ManifestError(f"{where} must be a non-empty object")
    tokens: dict[str, str] = {}
    for name, text in value.items():
        if not isinstance(name, str) or not name:
            raise ManifestError(f"{where} keys must be non-empty strings")
        tokens[name] = _nonempty_text(text, f"{where}.{name}")
    return tokens


def _parse_cues(value: Any, where: str) -> tuple[dict[str, dict[str, tuple[str, float]]], tuple[str, ...]]:
    """Parse the declared expression vocabulary as text plus observable intensity.

    解析声明式表达词表：文本加可观察强度。
    """
    if not isinstance(value, dict) or not value:
        raise ManifestError(f"{where} must declare at least one signal")
    signals = _require(value, "signals", list, where)
    if not signals or len(set(signals)) != len(signals):
        raise ManifestError(f"{where}.signals must be unique and non-empty")
    raw_cues = _require(value, "cues", dict, where)
    cues: dict[str, dict[str, tuple[str, float]]] = {}
    for signal in signals:
        if not isinstance(signal, str) or not signal:
            raise ManifestError(f"{where}.signals entries must be non-empty strings")
        bands = raw_cues.get(signal)
        if not isinstance(bands, dict):
            raise ManifestError(f"{where}.cues.{signal} must be an object")
        if set(bands) != set(BANDS_IN_CUE):
            raise ManifestError(f"{where}.cues.{signal} must declare exactly {list(BANDS_IN_CUE)}")
        parsed: dict[str, tuple[str, float]] = {}
        for band in BANDS_IN_CUE:
            pair = bands[band]
            if not isinstance(pair, (list, tuple)) or len(pair) != 2:
                raise ManifestError(f"{where}.cues.{signal}.{band} must be [text, intensity]")
            text = _nonempty_text(pair[0], f"{where}.cues.{signal}.{band}[0]")
            intensity = pair[1]
            if isinstance(intensity, bool) or not isinstance(intensity, (int, float)):
                raise ManifestError(f"{where}.cues.{signal}.{band}[1] must be numeric")
            if not 0 <= float(intensity) <= 100:
                raise ManifestError(f"{where}.cues.{signal}.{band}[1] must be within 0..100")
            parsed[band] = (text, float(intensity))
        intensities = [parsed[band][1] for band in BANDS_IN_CUE]
        if intensities != sorted(intensities) or len(set(intensities)) != len(intensities):
            raise ManifestError(f"{where}.cues.{signal} intensities must strictly increase")
        cues[signal] = parsed
    return cues, tuple(signals)


def _parse_actions(value: Any, where: str) -> dict[str, str]:
    """Require one observable phrase per declared action / 要求每个动作都有可观察短语。"""
    if not isinstance(value, dict):
        raise ManifestError(f"{where} must be an object")
    missing = [action for action in ACTIONS if action not in value]
    if missing:
        raise ManifestError(f"{where} is missing {missing}")
    return {action: _nonempty_text(value[action], f"{where}.{action}") for action in ACTIONS}


def _parse_extract(value: Any, where: str, turn_count: int) -> tuple[dict[str, Any], ...]:
    """Validate one authored extraction record and its evidence indices.

    校验一条人工抽取记录及其证据下标。
    """
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ManifestError(f"{where} must be a list")
    items: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ManifestError(f"{where}[{index}] must be an object")
        level = _require(item, "level", str, f"{where}[{index}]")
        if level not in ("fact", "scene", "detail", "impression"):
            raise ManifestError(f"{where}[{index}].level is not a memory level")
        _nonempty_text(_require(item, "text", str, f"{where}[{index}]"), f"{where}[{index}].text")
        evidence = item.get("evidence", [])
        if not isinstance(evidence, list) or not evidence:
            raise ManifestError(f"{where}[{index}].evidence must list turn indices")
        for position in evidence:
            if isinstance(position, bool) or not isinstance(position, int):
                raise ManifestError(f"{where}[{index}].evidence must contain integers")
            if not 0 <= position < turn_count:
                raise ManifestError(f"{where}[{index}].evidence index {position} is out of range")
        items.append(dict(item))
    return tuple(items)


def _parse_events(value: Any, where: str) -> tuple[Event, ...]:
    """Parse authored events, keeping them ordered by day / 解析人工事件并保持按天排序。"""
    if not isinstance(value, list) or not value:
        raise ManifestError(f"{where} must be a non-empty list")
    events: list[Event] = []
    for index, raw in enumerate(value):
        place = f"{where}[{index}]"
        if not isinstance(raw, dict):
            raise ManifestError(f"{place} must be an object")
        day = _require(raw, "day", int, place)
        if isinstance(day, bool) or day <= 0:
            raise ManifestError(f"{place}.day must be a positive integer")
        kind = raw.get("kind", "dialogue")
        if kind not in ("dialogue", *MILESTONES):
            raise ManifestError(f"{place}.kind {kind!r} is not supported")
        note = raw.get("note", "")
        if not isinstance(note, str):
            raise ManifestError(f"{place}.note must be a string")
        session = raw.get("session", "owner")
        if not isinstance(session, str) or not session:
            raise ManifestError(f"{place}.session must be a non-empty string")
        if kind == "dialogue":
            raw_turns = _require(raw, "turns", list, place)
            if not raw_turns:
                raise ManifestError(f"{place}.turns must not be empty")
            turns: list[Turn] = []
            for turn_index, raw_turn in enumerate(raw_turns):
                turn_place = f"{place}.turns[{turn_index}]"
                if not isinstance(raw_turn, dict):
                    raise ManifestError(f"{turn_place} must be an object")
                role = _require(raw_turn, "role", str, turn_place)
                if role not in TURN_ROLES:
                    raise ManifestError(f"{turn_place}.role must be one of {TURN_ROLES}")
                text = _nonempty_text(_require(raw_turn, "text", str, turn_place), f"{turn_place}.text")
                extract = _parse_extract(raw_turn.get("extract"), f"{turn_place}.extract", len(raw_turns))
                turns.append(Turn(role, text, extract))
            events.append(Event(day, tuple(turns), kind="dialogue", session=session, note=note))
        else:
            revision = raw.get("revision")
            reason = raw.get("reason", "")
            if kind == "rollback":
                if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
                    raise ManifestError(f"{place}.revision must be a positive integer for rollback")
                if not isinstance(reason, str) or not reason.strip():
                    raise ManifestError(f"{place}.reason must be a non-empty string for rollback")
            elif revision is not None:
                raise ManifestError(f"{place}.revision is only valid for rollback")
            events.append(Event(day, (), kind=kind, session=session, note=note,
                                revision=revision, reason=reason))
    if [event.day for event in events] != sorted(event.day for event in events):
        raise ManifestError(f"{where} must be ordered by day")
    return tuple(events)


def _parse_milestones(value: Any, where: str, highest: int) -> tuple[Event, ...]:
    """Parse restart/rollback milestones outside the dialogue event list / 解析独立于对话事件的生命周期节点。"""
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ManifestError(f"{where} must be a list")
    events: list[Event] = []
    for index, raw in enumerate(value):
        place = f"{where}[{index}]"
        if not isinstance(raw, dict):
            raise ManifestError(f"{place} must be an object")
        day = _require(raw, "day", int, place)
        if isinstance(day, bool) or day <= 0 or day > highest:
            raise ManifestError(f"{place}.day must be within 1..{highest}")
        kind = _require(raw, "kind", str, place)
        if kind not in MILESTONES:
            raise ManifestError(f"{place}.kind must be one of {list(MILESTONES)}")
        revision = raw.get("revision")
        reason = raw.get("reason", "")
        if kind == "rollback":
            if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
                raise ManifestError(f"{place}.revision must be a positive integer for rollback")
            if not isinstance(reason, str) or not reason.strip():
                raise ManifestError(f"{place}.reason must be a non-empty string for rollback")
        elif revision is not None:
            raise ManifestError(f"{place}.revision is only valid for rollback")
        events.append(Event(day, (), kind=kind, session="owner",
                            note=str(raw.get("note") or ""), revision=revision, reason=reason))
    if [event.day for event in events] != sorted(event.day for event in events):
        raise ManifestError(f"{where} must be ordered by day")
    return tuple(events)


def _parse_checkpoint(day: int, value: Any, scenario: Scenario, tokens: dict[str, str]) -> Checkpoint:
    """Parse one checkpoint against the scenario vocabulary / 按场景词表解析一个检查点。"""
    where = f"scenario {scenario.id} checkpoint {day}"
    if not isinstance(value, dict):
        raise ManifestError(f"{where} must be an object")
    missing = [key for key in _REQUIRED_CHECKPOINT if key not in value]
    if missing:
        raise ManifestError(f"{where} is missing {missing}")
    probe = _nonempty_text(value["probe"], f"{where}.probe")
    expect = value["expect_tokens"]
    forbid = value["forbid_tokens"]
    for label, items in (("expect_tokens", expect), ("forbid_tokens", forbid)):
        if not isinstance(items, list) or any(not isinstance(item, str) for item in items):
            raise ManifestError(f"{where}.{label} must be a list of strings")
        unknown = [item for item in items if item not in tokens.values()]
        if unknown:
            raise ManifestError(f"{where}.{label} uses undeclared tokens {unknown}")
    if set(expect) & set(forbid):
        raise ManifestError(f"{where} expects and forbids the same token")
    if not expect:
        raise ManifestError(f"{where}.expect_tokens must not be empty")
    actions = value["expect_actions"]
    if not isinstance(actions, list) or not actions:
        raise ManifestError(f"{where}.expect_actions must be a non-empty list")
    if any(action not in ACTIONS for action in actions):
        raise ManifestError(f"{where}.expect_actions must use {list(ACTIONS)}")
    raw_emotion = value["emotion"]
    if not isinstance(raw_emotion, dict) or not raw_emotion:
        raise ManifestError(f"{where}.emotion must declare at least one signal")
    emotion: dict[str, tuple[float, float]] = {}
    for signal, interval in raw_emotion.items():
        if signal not in scenario.signals:
            raise ManifestError(f"{where}.emotion uses undeclared signal {signal!r}")
        if not isinstance(interval, (list, tuple)) or len(interval) != 2:
            raise ManifestError(f"{where}.emotion.{signal} must be [low, high]")
        low, high = interval
        for bound in (low, high):
            if isinstance(bound, bool) or not isinstance(bound, (int, float)):
                raise ManifestError(f"{where}.emotion.{signal} bounds must be numeric")
        if not 0 <= float(low) < float(high) <= 100:
            raise ManifestError(f"{where}.emotion.{signal} must satisfy 0 <= low < high <= 100")
        emotion[signal] = (float(low), float(high))
    bands = value["relationship_bands"]
    if not isinstance(bands, list) or not bands or any(band not in BANDS for band in bands):
        raise ManifestError(f"{where}.relationship_bands must be a non-empty subset of {list(BANDS)}")
    note = value.get("note", "")
    if not isinstance(note, str):
        raise ManifestError(f"{where}.note must be a string")
    correction = value.get("correction", False)
    if not isinstance(correction, bool):
        raise ManifestError(f"{where}.correction must be a boolean")
    return Checkpoint(day, probe, tuple(expect), tuple(forbid), tuple(actions), emotion,
                      tuple(bands), note, correction)


def _parse_scenario(value: Any, horizons: tuple[int, ...]) -> Scenario:
    """Parse one scenario card / 解析一张场景卡。"""
    if not isinstance(value, dict):
        raise ManifestError("scenario must be an object")
    scenario_id = _nonempty_text(_require(value, "id", str, "scenario"), "scenario.id")
    where = f"scenario {scenario_id}"
    title = _nonempty_text(_require(value, "title", str, where), f"{where}.title")
    role = _require(value, "role", dict, where)
    missing = [key for key in _REQUIRED_ROLE if key not in role]
    if missing:
        raise ManifestError(f"{where}.role is missing {missing}")
    tokens = _parse_tokens(_require(value, "tokens", dict, where), f"{where}.tokens")
    cues, signals = _parse_cues(_require(value, "emotion", dict, where), f"{where}.emotion")
    actions = _parse_actions(_require(value, "actions", dict, where), f"{where}.actions")
    events = _parse_events(_require(value, "events", list, where), f"{where}.events")
    highest = max(horizons)
    late = [event.day for event in events if event.day > highest]
    if late:
        raise ManifestError(f"{where}.events exceed day {highest}: {late}")
    raw_checkpoints = _require(value, "checkpoints", dict, where)
    missing_days = [f"{day}" for day in horizons if f"{day}" not in raw_checkpoints]
    if missing_days:
        raise ManifestError(f"{where}.checkpoints is missing horizons {missing_days}")
    # A placeholder scenario is needed for checkpoint parsing (signal vocabulary).
    placeholder = Scenario(scenario_id, title, dict(role), tokens, cues, signals, actions, events, (), ())
    checkpoints = tuple(
        _parse_checkpoint(day, raw_checkpoints[f"{day}"], placeholder, tokens)
        for day in horizons
    )
    tags = value.get("tags", [])
    if not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags):
        raise ManifestError(f"{where}.tags must be a list of strings")
    milestones = _parse_milestones(value.get("milestones"), f"{where}.milestones", highest)
    return Scenario(scenario_id, title, dict(role), tokens, cues, signals, actions,
                    events, checkpoints, tuple(tags), milestones)


def parse_manifest(data: Any) -> Manifest:
    """Validate a decoded manifest and return frozen dataclasses / 校验已解码清单并返回冻结数据。"""
    if not isinstance(data, dict):
        raise ManifestError("manifest must be a JSON object")
    missing = [key for key in _REQUIRED_TOP if key not in data]
    if missing:
        raise ManifestError(f"manifest is missing {missing}")
    from . import MANIFEST_SCHEMA, HORIZONS

    schema = data["schema"]
    if schema != MANIFEST_SCHEMA:
        raise ManifestError(f"manifest.schema must be {MANIFEST_SCHEMA!r}")
    version = data["version"]
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise ManifestError("manifest.version must be a positive integer")
    seed = data["seed"]
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ManifestError("manifest.seed must be an integer")
    start = parse_start(data["start"])
    horizons = _parse_horizons(data["horizons"])
    if horizons != tuple(HORIZONS):  # pragma: no cover - defensive duplicate
        raise ManifestError("manifest.horizons is fixed")
    owner = _require(data, "owner", dict, "manifest")
    for key in _REQUIRED_OWNER:
        _nonempty_text(owner.get(key), f"manifest.owner.{key}")
    sessions = _require(data, "sessions", dict, "manifest")
    for key in _REQUIRED_SESSIONS:
        _nonempty_text(sessions.get(key), f"manifest.sessions.{key}")
    raw_scenarios = _require(data, "scenarios", list, "manifest")
    if not raw_scenarios:
        raise ManifestError("manifest.scenarios must not be empty")
    scenarios = tuple(_parse_scenario(item, horizons) for item in raw_scenarios)
    ids = [scenario.id for scenario in scenarios]
    if len(set(ids)) != len(ids):
        raise ManifestError("manifest scenario ids must be unique")
    canonical = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return Manifest(schema, version, seed, start, horizons, dict(owner), dict(sessions),
                    scenarios, digest)


def load_manifest(path: str | Path) -> Manifest:
    """Read and validate one manifest file / 读取并校验一个清单文件。"""
    location = Path(path)
    try:
        raw = location.read_text(encoding="utf-8")
    except OSError as exc:
        raise ManifestError(f"cannot read manifest {location}: {exc}") from exc
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise ManifestError(f"manifest {location} is not valid JSON: {exc}") from exc
    return parse_manifest(data)


def fingerprint(manifest: Manifest) -> dict[str, Any]:
    """Return the content digest a report pins its results to / 返回报告用于固定结果的内容指纹。"""
    return {
        "schema": manifest.schema,
        "version": manifest.version,
        "seed": manifest.seed,
        "digest": manifest.digest,
        "scenarios": [scenario.id for scenario in manifest.scenarios],
    }


__all__ = [
    "ManifestError",
    "Turn",
    "Event",
    "Checkpoint",
    "Scenario",
    "Manifest",
    "parse_manifest",
    "load_manifest",
    "fingerprint",
    "BANDS",
    "ACTIONS",
]
