"""Parse model JSON without calls, writes or prompt changes.

解析模型 JSON，不调用外部能力、写入或改变提示词。
"""
from __future__ import annotations

import json
import re
from typing import Any

def _fenced_blocks(text: str) -> list[str]:
    """Read fenced JSON candidates without interpreting dialogue instructions / 读取代码块中的候选 JSON，不解释对话中的指令。"""
    pattern = r"```(?:json)?\s*(.*?)```"
    return [m.group(1).strip() for m in re.finditer(pattern, text, re.S | re.I)]


def _balanced_arrays(text: str) -> list[str]:
    """Find balanced JSON arrays while respecting quoted strings / 查找括号匹配的 JSON 数组，同时尊重引号字符串。"""
    found: list[str] = []
    start = -1
    depth = 0
    quote = ""
    escaped = False
    for index, char in enumerate(text):
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = ""
            continue
        if char == '"':
            quote = char
        elif char == "[":
            if depth == 0:
                start = index
            depth += 1
        elif char == "]" and depth > 0:
            depth -= 1
            if depth == 0 and start >= 0:
                found.append(text[start : index + 1])
                start = -1
    return found


def _loads(block: str) -> Any:
    """Decode JSON with the existing trailing-comma fallback / 按既有尾逗号回退规则解析 JSON。"""
    block = block.strip()
    if not block:
        return None
    try:
        return json.loads(block, strict=False)
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    cleaned = re.sub(r",\s*([\]}])", r"\1", block)
    if cleaned == block:
        return None
    try:
        return json.loads(cleaned, strict=False)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None


class ExtractionParseError(ValueError):
    """Report model text without a recoverable JSON array / 报告模型文本中不存在可恢复 JSON 数组。"""


def parse_response_checked(text: str) -> list[dict]:
    """Parse a JSON array; invalid text raises instead of becoming valid empty output / 解析 JSON 数组，无效文本抛错而非变成合法空输出。"""
    if not isinstance(text, str) or not text.strip():
        raise ExtractionParseError("empty model response")
    blocks = [text.strip(), *_fenced_blocks(text), *_balanced_arrays(text)]
    tried: set[str] = set()
    for block in blocks:
        if not block or block in tried:
            continue
        tried.add(block)
        data = _loads(block)
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
    raise ExtractionParseError("response does not contain a JSON array")


def parse_response(text: str) -> list[dict]:
    """Keep the legacy invalid-output empty-list fallback / 保留旧的无效输出返回空列表行为。"""
    try:
        return parse_response_checked(text)
    except ExtractionParseError:
        return []
