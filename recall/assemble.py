"""Render disclosed memories with existing narrative ordering and character budgets; no writes.

按既有叙述顺序及字数预算转换已披露记忆，不执行写入。
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

try:  # Plugin namespace / 插件命名空间。
    from ..core.artifact import Artifact, content_of
    from .designated import deliverable, triggers_of
except ImportError:  # Top-level package / 顶层包。
    from core.artifact import Artifact, content_of
    from recall.designated import deliverable, triggers_of

MEDIA = {
    "video": ("个", "视频"),
    "music": ("首", "歌"),
    "audio": ("段", "音频"),
    "image": ("张", "照片"),
    "photo": ("张", "照片"),
    "article": ("篇", "文章"),
    "link": ("篇", "文章"),
}
CORE_LAYERS = ("persona", "impression")
SHADOW_SENTENCE = "有件事你答应过别人不说"


def _clean(value: Any, limit: int = 180) -> str:
    """Normalize narrative whitespace and punctuation / 规范叙述空白及标点。"""
    text = " ".join(str(value or "").split())
    text = re.sub(r"(?<=[^，。！？；：、\s不非])但", "，但", text)
    text = text.strip("。！？!?；;，,、 ")
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text + "。" if text else ""


def _clip(value: Any, limit: int = 60) -> str:
    """Clip a quote/title using the existing length rule / 按既有长度规则裁剪引语或标题。"""
    text = _clean(value, limit)
    return text[:-1] if text.endswith("。") else text


def _raw(art: Artifact) -> str:
    """Read family text with the existing content fallback / 按既有内容回退读取类型正文。"""
    for key in ("text", "shadow_text", "summary", "title"):
        value = art.payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    try:
        return content_of(art)
    except Exception:
        return ""


def _voice(text: str, about: str) -> str:
    """Convert the existing first-person memory wording to second person / 将既有记忆第一人称转换为第二人称。"""
    if about == "relation":
        text = text.replace("我们", "你们")
    return text.replace("我的", "你的").replace("我", "你")


def _when(created: str) -> str:
    """Format the existing relative date wording / 转换既有相对日期措辞。"""
    try:
        day = date.fromisoformat(str(created)[:10])
    except (TypeError, ValueError):
        return ""
    delta = (date.today() - day).days
    for limit, word in ((0, "今天"), (1, "昨天"), (10, "前几天"), (30, "前阵子")):
        if delta <= limit:
            return word
    return f"{delta // 30}个月前" if delta < 365 else "去年"


def _media_sentence(art: Artifact) -> str:
    """Render the existing media memory description / 转换既有媒体记忆说明。"""
    payload = art.payload
    kind = str(payload.get("type") or "video").lower()
    measure, noun = MEDIA.get(kind, ("个", "视频"))
    topic = _clip(payload.get("title") or payload.get("summary"), 60)
    for tail in ("是怎么来的", "的由来", "是怎么火起来的", "是什么", "的介绍"):
        if topic.endswith(tail) and len(topic) > len(tail):
            topic = topic[: -len(tail)]
            break
    verb = "叫" if kind == "music" else "讲" if kind in ("video", "article", "link") else "关于"
    thing = f"一{measure}{verb}{topic}的{noun}" if topic else f"一{measure}{noun}"
    who = str(payload.get("shared_by") or art.header.said_by or "other")
    if who in ("self", "bot", "you"):
        return f"你还记得给他看过{thing}。"
    return f"他给你看过{thing}。"


def _example_sentence(art: Artifact) -> str:
    """Render a prior user quote and assistant response / 转换先前用户原话及助手回应。"""
    user, reply = _clip(art.payload.get("user")), _clip(art.payload.get("assistant"))
    if user and reply:
        return f"你记得有一次他说「{user}」，你回「{reply}」。"
    if user:
        return f"你记得有一次他说「{user}」。"
    return f"你记得有一次你回「{reply}」。" if reply else ""


def _guarded_sentence(art: Artifact) -> str:
    """Render only a guarded hint without disclosing protected content / 仅转换保护提示，不披露受保护内容。"""
    if art.header.family == "designated":
        trigger = _clip("、".join(triggers_of(art)) or "那个东西", 40)
        return f"他让你记着一件事，等提到「{trigger}」时再告诉他。"
    shadow = _clean(art.payload.get("shadow_text") or SHADOW_SENTENCE)
    return f"你记得，{shadow}" if shadow else ""


def _shadow_sentence(art: Artifact) -> str:
    """Render shadow wording without the original body in any session / 在所有会话仅转换影子措辞，不使用原正文。"""
    shadow = _clean(art.payload.get("shadow_text") or SHADOW_SENTENCE)
    return f"你记得，{shadow}" if shadow else ""


def _designated_sentence(art: Artifact) -> str:
    """Render a designated body after its existing access gates passed / 在既有访问条件通过后转换指定正文。"""
    body = _clean(art.payload.get("text"), 600)
    if not body:
        return ""
    return f"你记得他让你记的事，现在他问起来了，你可以告诉他：{body}"


def _memory_sentence(art: Artifact) -> str:
    """Render memory wording for its existing abstraction level / 按既有抽象层级转换记忆措辞。"""
    text = _clean(_voice(_raw(art), str(art.payload.get("about") or "")))
    if not text:
        return ""
    level = str(art.payload.get("level") or "")
    if level == "impression":
        return f"你印象里{text}"
    if level == "detail":
        return f"你还记得{text}"
    when = _when(art.header.time.created) if level == "scene" else ""
    return f"{when}{text}" if when else f"你记得{text}"


def _persona_sentence(art: Artifact) -> str:
    """Render the whole persona without per-memory clipping; the total budget still applies / 转换完整人格，不按单条记忆裁剪，总预算仍适用。"""
    text = " ".join(str(_voice(_raw(art), "self") or "").split())
    text = text.strip("。！？!?；;，,、 ")
    if len(text) > 4000:
        text = text[:3999].rstrip() + "…"
    return text + "。" if text else ""


def _sentence(art: Artifact, text: str | None = None,
              is_private: bool | None = None) -> tuple[str, str]:
    """Choose shadow/family wording; missing designated context only permits a hint / 选择影子或类型措辞，缺少指定记忆上下文时仅允许提示。"""
    if str(art.header.scope or "") == "shadow":
        return "shadow", _shadow_sentence(art)
    family = art.header.family
    if family == "media":
        return "media", _media_sentence(art)
    if family == "designated":
        if text is None or is_private is None:
            return family, _guarded_sentence(art)
        if not deliverable(art, text, is_private):
            return family, ""
        return family, _designated_sentence(art)
    if family == "secret":
        return family, _guarded_sentence(art)
    if family == "example":
        return "example", _example_sentence(art)
    if family == "persona":
        return "persona", _persona_sentence(art)
    level = str(art.payload.get("level") or "scene")
    layer = level if level in ("fact", "impression", "scene", "detail") else "scene"
    return layer, _memory_sentence(art)


def _render(items: list[tuple[str, str]]) -> str:
    """Join already prepared sentences in order / 按顺序连接已准备句子。"""
    return "".join(sentence for _, sentence in items)


def _drop(items: list[tuple[str, str]], layers: tuple[str, ...]) -> int | None:
    """Remove the last eligible layer item and return its position / 移除末尾符合层级条件的项并返回位置。"""
    index = next((i for i in range(len(items) - 1, -1, -1) if items[i][0] in layers), None)
    if index is None:
        return None
    del items[index]
    return index


def _dedupe_key(art: Artifact) -> str:
    """Use shadow text or existing content as the assembly duplicate key / 使用影子文本或既有内容作为组装去重键。"""
    if str(art.header.scope or "") == "shadow":
        shadow = str(art.payload.get("shadow_text") or "").strip()
        return "shadow:" + (shadow or art.header.id)
    return content_of(art)


def _dedupe(arts: list[Artifact]) -> list[Artifact]:
    """Keep the existing nonempty noncontained narrative entries / 按既有规则保留非空且互不包含的叙述条目。"""
    kept: list[Artifact] = []
    seen: list[str] = []
    for a in arts:
        try:
            t = _dedupe_key(a).strip()
        except Exception:
            continue
        if not t:
            continue
        if any(t == o or t in o or o in t for o in seen):
            continue
        kept.append(a)
        seen.append(t)
    return kept


def build_with_meta(
    arts: list[Artifact], budget: int = 2000,
    *, text: str | None = None, is_private: bool | None = None,
    notes: dict[str, str] | None = None,
    overrides: dict[str, str] | None = None,
) -> tuple[str, tuple[str, ...], tuple[str, ...]]:
    """Assemble within the character budget and return final/dropped IDs / 在字数预算内组装，返回最终及丢弃编号。"""
    input_ids = [art.header.id for art in arts]
    arts = _dedupe(arts)
    if not arts or budget <= 0:
        return "", (), ()
    entries: list[tuple[str, str]] = []
    entry_ids: list[str] = []
    dropped: list[str] = []
    for art in arts:
        if overrides and art.header.id in overrides:
            safe = str(overrides[art.header.id] or "").strip()
            if not safe:
                dropped.append(art.header.id)
                continue
            level = str(art.payload.get("level") or art.header.family)
            layer = level if level in ("fact", "impression", "scene", "detail") else "scene"
            entries.append((layer, safe))
            entry_ids.append(art.header.id)
            continue
        layer, sentence = _sentence(art, text, is_private)
        if not sentence:
            dropped.append(art.header.id)
            continue
        if notes:
            extra = notes.get(art.header.id)
            if extra:
                sentence = sentence.rstrip("\u3002") + extra + "\u3002"
        entries.append((layer, sentence))
        entry_ids.append(art.header.id)
    if not entries:
        return "", (), tuple(dict.fromkeys(dropped))
    order = {"persona": 0, "impression": 1, "scene": 2, "detail": 3, "fact": 4,
             "example": 5}
    ranked = sorted(enumerate(entries), key=lambda ie: (order.get(ie[1][0], 6), ie[0]))
    header = [i for i, (layer, _) in enumerate(entries) if layer == "persona"]
    header += [i for i, (layer, _) in enumerate(entries) if layer == "impression"][:2]
    sequence = [i for i, _ in ranked if i not in header]
    indices = header + sequence
    items = [entries[i] for i in indices]
    item_ids = [entry_ids[i] for i in indices]
    for layer in ("example", "fact", "detail", "scene"):
        while len(_render(items)) > budget:
            index = _drop(items, (layer,))
            if index is None:
                break
            dropped.append(item_ids.pop(index))
    rest = ("media", "secret", "designated", "shadow", "memory", "impression")
    while len(_render(items)) > budget:
        index = _drop(items, rest)
        if index is None:
            break
        dropped.append(item_ids.pop(index))
    rendered = _render(items)
    final_ids = tuple(item_ids)
    if len(rendered) > budget:
        cut = rendered[: max(0, budget - 2)]
        pos = max(cut.rfind("\u3002"), cut.rfind("\uff1b"), cut.rfind("\uff0c"))
        if pos > budget * 0.6:
            cut = cut[: pos + 1]
        rendered = cut.rstrip("\uff0c\u3002\uff1b\u3001 ") + "\u2026\u2026"
        final_ids = tuple(
            entity for entity, (_, sentence) in zip(item_ids, items)
            if sentence.rstrip("\u3002") and sentence.rstrip("\u3002") in rendered
        )
    if rendered and not rendered.startswith("\u4f60"):
        rendered = "\u4f60\u8bb0\u5f97\uff0c" + rendered
    if len(rendered) > budget:
        rendered = rendered[: max(0, budget - 2)].rstrip("\uff0c\u3002\uff1b\u3001 ") + "\u2026\u2026"
        final_ids = tuple(
            entity for entity, (_, sentence) in zip(item_ids, items)
            if sentence.rstrip("\u3002") and sentence.rstrip("\u3002") in rendered
        )
    dropped_ids = tuple(dict.fromkeys(dropped + [entity for entity in input_ids
                                                 if entity not in final_ids]))
    if len(rendered) > budget:
        rendered = "\u2026" * max(0, budget)
        final_ids = ()
    return rendered, final_ids, dropped_ids


def build(arts: list[Artifact], budget: int = 2000,
          *, text: str | None = None, is_private: bool | None = None,
          notes: dict[str, str] | None = None,
          overrides: dict[str, str] | None = None) -> str:
    """Assemble narrative text without persistence / 组装叙述文本，不持久化。"""
    return build_with_meta(
        arts, budget, text=text, is_private=is_private,
        notes=notes, overrides=overrides,
    )[0]
