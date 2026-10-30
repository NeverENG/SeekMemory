"""Apply existing disclosure before rendering; read only supplied evidence origins.

在转换前应用既有披露规则，仅查询给定证据的来源，不写入记忆。
"""
from __future__ import annotations

try:
    from ..core.domain.memory.disclosure import DisclosureLevel, decide, safe_text
    from ..core.domain.character.bot_behavior import trusted_self_persona
except ImportError:
    from core.domain.memory.disclosure import DisclosureLevel, decide, safe_text
    from core.domain.character.bot_behavior import trusted_self_persona

def disclose(arts: list, relevance: float, *, scene, sources, umo: str, owner_umo: str,
             overrides: dict[str, str], disclosure_info: dict[str, str]) -> list:
    """Apply existing disclosure and collect safe text overrides; failures withhold an item / 应用既有披露并收集安全措辞替换，失败时不提供该项。"""
    safe_arts = []
    for art in arts:
        try:
            if art.header.family == "persona":
                safe = trusted_self_persona(art)
                disclosure_info[art.header.id] = "full" if safe else "silence"
                if safe:
                    safe_arts.append(art)
                continue
            source_ids = list(art.header.lineage.sources)
            origins = (
                tuple(sources.source_umos(source_ids).values())
            )
            if art.header.family == "designated":
                owner_ref = str(
                    art.payload.get("owner_umo")
                    or art.payload.get("owner")
                    or ""
                )
                if owner_ref in (umo, owner_umo) or umo in origins:
                    disclosure_info[art.header.id] = "full"
                    safe_arts.append(art)
                else:
                    disclosure_info[art.header.id] = "silence"
                continue
            decision = decide(art, scene, relevance, origins)
            disclosure_info[art.header.id] = decision.level.value
            if decision.level == DisclosureLevel.SILENCE:
                continue
            if decision.level != DisclosureLevel.FULL:
                safe = safe_text(art, decision.level)
                if not safe:
                    continue
                overrides[art.header.id] = safe
            safe_arts.append(art)
        except Exception:
            continue
    return safe_arts
