# SeekMemory Issues 索引

> 审计基准：`main` @ 首次审计 `1be8baa`，之后随修复推进更新。行号以当前工作树为准。
> 级别口径：P1 = 设计承诺的核心功能失效或隐私边界失效；P2 = 能力缺失/未接线；
> P3 = 增强。状态：`open` 未修、`merged` 已修并合入、`closed` 已关闭。

| 编号 | 标题 | 级别 | 状态 | 一句话 |
|---|---|---|---|---|
| [ISSUE-0001](ISSUE-0001.md) | 无 BM25 / 向量检索，同跨度问法的召回为 0 | P1 | open | 零字面重合时 seeds=0，6/6 里的那一题是 weight 先验兜底，不是语义召回。 |
| [ISSUE-0002](ISSUE-0002.md) | 缓冲层只是一个内存列表：没有话题聚合、没有 24h TTL、没有落盘 | P1 | closed | 重启即丢；不按话题聚合，早上“要辞职”、晚上“算了”会被同一晚抽走。 |
| [ISSUE-0003](ISSUE-0003.md) | 检索从不按 scope 过滤：private / shadow 记忆会被注入给所有人 | P1 | closed | `_recall_block()` 取全库 active，`scope=shadow` 的正文会全文注入；benchmark 的零泄漏是脚本预过滤。 |
| [ISSUE-0004](ISSUE-0004.md) | 指定记忆永远不会归还：私聊、触发词、已给状态三条硬条件全缺 | P1 | closed | `designated` 只输出“等提到 X 再告诉他”的提示句，`payload["text"]` 从不交付。 |
| [ISSUE-0005](ISSUE-0005.md) | RBAC 只有一道写入门控：trusted 的 80 字、guest/blocked 的角色语义都没有 | P2 | open | 一个 bool + 全局 `budget_chars`；trusted 拿 600，blocked 不存在。 |
| [ISSUE-0006](ISSUE-0006.md) | 沉淀链路断了：promote 只返回候选，persona 永远为空，抽象树只实例化不使用 | P2 | closed | `promote_candidates()` 无调用方，`make("persona")` 只出现在测试，`Tree.add_under()` 生产不用。 |
| [ISSUE-0007](ISSUE-0007.md) | 每周整理只跑“衰减 + 合并”两步：六步流程缺四步，Dream 矛盾检查与审批完全没有 | P2 | open | 周任务确实会跑，但只做 2/6；没有补跑、没有 proposal/审批。 |
| [ISSUE-0008](ISSUE-0008.md) | 关系曲线不存在：没有日常快照、没有滑动窗口，组装头部也没有“关系结论” | P2 | open | `about=relation` 只改人称；DESIGN 只写“关系曲线滑窗”，14 天窗口尚未进规格。 |
| [ISSUE-0009](ISSUE-0009.md) | 写入从不建联想边：激活扩散永远只返回种子，扩散贡献为 0 | P2 | closed | 生产写入只 `db.upsert`，不建 `similar/causal/temporal` 边；`ANALYSIS.md` 实测新增候选 0。 |
| [ISSUE-0010](ISSUE-0010.md) | 容量治理只实现了第一级：merge 只看 scene/detail、五级淘汰缺两级、没有 blob 清理 | P2 | open | 第 1 级可用；第 2 级口径错，第 3 级要 3 条，第 4/5 级缺失，首因也没实现。 |
| [ISSUE-0011](ISSUE-0011.md) | 强化与命中计数没接线：hits 永远不涨、hot 永远不设、同一段记忆会反复注入 | P2 | in_progress | `reinforce()`/`hit_cooldown_ok()` 只有测试调用，`last_used/hot_until` 只读不写。 |
| [ISSUE-0012](ISSUE-0012.md) | 时间只做了半截：相对时间缺“上个月/很久以前”，事件时间被写成写入时间，chrono/有效期不参与检索 | P2 | open | `_when()` 六档且用 `date.today()`；`created` 是入库时间；periodic/annual/valid_to 都没接。 |
| [ISSUE-0013](ISSUE-0013.md) | Source / evidence 从未落库，media 没有抽取路径，外部源适配器缺位 | P2 | in_progress | `add_source`/`link_evidence` 无调用方；media 只有校验和渲染；`SourceAdapter` 不存在。 |
| [ISSUE-0014](ISSUE-0014.md) | 反思模块没接线：signals 只有测试在调，冷处理、错误留档、负权重、情绪闭环都没有 | P2 | open | `enable_reflect` 是死配置；没有 pending 表、没有 mistake、没有 weight=-0.3。 |
| [ISSUE-0015](ISSUE-0015.md) | 措辞没有三档不确定，也没有 metamemory：confidence 不参与表达，分不清“我忘了”和“你没说过” | P3 | open | `_memory_sentence()` 永远“你记得”；缓存只装 active，查不到同话题 forgotten。 |
| [ISSUE-0016](ISSUE-0016.md) | 无语境回忆（random_recall）完全没实现：空消息直接 return，10% 探索只在有 query 时发生 | P3 | open | 没有 `funny × weight × noise` 排序，也没有 hot/sensitive 排除和“长期+缓冲”双池。 |
| [ISSUE-0017](ISSUE-0017.md) | 没有相关性闸门：select 永远凑满 top-k | P1 | closed | PR-0017 落双阈值（无效）→ PR-0018 换证据闸门：检索层噪声 81%→40%、常驻层 38 字单列、边界正文泄露 0、时钟题 0 检索。 |
| [ISSUE-0019](ISSUE-0019.md) | 静态黄金集饱和：run.py 100/100、ablation 17/18 | P2 | open | 三个静态基准全部贴顶，下一轮改动会得到「没有变化」的假结论；需要多跳/时序撤回/冲突消解/跨会话任务集。 |
| [ISSUE-0020](ISSUE-0020.md) | Artifact kernel and version chain foundation | P1 | closed | CAS commits, append-only versions, state events, evidence and ledger. |
| [ISSUE-0021](ISSUE-0021.md) | Pending backlog can starve extraction and flush can drop sessions | P1 | closed | Backlog flush and session-safe draining. |
| [ISSUE-0022](ISSUE-0022.md) | Consolidate writes, disclosure and retrieval boundary | P1 | closed | All production writes use commit; disclosure and lexical candidate boundary. |
| [ISSUE-0023](ISSUE-0023.md) | Topic buffer, subject attribution and event time | P1 | closed | Typed DialogueTurn buffer, subject_id, event_at and TTL trigger. |
| [ISSUE-0024](ISSUE-0024.md) | BM25 hybrid retrieval for Chinese memory recall | P1 | open | 默认开启本地 BM25，显式关闭可回滚；验收与后续边界统一记录于 Issue。 |
| [ISSUE-0025](ISSUE-0025.md) | v0.3.2 local WebUI, private recall, BM25 shadow and persona timeline | P1 | open | GitHub #6 tracking issue. |
| [ISSUE-0026](ISSUE-0026.md) | Recall feel fallback and shared disclosure | P1 | open | Explicit recall fallback plus same-session shared exposure. |
| [ISSUE-0027](ISSUE-0027.md) | Public interface guide and contract tests | P2 | open | GitHub #13 contributor infrastructure. |

## 关系图（读的顺序）

- **隐私/可见性**：ISSUE-0003（scope 过滤）→ ISSUE-0004（指定记忆交付）→
  ISSUE-0005（角色预算）。三条都依赖“viewer 是谁”和 `said_by` 的正确写入。
- **写入链路**：ISSUE-0002（缓冲）→ ISSUE-0013（source/evidence）→
  ISSUE-0014（反思/错误留档）→ ISSUE-0011（强化/命中）。
- **沉淀链路**：ISSUE-0006（promote/persona/tree）→ ISSUE-0007（周任务编排）→
  ISSUE-0010（容量淘汰）→ ISSUE-0008（关系曲线）。
- **检索链路**：ISSUE-0001（BM25/向量）→ ISSUE-0009（联想边）→
  ISSUE-0012（时间/有效期）→ ISSUE-0015（不确定/metamemory）→
  ISSUE-0016（无语境回忆）。

## 关于竞品可借鉴点

`COMPARISON.md` 里的 angel_memory（BM25 CJK + 能量槽 + 睡眠巩固）和
memory_companion（断言层/修订/权限拓扑/RRF+MMR）确实值得借鉴，但它们是
**增强**，不是“DESIGN 写了没实现”。本轮不单开 issue：

- BM25/向量已由 ISSUE-0001 覆盖；
- 能量槽、断言层、RRF+MMR 要等检索底座（0001）和 scope/权限（0003/0005）
  落地后再评估，否则会在错误的池子上做排序；
- 睡眠巩固与 ISSUE-0007（周任务）有重叠，先把六步跑通再谈“巩固”。

## 复核方式

每个 issue 的“现状”都带 `文件:行号`，可用下面的命令快速抽查：

```bash
cd SeekMemory
grep -n "_pending\|_may_remember\|_recall_block\|budget_chars" main.py
grep -rn "scope" --include="*.py" recall main.py store/cache.py
grep -rn "promote_candidates\|add_source\|link_evidence\|reinforce(" --include="*.py" .
grep -n "def _when\|def _guarded_sentence\|def _memory_sentence" recall/assemble.py
grep -n "MAX_ACTIVE\|len(pool)\|family != \"memory\"" maintain/merge.py maintain/decay.py
```
