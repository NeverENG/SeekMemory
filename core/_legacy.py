"""Historical core module aliases / 旧 core 模块别名，不重复实现。"""

from importlib import import_module
from sys import modules

# Register old import paths from their owning modules. The physical layout
# remains core/domain/* and core/port/* / 旧导入与真实模块共享身份，不保留根目录转发文件。
_owners = {
    "memory": ("artifact", "source", "versioning", "retrieval", "strength", "disclosure", "graph"),
    "character": ("persona", "persona_artwork", "persona_pack", "bot_behavior"),
    "social": ("relationship", "relationship_rules", "interaction_policy"),
    "operations": ("capacity", "trace"),
}
for _group, _names in _owners.items():
    for _name in _names:
        _owner = import_module(f".domain.{_group}.{_name}", __package__)
        modules[f"{__package__}.{_name}"] = _owner
        modules[f"{__package__}.domain.{_name}"] = _owner
        setattr(modules[__package__], _name, _owner)
        setattr(modules[f"{__package__}.domain"], _name, _owner)
_owner = import_module(".port.graph", __package__)
modules[f"{__package__}.ports"] = _owner
setattr(modules[__package__], "ports", _owner)
