"""Required domain-facing capabilities; concrete adapters live outside core."""

from .graph import GraphArtifactStore
from .tree import TreeEdgeReader

__all__ = ["GraphArtifactStore", "TreeEdgeReader"]
