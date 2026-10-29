"""Provide a pure memory fixture without importing any test case.

提供纯记忆样本，不导入任何测试类。
"""

from core.artifact import make


def _memory(subject="u1", scope="private", text="I have a job interview"):
    """Construct an unsaved fact fixture / 构造未保存的事实样本。"""
    return make("memory", {"text": text, "level": "fact", "tags": "job interview"},
                subject_id=subject, scope=scope)
