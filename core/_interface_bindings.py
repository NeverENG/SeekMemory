"""Import binding only; no domain behavior / 仅负责导入绑定，不包含领域逻辑。"""

from importlib import import_module

_GRAPH_NAMES = {"ArtifactEdge", "Graph", "KINDS"}
_TREE_NAMES = {"Tree", "EDGE_PREFIX", "LEVELS"}


def __getattr__(name: str) -> object:
    """Load graph/tree exports after protocol declaration / 在接口声明后按需载入图和树的导出。"""
    if name in _GRAPH_NAMES:
        return getattr(import_module(".graph", __package__), name)
    if name in _TREE_NAMES:
        return getattr(import_module(".tree", __package__), name)
    raise AttributeError(f"module {__package__}.interfaces has no attribute {name!r}")


def __dir__() -> list[str]:
    """Include deferred exports in inspection / 检查接口时也列出延迟导出的名称。"""
    module = import_module(".interfaces", __package__)
    return sorted(set(vars(module)) | set(module.__all__))
