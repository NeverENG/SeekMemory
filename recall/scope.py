"""Keep explicit designated/secret access rules while leaving ordinary memory scope to disclosure.

保持明确的指定及秘密记忆访问规则，普通记忆范围交由披露判断。
"""

from __future__ import annotations

from typing import Callable, Iterable

try:  # Plugin namespace / 插件命名空间。
    from ..core.artifact import Artifact
except ImportError:  # Top-level package / 顶层包。
    from core.artifact import Artifact

OWNER_KEYS = ("owner_umo", "umo")
Lookup = Callable[[str], str]


def owner_of(art: Artifact, lookup: Lookup | None = None) -> str:
    """Resolve provenance from payload or Source lookup without fabricating ownership / 从内容或原始消息查询确定来源，不补造归属。"""
    payload = art.payload if isinstance(art.payload, dict) else {}
    for key in OWNER_KEYS:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    for source in art.header.lineage.sources or ():
        if lookup is None:
            break
        try:
            umo = lookup(str(source))
        except Exception:  # noqa: BLE001 - Bad provenance is isolated / 隔离损坏来源。
            continue
        if umo:
            return str(umo)
    said_by = str(art.header.said_by or "")
    return said_by if ":" in said_by else ""


def visible(pool: Iterable[Artifact], umo: str, owner_umo: str = "",
            lookup: Lookup | None = None) -> list[Artifact]:
    """Keep the global ordinary pool while enforcing explicit secret/designated access / 保留全局普通记忆池，同时执行明确的秘密及指定记忆访问条件。"""
    viewer = str(umo or "")
    fallback = str(owner_umo or "")
    kept: list[Artifact] = []
    for art in pool:
        family = str(art.header.family or "")
        if family == "secret":
            continue
        if family == "designated":
            own = owner_of(art, lookup)
            if own:
                if own != viewer:
                    continue
            elif not fallback or viewer != fallback:
                continue
        kept.append(art)
    return kept
