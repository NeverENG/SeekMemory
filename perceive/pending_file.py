"""Own legacy pending-file I/O and its error status; no queue or model calls.

管理旧待处理文件读写及错误状态，不调用队列或模型。
"""
from __future__ import annotations

import json
import os
from pathlib import Path


class PendingFile:
    """Own one legacy path and its read/write diagnostics / 管理一个旧文件路径及其读写诊断。"""

    def __init__(self, path: str = "") -> None:
        self.path = str(path or "")
        self.load_error = ""
        self.save_error = ""

    def read(self) -> dict:
        if not self.path or not os.path.exists(self.path):
            return {}
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception as exc:
            self.load_error = type(exc).__name__
            self.quarantine()
            return {}
        if not isinstance(data, dict):
            self.load_error = "InvalidPendingFile"
            self.quarantine()
            return {}
        self.load_error = ""
        return data


    def quarantine(self) -> None:
        """Preserve a corrupt pending file instead of overwriting it on save."""
        if not self.path or not os.path.exists(self.path):
            return
        target = Path(self.path + ".corrupt")
        suffix = 1
        while target.exists():
            target = Path(f"{self.path}.corrupt.{suffix}")
            suffix += 1
        try:
            Path(self.path).replace(target)
        except OSError:
            pass


    def save(self, data: dict) -> bool:
        """Save the existing JSON layout and expose failures / 保存既有 JSON 布局并暴露失败。"""
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as stream:
                json.dump(data, stream, ensure_ascii=False)
            self.save_error = ""
            return True
        except Exception as exc:
            self.save_error = type(exc).__name__
            return False
