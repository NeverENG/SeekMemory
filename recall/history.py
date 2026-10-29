"""Read cached impression version history and format optional trajectory notes.

读取缓存中印象的版本历史并转换可选变化说明，不执行写入。
"""


from __future__ import annotations

try:  # Plugin namespace / 插件命名空间。
    from ..app.ports import ArtifactCache
    from ..core.artifact import Artifact
except ImportError:  # Top-level package / 顶层包。
    from app.ports import ArtifactCache
    from core.artifact import Artifact

MAX_SIDE = 22   # Prior wording limit / 旧措辞长度上限。


def _texts(cache: ArtifactCache, art: Artifact) -> list[str]:
    """Read deduplicated cached version text in old-to-new order / 按旧到新读取去重的缓存版本正文。"""
    artifacts = getattr(cache, "artifacts", None)
    if artifacts is None:
        return []
    try:
        rows = artifacts.history(art.header.id)
    except Exception:  # noqa: BLE001 - Missing history stays empty / 历史缺失时按空处理。
        return []
    out: list[str] = []
    for row in rows:
        payload = row.get("payload") or {}
        text = str(payload.get("text") or "").strip()
        if text and (not out or out[-1] != text):
            out.append(text)
    return out


def _trim(text: str) -> str:
    """Trim existing narrative lead-ins and trailing punctuation / 裁剪既有叙述开头及末尾标点。"""
    body = text.strip().rstrip("。！？!?；;")
    for prefix in ("他", "她", "他们", "她们"):
        if body.startswith(prefix):
            body = body[len(prefix):]
            break
    return body[:MAX_SIDE]


def _when(iso: str) -> str:
    """Format the existing relative date wording / 转换既有相对日期措辞。"""
    try:
        import datetime

        day = datetime.date.fromisoformat(str(iso)[:10])
        days = max(0, (datetime.date.today() - day).days)
    except (TypeError, ValueError):
        return "以前"
    if days >= 60:
        return f"{days // 30} 个月前"
    if days >= 14:
        return f"{days // 7} 周前"
    if days >= 2:
        return f"{days} 天前"
    return "以前"


def _first_at(cache: ArtifactCache, art: Artifact) -> str:
    """Read the earliest cached version time / 读取最早缓存版本时间。"""
    artifacts = getattr(cache, "artifacts", None)
    if artifacts is None:
        return ""
    try:
        rows = artifacts.history(art.header.id)
    except Exception:  # noqa: BLE001
        return ""
    return str(rows[0].get("at") or "") if rows else ""


def trajectory(cache: ArtifactCache, art: Artifact) -> str:
    """Format optional bounded impression history without writes / 转换可选且有长度上限的印象历史，不执行写入。"""
    texts = _texts(cache, art)
    if len(texts) < 2:
        return ""
    old = _trim(texts[0])
    if not old:
        return ""
    return f"（{_when(_first_at(cache, art))}觉得{old}）"
