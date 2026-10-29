"""Keep legacy pure compression prompt/parser helpers; production extraction does not call them.

保留旧的纯压缩提示词及解析帮助函数，生产抽取不调用这些函数。
"""

from __future__ import annotations

import re

_EMPTY_FACTS = ("", "无", "没有", "暂无", "none", "null")


def build_compress_prompt(dialogue: str) -> str:
    """Build the existing three-line compatibility prompt without invoking a model / 构造既有三行兼容提示词，不调用模型。"""
    body = dialogue.strip() if isinstance(dialogue, str) else ""
    return (
        "把下面这段对话压缩成三行，只输出这三行，不要解释，不要 Markdown。\n\n"
        "情绪：<一个词>\n"
        "未完成：<一句话或 无>\n"
        "事实：<最多两条或 无>\n\n"
        "要求：\n"
        "1. 情绪只写一个词，例如 平静/开心/累/低落/生气。\n"
        "2. 未完成只写对话里还悬着的事；已经说完的写 无。\n"
        "3. 事实只写值得留下的、确定的信息，最多两条，用顿号分隔。\n"
        "4. 不要复述整段对话，不要添加对话里没有的信息。\n\n"
        "【对话】\n" + (body or "（无）")
    )


def _first_word(value: str) -> str:
    """Keep the first supported emotion word or an empty value / 保留首个受支持的情绪词或空值。"""
    value = value.strip("。.!！ ")
    if value.lower() in _EMPTY_FACTS:
        return ""
    for part in re.split(r"[，,；;、\s]+", value):
        part = part.strip("。.!！ ")
        if part:
            return part
    return ""


def _split_facts(value: str) -> list[str]:
    """Parse at most two facts using existing separator rules / 按既有分隔规则解析至多两条事实。"""
    if value.strip().lower() in _EMPTY_FACTS:
        return []
    facts: list[str] = []
    for part in re.split(r"[、,，;；]\s*", value):
        part = re.sub(r"^\s*\d+\s*[.、)]\s*", "", part).strip("。.!！ ")
        if part and part.lower() not in _EMPTY_FACTS:
            facts.append(part)
        if len(facts) >= 2:
            break
    return facts


def parse_compress(text: str) -> dict:
    """Parse the legacy three-line response with defaults for absent fields / 解析旧三行响应，缺失字段使用默认值。"""
    result: dict = {"emotion": "", "unfinished": "", "facts": []}
    if not isinstance(text, str):
        return result
    for raw in text.splitlines():
        line = raw.replace("**", "").strip()
        line = re.sub(r"^(?:[-*•]|\d+[.、)])\s*", "", line)
        match = re.match(r"(情绪|未完成|事实)\s*[：:]\s*(.*)$", line)
        if not match:
            continue
        label, value = match.group(1), match.group(2).strip()
        if label == "情绪":
            result["emotion"] = _first_word(value)
        elif label == "未完成":
            result["unfinished"] = "" if value.lower() in _EMPTY_FACTS else value
        else:
            result["facts"] = _split_facts(value)
    return result
