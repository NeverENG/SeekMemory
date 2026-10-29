# recall：检索、披露与提示组装

## 职责

recall 负责从 active Artifact 候选中取出与当前输入相关、可以在当前场景表达的内容，并输出有字符预算的文本块及决策元数据。模块不调用模型，也不直接写 SQL；图边、历史和 Source 回查可能经过注入的仓储读取。

## 执行顺序

1. pipeline 计算当前 speaker/owner，并从 Cache 取 active Artifact。
2. scope.visible 排除 family=secret；designated 只能由归属会话读取。普通 memory 的 private、shared、shadow 不按来源会话做硬过滤；scope 会影响后续披露强度。private 不代表跨会话正文必然可见。
3. 有效期和显式时间查询先过滤过期/不在日期窗内的 memory。designated 还要求私聊、触发词命中且没有给过。
4. 有记忆意图时由 Retriever 产出候选：GraphRetriever 用字符二元组种子和图激活；HybridRetriever 在原激活分数上加本地 BM25 lexical 分数。BM25 正文与 tags 分开索引，仅用本次可见池统计，不产生模型、网络或 SQL 调用。
5. select 先以字面、标签、情绪、激活和 lexical 计算相关性证据，通过绝对与相对 evidence gate，再用 weight、新鲜度和最近使用情况排序。先验权重不能单独让无关候选过闸。
6. 显式 profile/topic 回忆可走近期记忆 fallback；没有候选时，有限场景可触发一次确定性主动浮现。
7. 当普通选中不足 min(2, recall_k)，且查询有记忆意图时，Source fallback 查询时间/数量受限的近期 Source。它只用 Source IDs 经 artifact_evidence 找 active Artifact，并再次执行可见性、有效期与披露；Source 正文不会被组装。
8. 统一披露后由 assemble 按 persona、impression、scene、detail、fact 和 example 等顺序组织文本，在预算内裁剪并返回 final_ids / dropped_ids。

Source 回查的新鲜度对带时区的值按绝对时刻计算；无时区的值沿用运行环境本地时间比较，不改写原始 Source。

## 披露与交付

core.disclosure 将上下文亲和、subject fit、scope prior、敏感度和相关度组合为 full、paraphrase、hint 或 silence。低于 full 的记忆用固定通用句，不暴露原始文本或 tags。被选中不等于最终注入；被注入也不代表模型实际引用。

family=secret 完全不会进入普通候选。scope=shadow 的 memory 只允许遮蔽表达。family=designated 独立执行私聊 + 触发词 + 尚未交付检查；只有正文确实出现在最终块时才提交 given 状态。管理诊断以 dry_run 运行，不消耗一次性交付状态。

## 观测

返回的 info 包含 mode、候选计数、gate 结果、披露等级、fallback、final_ids、dropped_ids 和 Source fallback 计数。正常日志只应记录统计与 ID；不应输出 Source 正文或组装的私密内容。

## 明确接口与副作用

`recall/domain.py` 明确导出受支持查询、检索及组装入口和上下文注入写入入口；`recall/ports.py` 复用 app 已有仓储、缓存及检索器协议。旧导入保持可用。`query_block()` 与 `RecallService.query()` 是纯记忆查询：允许缓存、原始消息、版本读取及派生内存索引，不提交记忆或修改给出状态；预览使用纯查询。

`record_context()` 与 `RecallService.record_context_injection()` 是明确写入：仅当指定记忆正文出现在最终块中且编号通过组装时，记录该记忆。含义仍为**正文已进入模型上下文**，与之后模型或发送成功无关。AstrBot 在将块附加到请求后记录；延迟和主动运行时在模型调用前立即调用可选通用 `MemoryContextRecorder`，运行时不包含指定记忆领域规则。

旧 `build_block()` 与 `RecallService.build()` 保留参数、返回值和默认的查询加记录行为，`dry_run=True` 仍只读。新增调用方需要注意这一兼容副作用；运行时构造上下文使用服务的纯查询。

| 文件 | 职责与副作用 | 逻辑复杂度及耦合 |
|---|---|---|
| `pipeline.py` | 候选→评分及筛选→披露→组装，以及兼容写入包装 | 中至高：协调既有规则，无重复查询实现 |
| `selection.py` | 配置解释、说话人身份及近期记忆回退 | 低：纯规则，主体贴合是排序信号 |
| `source_fallback.py` | 限量证据读取→当前记忆查找 | 中：仅查询，不注入原始消息正文 |
| `disclosure.py` | 应用共享隐私决策及安全措辞替换 | 中：渲染前唯一披露阶段 |
| `context_recording.py`、`designated.py` | 明确上下文包含记录及既有私聊、触发词条件 | 中：版本写入与查询分开 |
| `retriever.py`、`bm25.py`、`seed.py`、`tokenizer.py`、`spread.py` | 派生字面及图信号、索引失效及有限扩展 | 中：不调用模型或网络，不写业务状态 |
| `score.py`、`gate.py`、`intent.py`、`temporal.py` | 既有评分、证据、意图及日期规则 | 中：公式、阈值及时间行为不变 |
| `assemble.py`、`history.py`、`drift.py`、`scope.py` | 叙述预算、可选印象历史、偶然浮现及明确候选访问 | 中：调用方提供候选和资源 |

`tests/test_recall_context_integration.py` 覆盖纯读取、兼容默认写入、明确重复记录、预算丢弃正文及模型或发送失败时机。`tests/test_recall_interface_contract.py` 验证明确导出及可选通用运行时能力；全新导入检查覆盖顶层及插件命名空间。既有隐私、范围及冻结 BM25 验收仍需执行，这些测试不是真实模型质量证据。

## 上下文记录恢复

`RecallService` 唯一持有一个 `ContextRecorder`，管理进程内待提交包含记录及仅需缓存的补偿。查询信息包含通过组装的指定编号及观察版本，记录保留该版本与原始时间戳。数据库提交失败继续待处理；版本变化或预期版本冲突时丢弃旧记录，不将它重放到新正文。数据库成功后，在缓存操作前消费待提交状态；即使缓存刷新失败，也计为一次已提交标记。

纯查询读取指定记忆当前数据库版本，不回填缓存；指定版本读取失败时不提供该项，旧缓存不能再次注入已提交给出标记的正文。仅需缓存的补偿读取数据库最新版本，不再次提交给出记录。`retry_writebacks()` 仅完成已准备持久化，不重新召回、生成或发送；既有后台频率及停止流程独立于抽取或发言开关委托该补偿。

旧 `mark_given()` 和 `record_context()` 通过同一实现尝试一次，需要后续补偿的调用方应像 RecallService 一样保留 `ContextRecorder`。补偿限当前进程，不新增结构、任务或崩溃和跨进程保证。`tests/test_recall_failure_recovery.py` 覆盖提交或读取失败、缓存连续失败、新版本、旧及冲突凭据、兼容计数和停止补偿。撤销恢复提交无需数据迁移。
