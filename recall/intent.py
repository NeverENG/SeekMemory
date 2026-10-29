"""Classify existing recall intent from supplied text without model calls.

按给定文本判断既有召回意图，不调用模型。
"""

from __future__ import annotations

import re

CLOCK = re.compile(
    r"^(今天|现在|此刻)?(几号|多少号|星期几|周几|几点|什么时候了|什么日子)", re.I
)
GREET = re.compile(
    r"^(在吗|在不在|在么|早|早安|早上好|中午好|下午好|晚上好|晚安|睡了|睡了吗|"
    r"吃了吗|吃了没|干嘛呢|在干嘛|你好|哈喽|嗨|嗯+|哦+|啊+|哈+)[\s。！？!?~～]*$"
)
OPERATE = re.compile(
    r"(帮我|给我|帮我写|写个|写一个|翻译|查一下|搜一下|算一下|计算|怎么用|怎么配置|"
    r"报错|异常|堆栈|正则|代码|函数|接口|命令|部署|安装|卸载|升级)"
)
RECALL = re.compile(
    r"(还记得|记不记得|上次|上回|之前|以前|那天|当时|我说过|我提过|我跟你说过|"
    r"我叫什么|我的名字|我是干什么的|我是哪里人|你最了解我|你觉得我这个人|群聊里|群里.*聊|聊了啥|聊过什么|说过什么|基础信息|你了解我|知道我是谁)"
)
MOOD = re.compile(
    r"(累|难过|崩溃|烦|焦虑|压力|委屈|想哭|不开心|心情|睡不好|失眠|难受|撑不住)"
)


TOPIC_RECALL = re.compile(
    r"(记得我们|我们.*聊|聊了啥|聊过什么|说过什么|群聊里.*聊|群里的.*聊|之前.*聊)"
)
PROFILE_RECALL = re.compile(
    r"(基础信息|我的信息|我是谁|我的名字|我是做什么的|我是哪里人|你了解我|知道我是谁)"
)


def is_topic_recall(text: str) -> bool:
    """Recognize an explicit conversation-memory question / 识别明确的聊天回忆问题。"""
    return bool(TOPIC_RECALL.search(str(text or "")))


def is_profile_recall(text: str) -> bool:
    """Recognize an explicit personal-profile question / 识别明确的个人基础信息问题。"""
    return bool(PROFILE_RECALL.search(str(text or "")))


def intent_of(text: str) -> str:
    """Return the existing none/strict/loose recall mode / 返回既有 none、strict 或 loose 召回模式。"""
    line = str(text or "").strip()
    if not line:
        return "strict"
    if CLOCK.search(line) or GREET.match(line):
        return "none"
    if RECALL.search(line) or PROFILE_RECALL.search(line):
        return "loose"
    if MOOD.search(line):
        return "loose"
    if OPERATE.search(line) and len(line) <= 40:
        return "none"
    return "strict"
