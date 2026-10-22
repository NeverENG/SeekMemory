"""唤起方式门控：这条消息该不该翻记忆，翻多宽。

人不是每句都去翻回忆的。寒暄、问几点、让你写个正则，这些不需要翻；
说"上次那事儿"、说"我好累"，才需要把相关的旧事拎上来。

三种结果：
- ``none``   不检索（只留常驻层：人格与印象）
- ``strict`` 正常检索（证据闸门按默认阈值）
- ``loose``  放宽检索（明确回忆或情绪场景，多给一点预算）
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
    """是否是明确的聊天回忆请求。"""
    return bool(TOPIC_RECALL.search(str(text or "")))


def is_profile_recall(text: str) -> bool:
    """是否在询问个人基础信息。"""
    return bool(PROFILE_RECALL.search(str(text or "")))


def intent_of(text: str) -> str:
    """返回 none / strict / loose。空消息按 strict 处理（由上层决定）。"""
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
