"""Explicit shared adapter exports; no host SDK or resource creation here.

明确共享适配器导出，本入口不依赖宿主 SDK 或创建资源。
"""
from .persona_packs import FilePersonaPacks
from .relationship_policy import (
    RelationshipReader, RelationshipInteractionPolicy, settings_from_config, interaction_prompt,
)

__all__ = [
    "FilePersonaPacks", "RelationshipReader", "RelationshipInteractionPolicy",
    "settings_from_config", "interaction_prompt",
]
