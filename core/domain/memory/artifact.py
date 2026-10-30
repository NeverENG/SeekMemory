"""Define Artifact data and construction, revision, validation and text access; no storage I/O.

定义 Artifact 数据及构造、修订、校验和文本读取，不进行存储读写。
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any

FAMILIES = (
    "memory", "example", "persona", "media", "secret", "designated",
    "relationship",
)


_TEXT_FIELDS = {
    "memory": "text",
    "persona": "text",
    "secret": "shadow_text",
    "designated": "text",
    "relationship": "summary",
}

_SEQ = 0


@dataclass(frozen=True)
class Strength:
    """Immutable strength values, including explicit hits and emotion inputs.

    不可变强度数据，包括显式命中和情绪输入。
    """
    weight: float = 1.0
    confidence: float = 1.0
    arousal: float = 0.3
    valence: float = 0.0
    funny: float = 0.0
    hits: int = 0


@dataclass(frozen=True)
class TimeSpan:
    """Stored creation, update and validity dates; does not parse or convert time.

    保存创建、更新及有效日期，不解析或转换时间。
    """
    created: str = ""
    updated: str = ""
    valid_from: str | None = None
    valid_to: str | None = None
    expires: str | None = None


@dataclass(frozen=True)
class Lineage:
    """Reference immutable Sources and upstream Artifacts as separate evidence links.

    分别引用不可变 Source 和上游 Artifact 作为证据链接。
    """
    sources: tuple[str, ...] = ()
    derived_from: tuple[str, ...] = ()


@dataclass(frozen=True)
class Header:
    """Immutable identity, revision, visibility and provenance for one Artifact.

    一个 Artifact 的不可变编号、版本、可见性及来源信息。
    """
    id: str
    family: str
    revision: int = 1
    state: str = "active"
    scope: str = "private"
    lineage: Lineage = field(default_factory=Lineage)
    strength: Strength = field(default_factory=Strength)
    time: TimeSpan = field(default_factory=TimeSpan)
    said_by: str = "owner"
    shareable: str = "private_only"
    subject_id: str = ""


@dataclass(frozen=True)
class Artifact:
    """Pair an immutable header with a copied mutable payload.

    将不可变头部与复制后的可变内容配对。
    """
    header: Header
    payload: dict[str, Any]


def _now() -> str:
    return datetime.now().isoformat(timespec="microseconds")


def _new_id() -> str:
    global _SEQ
    _SEQ += 1
    return "n_" + datetime.now().strftime("%Y%m%d%H%M%S%f") + f"{_SEQ:03d}"


def _coerce(kw: dict[str, Any]) -> dict[str, Any]:
    """Convert nested header dictionaries to their declared data types.

    将嵌套头部字典转换为声明的数据类型。
    """
    for key, cls in (("lineage", Lineage), ("strength", Strength), ("time", TimeSpan)):
        if isinstance(kw.get(key), dict):
            kw[key] = cls(**kw[key])
    return kw


def _stamp(time: TimeSpan) -> TimeSpan:
    now = _now()
    return replace(time, created=time.created or now, updated=time.updated or now)


def make(family: str, payload: dict[str, Any], **header_kw: Any) -> Artifact:
    """Construct a valid-family Artifact without validating its payload; fill missing identity/time from the clock.

    构造类别合法的 Artifact，不校验内容；缺少的编号及时间由时钟补齐。
    """
    if family not in FAMILIES:
        raise ValueError(f"未知 family：{family!r}，可选：{', '.join(FAMILIES)}")
    kw = _coerce(dict(header_kw))
    kw.pop("family", None)
    kw.setdefault("id", _new_id())
    kw["time"] = _stamp(kw.get("time") or TimeSpan())
    return Artifact(header=Header(family=family, **kw), payload=dict(payload))


def revise(art: Artifact, payload: dict[str, Any] | None = None, **header_kw: Any) -> Artifact:
    """Keep identity/family, increment revision and update time; return a copy without persistence.

    保持编号和类别、递增版本并更新时间；返回副本，不执行保存。
    """
    kw = _coerce(dict(header_kw))
    kw.pop("family", None)
    kw.pop("id", None)
    time = kw.pop("time", art.header.time)
    kw.setdefault("revision", art.header.revision + 1)
    kw["time"] = replace(time, updated=_now())
    new_payload = dict(art.payload if payload is None else payload)
    return Artifact(header=replace(art.header, **kw), payload=new_payload)


def validate(art: Artifact) -> None:
    """Validate required family payload fields; invalid data raises ValueError.

    按类别校验必需内容字段，无效数据抛出 ValueError。
    """
    family = art.header.family
    if family not in FAMILIES:
        raise ValueError(f"未知 family：{family!r}，可选：{', '.join(FAMILIES)}")
    if not isinstance(art.payload, dict):
        raise ValueError(f"{family} 的 payload 必须是 dict")
    # Resolve validators at use time so a family can import its own domain vocabulary.
    from ...families import designated, example, media, memory, persona, relationship, secret

    validators = {
        "memory": memory.validate, "example": example.validate,
        "persona": persona.validate, "media": media.validate,
        "secret": secret.validate, "designated": designated.validate,
        "relationship": relationship.validate,
    }
    validators[family](art.payload)


def _field(payload: dict[str, Any], key: str, family: str) -> str:
    if key not in payload:
        raise ValueError(f"{family} payload 缺少字段：{key}")
    value = payload[key]
    return "" if value is None else str(value)


def content_of(art: Artifact) -> str:
    """Read display text without authorizing disclosure or writing state.

    读取显示文本，不授予披露权限或写入状态。
    """
    family, payload = art.header.family, art.payload
    if family == "example":
        user = _field(payload, "user", family)
        assistant = _field(payload, "assistant", family)
        return f"{user} → {assistant}"
    if family == "media":
        return str(payload.get("summary") or payload.get("title") or "")
    key = _TEXT_FIELDS.get(family)
    if key is None:
        raise ValueError(f"未知 family：{family!r}")
    return _field(payload, key, family)
