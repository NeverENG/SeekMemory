"""Host-neutral inbound projection for runtime inputs / 宿主无关的运行时入站投影。"""

from .contracts import HostRequest
from .gateway import HostGateway

__all__ = ["HostGateway", "HostRequest"]
