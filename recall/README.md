# recall · 检索与组装

## 管什么

输入一条用户消息和当前记忆池，输出一段可直接拼进 system prompt 的中文记忆。
链路是 `visible → Retriever → select → disclosure → build`：先按 scope 过滤，
默认用字符 Dice 种子和图激活；启用 BM25 时附加词面证据，再过相关性闸门、披露和预算组装。
检索不调用模型或网络，BM25 无新增运行依赖。图邻居、来源及历史轨迹仍可能读取 SQLite。

## 文件表

| 文件 | 行数 | 职责 |
| --- | ---: | --- |
| `__init__.py` | 0 | 空包标记 |
| `scope.py` | 64 | `visible()`：private 只给归属会话，shared / shadow 全员可见 |
| `designated.py` | 85 | 指定记忆交付：私聊 + 触发词 + given 三条硬条件 |
| `seed.py` | 173 | `seeds()`：二元组重合度 + 梗标签加分，取 top-limit 个种子 id |
| `spread.py` | 75 | `activate()`：每跳乘 0.5、每轮只留 top 20 的激活扩散 |
| `tokenizer.py` | — | `tokenize()`：小写化、字符 bigram、保留词频，无中文停词表 |
| `bm25.py` | — | `BM25Index`：正文/标签倒排索引与可见池 BM25 计分 |
| `retriever.py` | — | GraphRetriever 保留原路径，HybridRetriever 合并 activation/lexical |
| `pipeline.py` | — | 意图、配置、可见池、披露、组装与只读诊断编排 |
| `score.py` | 267 | `score()` 按 DESIGN 5.1 打分；`select()` 过双阈值闸门后取 top-k + 10% 探索 |
| `assemble.py` | 264 | `build()`：叙述化组装；shadow 只给影子句，超预算先砍 example 再砍 detail |
| `README.md` | 41 | 本文件 |

## 依赖方向

```
scope       → core.artifact (Artifact)
designated  → core.artifact (Artifact, revise)
seed        → core.artifact (Artifact, content_of)
spread      → core.graph (Graph), store.cache (Cache)
score       → core.artifact, recall.seed (overlap, tags_of)
assemble    → core.artifact, recall.designated (deliverable, triggers_of)
bm25        → core.artifact, recall.seed (tags_of), recall.tokenizer
retriever   → core.graph, core.retrieval, store.cache, recall.bm25
pipeline    → app.ports (Retriever), core/store/recall
```

检索器复用 `app.ports.Retriever` 协议，不 import `astrbot`、不碰 SQL。
`build()` 信任 `arts` 的传入顺序就是相关度降序；`select()` 的候选既可以是
裸 `Artifact`、旧 `(Artifact, activation)` 二元组或 `RetrievalCandidate`；生产管线使用后者。
`now_days` 传 0 会用 `time.created` 推算年龄，传正小数视为年龄，传大数
视为绝对天数（epoch days / ordinal）。`select()` 默认开启证据闸门：
只有字面 / lexical / 标签 / 情绪 / 激活累计证据达到
`max(min_ev_abs, top_evidence × min_ev_rel)` 的候选才保留，全不达标返回空列表；
`weight` / `freshness` 只参与排序。纯问时间的时钟类消息直接返回空。
`gate=False` 回到“凑满 top-k”的旧行为，供消融对比。`gate.pinned(cache)` 返回
常驻层（persona + 印象前 2），不经过证据闸门。`build()` 的
`text` / `is_private` 是
可选会话上下文：不传时 designated 只给托付提示（旧行为），传了才按三条硬
条件交付正文。

## 可选 BM25

配置 `bm25_enabled` 默认 true，未提供配置时同样开启；`bm25_weight` 默认 1.0，`select()` 的函数默认 lexical_weight
仍为 2.0，以兼容旧调用。BM25 的 k1=1.2、b=0.75，正文/标签分别经 `s/(s+8)` 后按 0.75/0.25 融合。
插件组合入口持有 HybridRetriever，聊天和诊断共用；缓存 version 变化时重建，IDF 与长度统计仅取本次可见池。
显式关闭开关恢复旧行为，BM25 可独立运行。语义分数不可填入 lexical。
校准、已知漏题、回滚方式与后续边界见 [ISSUE-0024](../docs/issues/ISSUE-0024.md)。
