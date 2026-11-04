"""Shared byte limits for authenticated management request bodies.

管理接口鉴权后请求体大小的共享限制。
"""
from __future__ import annotations


def request_body_limit(action: str) -> int:
    """Allow escaped persona edits while bounding every HTTP transport.

    为转义后的人格编辑预留容量，同时限制各 HTTP 传输。
    """
    if action == "persona":
        return 3 * 1024 * 1024
    if action == "update":
        return 1024 * 1024
    return 65536
