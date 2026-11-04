"""Single inbound projection; no authentication or runtime policy / 唯一入站投影，不处理认证或运行时策略。"""

from __future__ import annotations

from dataclasses import asdict

from .contracts import HostRequest

try:
    from ...app.runtime.contracts import RuntimeInput
except ImportError:  # Top-level package / 顶层包。
    from app.runtime.contracts import RuntimeInput


class HostGateway:
    """Project trusted host facts without changing their meaning / 投影可信宿主事实，不改变其含义。"""

    @staticmethod
    def project(request: HostRequest) -> RuntimeInput:
        """Construct the runtime decision view / 构建运行时决策视图。"""
        return RuntimeInput(**asdict(request))
