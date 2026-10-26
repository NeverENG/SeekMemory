# ISSUE-0034 人格注入被 180 字截断：seed 人格永远只到第一段

| 项 | 值 |
|---|---|
| 编号 | ISSUE-0034 |
| 级别 | P1（人格注入失效，等价于人格只剩三分之一） |
| 状态 | merged |
| 发现方式 | 2026-10-26 线上 persona file bootstrap 验收 |
| 日期 | 2026-10-26 |
| 关联 PR | [PR-0034](PR-0034.md) |

## 症状

按 `docs/PERSONA_SEED.md` 把人格文件 bootstrap 成 seed 人格后，召回常驻层**没有注入完整人格**：

```
修复前注入片段：
你是大肥鱼。DeepSeek 那只圆滚滚的蓝鲸。……你知道自己记性时好时坏
```

只到 180 字左右就断了，后面的「不装傻」「分寸」「安全线」「说话规则」全部丢失。
同时 `calls.jsonl` 里 `chars` 只有 60~75——因为人格句被截断后总长度也变小。

## 原因

`recall/assemble.py` 的 `_persona_sentence()` 复用了通用清洗函数：

```python
def _persona_sentence(art):
    return _clean(_voice(_raw(art), "self"))

def _clean(value, limit=180):   # 单条记忆句的上限
    ...
```

`_clean` 的 180 字上限是为「一条记忆一句话」设计的。人格是**整段设定**，
走同一个入口必然被截断；而 assemble 的预算裁剪逻辑里 persona 属于 header，
不会被逐条丢弃，所以表现就是「人格永远只有开头 180 字」。

## 期望

1. persona 句子不按单条记忆的 180 字上限截断；
2. 长度只由注入预算约束（`budget_chars`），persona 属于 header 层，保持整段；
3. 加回归测试：长人格（>180 字）注入后必须包含结尾标记；
4. 提供可复用的 bootstrap 命令行入口，避免每次手写脚本。

## 验收标准

- 长人格文本注入后包含末尾规则句（回归测试覆盖）；
- bootstrap 两次落在同一条人格链，revision 递增、seed 来源字段保留；
- `scripts/bootstrap_persona.py --dry-run` 可只校验不写库；
- 全量测试不新增失败（本地环境相关的既有失败不计）。
