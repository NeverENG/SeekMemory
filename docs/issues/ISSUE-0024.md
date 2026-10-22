# ISSUE-0024 BM25 hybrid retrieval for Chinese memory recall

| item | value |
|---|---|
| id | ISSUE-0024 |
| level | P1 |
| status | open |
| date | 2026-10-21 |
| GitHub | [#4](https://github.com/NeverENG/SeekMemory/issues/4) |
| branch | feat/issue-0024-bm25 |
| PR | [#7](https://github.com/NeverENG/SeekMemory/pull/7) |

## Problem

Current recall depends on character-bigram overlap, tags and graph activation. Queries that
paraphrase or reorder the original memory often return zero candidates.

RetrievalCandidate.lexical already exists, but no retriever fills it. This is the smallest
surface for adding BM25 without changing the cognitive model, evidence gate or disclosure rules.

## Scope

- Add a tokenizer boundary with a zero-dependency character-bigram default.
- Add an in-memory BM25 index with text and tag fields.
- Add HybridRetriever that merges graph activation and lexical scores.
- Add config keys bm25_enabled and bm25_weight.
- Enable BM25 by default; keep an explicit disable switch to restore graph-only retrieval.
- Calibrate evidence gate thresholds and lexical weight with benchmarks.
- Keep disclosure and cross-session privacy unchanged.

## Acceptance criteria

- [x] BM25 index supports add/remove/search and normalized lexical scores.
- [x] HybridRetriever returns one candidate per Artifact with activation and lexical.
- [x] BM25 score contributes to evidence gate only through lexical evidence.
- [x] Empty/punctuation-only queries produce zero lexical evidence.
- [x] Recall remains correct when bm25_enabled is false.
- [x] Unit tests cover tokenizer, index, hybrid merge and empty query.
- [x] Ablation reports hit rate, noise, injected chars and latency on/off.
- [x] Per the user's 2026-10-22 instruction, schema and missing-key fallback enable BM25 by default.
- [ ] Lead review, staging validation and production deployment.

## Implementation checklist

- [x] recall/tokenizer.py
- [x] recall/bm25.py
- [x] Cache.version and index rebuild policy
- [x] HybridRetriever
- [x] recall/score.py configurable lexical weight
- [x] config keys and docs
- [x] tests/test_bm25.py
- [x] benchmark before/after

## 补充：2026-10-22 实现决策与校准

- 使用纯本地、无新依赖的字符 bigram BM25，不引入模型、下载器、网络调用或外部服务。
- 不维护人工中文停词表；空输入/纯标点无词项，单字符保留自身，文档保留词频。
- 归一化改为固定映射 `s/(s+C)`，不使用逐查询最大值；正文/标签按 0.75/0.25 融合。
- 保留旧黄金集与证据闸门。权重 2.0 导致旧消融基准 17/18 降至 16/18，已向用户报告。
- 经用户确认扩大权重校准至 0.5/1/1.5/2，与 C=1/2/4/8 交叉比较。
- 冻结参数 C=8、默认权重 1.0：旧集 17/18、检索层噪声 0.4000→0.3723；
  五条字面校准题 0/5→3/5。独立验收集运行前选定，不根据验收结果再调参。
- 原末五条探索题曾观察结果，不作为独立 holdout。新的五条独立合成数据位于
  `benchmarks/bm25_holdout.py`，冻结 SHA256：
  `2C2ADE9A29AEF9D8DD55664B816988340BE09143A31177978EAAB6CCF3BE3569`。
- 最初按默认关闭实现；同日后续用户指令改为默认开启，见下方当前决策。
  复用现有 Retriever 协议，不添加 semantic 占位字段；本地向量约束保留在本 Issue，本次不实现。

## 补充：2026-10-22 验证与评审完成

- 实现与验证记录统一保存在本 Issue，关联 [PR #7](https://github.com/NeverENG/SeekMemory/pull/7)。状态保持 open，待 Lead 审阅和 staging 对照。
- [x] tokenizer、正文/标签 BM25 倒排表、Cache.version 和 HybridRetriever 已实现。
- [x] 配置、调用契约、显式关闭兼容、完整管线及 WebUI 诊断只读已验证。
- [x] 旧集保持 17/18、噪声 40.00%→37.23%；独立题 1/5→2/5，未修改数据或金标。
- [x] Python 256 项测试检查通过（11 项宿主测试跳过）；真实 AstrBot 4.28.1 单独运行 11 项全通过。
- [x] 前端类型、lint、29 项测试、2 项跨语言契约及生产构建通过；LF 副本格式检查通过。
- [x] Standards 与 Spec 两轴评审各发现一项问题，均修复并独立复核；没有未解决发现。
- [ ] Lead 审阅、staging 效果和资源对照、生产启用决策。

## 当前决策：2026-10-22 默认开启与 Issue 归档

用户明确要求删除独立 PR 文档与两份提案，以 Issue 跟踪实现、验收和风险，并将 BM25 从默认关闭改为默认开启。
本节取代此前的默认关闭 rollout 约定，不修改线上环境或已显式保存为 false 的配置。

- `_conf_schema.json` 中 `bm25_enabled.default=true`；`build_block()` 缺少该键时同样按 true 处理。
- 显式 `bm25_enabled=false` 恢复 GraphRetriever，并且不读取 BM25 权重，残留无效权重不会阻止回滚。
- 权重仍为 1.0；`select(..., lexical_weight=2.0)` 的函数默认值保留旧调用兼容。
- 默认开启只改变检索路径，不绕过原证据闸门、可见池、披露或指定记忆交付规则。
- BM25 使用 k1=1.2、b=0.75，正文/标签分别以 `s/(s+8)` 归一化后按 0.75/0.25 融合。
  标签独立分词，不生成跨标签词项；N、df 和平均长度只来自当前可见候选池。
- 聊天与 WebUI 诊断复用长期检索器，Cache.version 改变后从活跃缓存重建索引；诊断仍 dry_run。

## 验收结果与复现

黄金集、校准集与独立验收集的原数据和期望不变；独立验收结果不用于继续调参。

| 指标 | 关闭 | 开启 |
|---|---:|---:|
| 原基础基准综合指标 | 100/100 | 现有指标保持 100/100，另有开关对照 |
| 原规模集可答题命中 | 5/6 | 5/6 |
| 原消融集命中 | 17/18 | 17/18，逐题无新增漏召 |
| 原集检索层字数加权噪声 | 40.00% | 37.23% |
| 原集平均总注入字数 | 57.65 | 55.85 |
| 原集边界正文泄露 | 0 | 0 |
| 五条字面校准题 top-8 命中 | 0/5 | 3/5 |
| 五条独立合成题 top-8 命中 | 1/5 | 2/5 |
| 独立题候选噪声 | 97.5% | 95.0% |
| 独立题平均组装字数 | 209.2 | 210.8 |
| 规模集平均延迟，含首次构建 | 0.849 ms | 2.400 ms |

数字来源：`benchmarks/results/latest.md`、`scale.md`、`ablation.md`、`bm25.json`。
原消融噪声按检索层字数加权，独立题噪声按候选数计算，两个百分比不能直接比较。
5k/20k 文档索引构建约 54/239 ms、重建约 56/234 ms、暖查询约 13/59 ms，均为本机测量。

```bash
python -m unittest discover -s tests -p 'test_*.py' -q
python -X utf8 tests/test_smoke.py
python -X utf8 benchmarks/run.py
SCALE_USERS=8 SCALE_DAYS=30 SCALE_MSGS=40 python -X utf8 benchmarks/scale.py
python -X utf8 benchmarks/ablation.py
python -X utf8 benchmarks/bm25.py
```

完整套件需安装 `requirements-dev.txt`。已有宿主测试假定至少三层父目录，
`D:/project/SeekMemory` 路径太浅会触发既有 IndexError；完整验证在较深的源码副本中执行。
真实宿主验证使用 Python 3.12、AstrBot 4.28.1，11 项包含生产页面发现均通过。
默认开启后完整套件为 257 项（246 项执行通过、11 项宿主测试跳过），真实宿主 11 项另行全部通过。
新增默认/schema/缺省配置行为及显式关闭回滚的 9 项管线测试通过；BM25 冻结验收和打包冒烟通过。
前端 TS 7、lint、29 项单测、2 项跨语言契约和构建已在前轮通过，本轮没有前端源码变更。

前端使用 CI 的 pnpm 10.13.1 按锁文件安装；本机 pnpm 12 曾拒绝上游新发布的锁定包，
使用固定版本后成功，未修改锁文件。core.autocrlf=true 的主检出对 58 个 CRLF 文件报格式差异，
相同 Git 内容在 LF 副本中格式检查全部通过。测试命令与运行边界无需独立 PR 文档承载。

## 评审与回滚

- Standards 评审发现关闭兼容测试只比较同一函数的两个输出，已改为用冻结案例锁定新旧路径的不同结果。
  临时把旧检索器换成 BM25 时，显式关闭测试会失败；当前另有配置默认值与缺省键的正向召回测试。
- Spec 评审发现关闭开关仍读取无效权重，已先写失败测试再修正。显式 false 下 NaN、inf、字符串、None 均不影响旧路径。
- 当前没有未解决的两轴评审发现；默认开启变更使用同一公开 build_block 接缝先失败再通过。
  复核分别把 schema 默认值和运行时缺键回退临时改回 false，新测试各独立失败一次，能捕获两种回归。
- 独立验收仅五题，仍有三题漏召、95% 候选噪声，不能据此推断真实聊天整体收益。
  零 bigram 重合的语义题仍由 ISSUE-0001 跟踪。
- 默认开启会增加索引构建、重建和查询的 CPU/内存开销，staging 仍需核验真实规模。
  设 `bm25_enabled=false` 即回退；无需模型、数据库迁移或向量索引。合并后撤销用 `git revert -m 1 <merge-commit>`。

## 后续本地向量边界

本次不选择模型、不新增推理依赖、向量字段或索引，BM25 独立完成当前能力。
后续若立项：模型由用户预装，只读取本地路径；运行时不联网、不下载、不遥测、不加载远程代码或调用收费 API。
继续复用 Retriever 接口；语义分数不得填入 lexical，须另行明确分数契约与校准方式。
后续 Issue 需提供中文效果、模型许可证及哈希、CPU/内存/磁盘和查询延迟、索引失效与回滚实测，
并覆盖跨表述、实体混淆、否定/时序、无答案与跨会话边界；不依赖这项后续工作验收 BM25。

## GitHub 跟踪

PR：[NeverENG/SeekMemory #7](https://github.com/NeverENG/SeekMemory/pull/7)，
头分支 `CarolDestiny/SeekMemory:feat/issue-0024-bm25`，目标为 `NeverENG/SeekMemory:main`。
远端 CI 与分发构建此前返回 `action_required`、jobs=0，运行页显示等待维护者批准 fork 工作流；
本地通过不等同于远端 CI 通过。合并、staging 与部署尚待完成。
