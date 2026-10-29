"""Own legacy pending-file I/O and its error status; no queue or model calls.

管理旧待处理文件读写及错误状态，不调用队列或模型。
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


class PendingFile:
    """Own one legacy path and its read/write diagnostics / 管理一个旧文件路径及其读写诊断。"""

    def __init__(self, path: str = "") -> None:
        self.path = str(path or "")
        self.load_error = ""
        self.save_error = ""

    def read(self) -> dict:
        """Read a legacy object; quarantine malformed input and expose its safe error type.

        读取旧对象，将格式损坏输入隔离并提供安全错误类型。
        """
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
        """Preserve corrupt input at a unique backup path; ordinary rename errors remain isolated.

        将损坏输入保留到唯一备份路径，普通重命名错误保持隔离。
        """
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
        """Prepare a complete file, then replace it; failed writes preserve old input.

        准备完整文件后再替换，写入失败时保留旧输入；返回值明确表示保存是否完成。
        """
        temporary = None
        try:
            content = json.dumps(data, ensure_ascii=False)
            target = Path(self.path)
            target.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary = tempfile.mkstemp(dir=target.parent, prefix=".pending-")
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(content)
            os.replace(temporary, target)
            self.save_error = ""
            return True
        except Exception as exc:
            self.save_error = type(exc).__name__
            return False
        finally:
            if temporary is not None:
                try:
                    Path(temporary).unlink(missing_ok=True)
                except OSError:
                    pass
