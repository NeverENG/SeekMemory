"""Apply Artifact lifecycle expiry without touching immutable Source rows."""

from __future__ import annotations

import datetime

try:
    from ..core.artifact import Artifact, revise
    from ..store.cache import Cache
    from ..store.db import DB
except ImportError:
    from core.artifact import Artifact, revise
    from store.cache import Cache
    from store.db import DB


def _date(value: str | None) -> datetime.date | None:
    if not isinstance(value, str) or len(value) < 10:
        return None
    try:
        return datetime.date.fromisoformat(value[:10])
    except ValueError:
        return None


def _expired(art: Artifact, today: datetime.date) -> bool:
    deadline = _date(art.header.time.expires) or _date(art.header.time.valid_to)
    return deadline is not None and deadline < today


def forget_expired(db: DB, cache: Cache, today: str = "") -> int:
    """Move expired active Artifacts to forgotten and retain their audit history."""
    try:
        base = datetime.date.fromisoformat(today[:10]) if today else datetime.date.today()
    except ValueError:
        base = datetime.date.today()
    forgotten = 0
    for art in list(cache.active()):
        if not _expired(art, base):
            continue
        updated = revise(art, state="forgotten")
        db.commit(
            updated,
            expected_revision=art.header.revision,
            op="forget",
            reason="lifecycle expiration",
            source_ids=tuple(art.header.lineage.sources),
        )
        cache.remove(art.header.id)
        forgotten += 1
    return forgotten
