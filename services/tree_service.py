"""Tree reads and writes over injected storage and optional cache."""

from __future__ import annotations

try:
    from ..app.ports import TreeArtifactStore, TreeCache
    from ..core.artifact import Artifact, revise
except ImportError:
    from app.ports import TreeArtifactStore, TreeCache
    from core.artifact import Artifact, revise

EDGE_PREFIX = "tree_child:"
LEVELS = ("impression", "scene", "detail")


class TreeService:
    """Coordinate tree operations; callers own storage and cache lifetimes.

    Writes commit the memory before updating cache, parent and edge separately.
    These steps are not a single transaction; failures propagate to the caller.
    """

    def __init__(self, artifacts: TreeArtifactStore,
                 cache: TreeCache | None = None) -> None:
        self.artifacts = artifacts
        self.cache = cache

    def _get(self, node_id: str) -> Artifact | None:
        """Prefer a cached value, falling back to storage without filling cache."""
        art = self.cache.get(node_id) if self.cache is not None else None
        if art is not None:
            return art
        return self.artifacts.get(node_id)

    def _persist(self, art: Artifact) -> None:
        """Prepare a revision, commit it, then update the optional cache."""
        existing = self.artifacts.get(art.header.id)
        if existing is None:
            expected = 0
            op = "create"
        else:
            expected = existing.header.revision
            op = "revise"
            if art.header.revision <= existing.header.revision:
                art = revise(
                    existing,
                    payload=art.payload,
                    state=art.header.state,
                    scope=art.header.scope,
                    strength=art.header.strength,
                    lineage=art.header.lineage,
                    said_by=art.header.said_by,
                    shareable=art.header.shareable,
                    subject_id=art.header.subject_id,
                )
        self.artifacts.commit(
            art,
            expected_revision=expected,
            op=op,
            reason="tree",
            source_ids=tuple(art.header.lineage.sources),
        )
        if self.cache is not None:
            self.cache.put(art)

    def children(self, node_id: str) -> list[Artifact]:
        """Read distinct existing children through the stored tree edges."""
        if not node_id:
            return []
        wanted = EDGE_PREFIX + node_id
        result: list[Artifact] = []
        seen: set[str] = set()
        for edge in self.artifacts.edges_of(node_id):
            if len(edge) < 3:
                continue
            other, kind = edge[0], edge[1]
            if kind != wanted or not other or other in seen:
                continue
            art = self._get(other)
            if art is not None:
                seen.add(other)
                result.append(art)
        return result

    def impressions(self) -> list[Artifact]:
        """Read active memory impressions, using storage when the cache level is empty."""
        arts = list(self.cache.by_level("impression")) if self.cache else []
        if not arts:
            arts = list(self.artifacts.list("memory", "active"))
        return [
            art for art in arts
            if art.header.family == "memory"
            and art.header.state == "active"
            and art.payload.get("level") == "impression"
        ]

    def add_under(self, child: Artifact, parent_id: str | None) -> Artifact:
        """Save the child and update its parent/edge, returning the original input."""
        if parent_id is not None and parent_id == child.header.id:
            raise ValueError("node cannot be its own parent")
        self._persist(child)
        self.artifacts.set_parent(child.header.id, parent_id)
        if parent_id is not None:
            self.artifacts.add_edge(
                parent_id, child.header.id, EDGE_PREFIX + parent_id, 1.0
            )
        return child
