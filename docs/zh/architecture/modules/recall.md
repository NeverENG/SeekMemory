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

## 披露与交付

core.disclosure 将上下文亲和、subject fit、scope prior、敏感度和相关度组合为 full、paraphrase、hint 或 silence。低于 full 的记忆用固定通用句，不暴露原始文本或 tags。被选中不等于最终注入；被注入也不代表模型实际引用。

family=secret 完全不会进入普通候选。scope=shadow 的 memory 只允许遮蔽表达。family=designated 独立执行私聊 + 触发词 + 尚未交付检查；只有正文确实出现在最终块时才提交 given 状态。管理诊断以 dry_run 运行，不消耗一次性交付状态。

## 观测

返回的 info 包含 mode、候选计数、gate 结果、披露等级、fallback、final_ids、dropped_ids 和 Source fallback 计数。正常日志只应记录统计与 ID；不应输出 Source 正文或组装的私密内容。
