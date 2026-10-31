"""Keep prepared extraction progress in this process; never own resources.

在当前进程保留已准备的抽取进度，不拥有资源；不提供崩溃或跨进程交付保证。
"""
from __future__ import annotations

from dataclasses import dataclass, field

try:
    from ..app.contracts import DialogueTurn
    from ..perceive.absorb import ExtractionPlan
except ImportError:
    from app.contracts import DialogueTurn
    from perceive.absorb import ExtractionPlan


@dataclass(frozen=True)
class ExtractionTask:
    """Hold one pull-style extraction task for a host-owned model call.

    保存一个供宿主自行调用模型的拉取式抽取任务；不含模型调用或持久化。
    """

    task_id: str
    source_ids: tuple[str, ...]
    session_id: str = ""
    topic_id: str = ""
    system_prompt: str = ""
    prompt: str = ""
    require_evidence: bool = False

    @property
    def turns(self) -> int:
        """Read the bounded number of dialogue rows / 读取受限的对话行数。"""
        return len(self.source_ids)


@dataclass
class PreparedExtraction:
    """Own one plan's durable and follow-up stages, separate from model retry.

    管理一个计划的持久提交及后续阶段，与模型重试分开；各阶段只有一个进度所有者。
    """

    plan: ExtractionPlan
    rows: tuple[DialogueTurn, ...]
    confirm_queue: bool = False
    committed: set[str] = field(default_factory=set)
    cached: set[str] = field(default_factory=set)
    enriched: set[str] = field(default_factory=set)
