# Benchmark

离线合成数据用于比较代码行为，不代表真实模型质量、人格效果或线上费用。

## 固定记忆回归

```bash
python benchmarks/run.py
python benchmarks/run.py --repo /path/to/target --baseline benchmarks/data/memory_baseline.json
```

入口不访问网络或模型。每次生成独立的 `.tmp/benchmarks/<运行编号>/memory.json` 与 `memory.md`；不覆盖历史 `results/latest.md`。JSON 的 `acceptance.passed` 与退出码共同表示验收，失败返回非零，CI 使用同一入口。

固定 19 个事件和 8 个查询（原 `dataset.py` 标注不变），日期固定为 2026-10-30，样本编号、种子、条数和预算固定；秘密样本按实际 secret 类别建模。时钟仅在离线评测期间临时控制，生产时间逻辑不变。每个进程只加载一个生产代码版本，报告包含代码提交及源码指纹、评测器提交及指纹、语料指纹、配置和环境；脏工作区单独标明。计数保持确定，耗时受机器影响。

| 职责 | 归属 |
|---|---|
| 事件和查询标注 | `dataset.py` |
| 固定日期、编号及样本构造 | `memory_corpus.py` |
| 隔离目标版本和评测时钟 | `memory_target.py` |
| 检索组件、完整管线、隐私正反例及规模执行 | `memory_execution.py` |
| 纯指标和退化判定 | `memory_metrics.py` |
| 版本指纹及聚合报告 | `memory_reporting.py` |
| 参数、文件输出及退出码 | `run.py` |

## 指标与验收

| 指标 | 实际测量 |
|---|---|
| 候选命中 | 可答题选中内容包含期望片段；不代表已注入 |
| 最终上下文命中 | 实际组装文本包含期望片段；仍不证明模型正确使用 |
| 无答案题误召回 | 分别统计选中候选、上下文非空的题目数 |
| 候选噪声 | 不含金标片段的选中项；无答案题全部选中项计入噪声 |
| 字数 | Python 字符数，不是分词器 token 数或费用 |
| 留存样本 | 调用实际 retention；不执行夜间维护流程 |
| 样本预设权重比 | 根据 importance/mentions 预设权重的比例，不调用强化函数 |
| 隐私及正常披露对照 | 完整生产召回管线验证秘密、影子、跨会话固定印象、未可信人格、其他人的指定记忆，以及同会话正常给出的正例；禁止 Source 正文注入 |

图/BM25 组件测量不包含完整披露；`full_pipeline` 才经过完整读取、披露及组装。旧“综合像人指数”保留在历史报告中，不再作为验收指标。

使用同一修正评测器比较卫生前 `4e14e98` 与目标代码。逐题候选/最终期望片段命中及层级计数不下降，无答案误召回和候选噪声数量/比例不增加，留存计数及样本权重比不变，隐私和正常披露正例全部通过，不扩大原条数和字符预算。冻结基线保存于 `data/memory_baseline.json`；存在的旧误召回仍会如实报告，通过仅表示没有相对退化。

基线是显式版本化产物；需要更新评测方法时，用同一新评测器重跑原代码并生成新的基线文件，不得用目标代码的结果降低门槛。新文件可用：

```bash
python benchmarks/run.py --repo /path/to/exported-4e14e98 --revision <full-commit> \
  --record-baseline /new/path/baseline.json
```

已有基线和运行输出目录拒绝覆盖。运行时性能只作环境相关描述。core 的验证对应表见[模块文档](../docs/zh/architecture/modules/core.md#core-verification)。

## Runtime load/soak

```bash
python3 benchmarks/runtime_load.py
```

固定时钟跨一小时模拟 1,000 个会话和 10,000 条事件；运行生产 `AgentRuntime` 决策、`RuntimeWorker` 并发/去重路径、主动策略有界 fan-out，以及 SQLite action ledger 的重复回调、重启和保留清理。模型和发送端都使用 fake port，不访问网络或模型。脚本验证队列深度、派发上限、重复回调去重、唯一终态和并发上限，并输出 p50/p95 决策延迟、派发计数、去重计数和峰值内存。耗时和内存值受运行机器影响，计数断言保持确定。

## BM25 对照与冻结验收

`run.py`、`scale.py` 和 `ablation.py` 均实际运行图检索/BM25 两条路径，
比较命中、候选或字数加权噪声、注入长度和耗时；不同噪声口径在报告中标明。
这些组件基准不替代完整管线的 scope/disclosure 集成测试。

```bash
python benchmarks/bm25.py --calibrate --sizes --output benchmarks/results/bm25.json
```

校准仅使用原黄金集及 `bm25_cases.py` 的首五题；末五题曾被探索过，不称作 holdout。
`bm25_holdout.py` 是独立代理在未看输出时冻结的五题验收集；先确定参数再运行，
不得为提高结果而改金标或使用验收题调参。当前冻结 C=8、weight=1；
CI 会检查原黄金题逐题不回退、噪声不增加、独立集命中提升及无证据/语义边界。
`--sizes` 另外测量 5k/20k 文档索引开销；性能数字与机器有关，需与召回收益一起阅读。

## Dream 分诊 tradeoff 评估（ISSUE-0035）

冻结 40 个合成主题（事实、bot 行为、低价值闲聊、积压），在隔离的内存 SQLite 上跑生产
`DreamCycle -> IngestService.flush` 路径，用确定性 fake provider 返回按 Source id 索引的
预记录抽取结果；不访问网络、不提交真实聊天正文。`IngestService` 仍是唯一 Artifact 写入者。

```bash
python benchmarks/dream_eval.py --repo . --label current \
  --output benchmarks/results/dream_tradeoff_current.json

python benchmarks/dream_tradeoff.py \
  --target cc814ce=/path/to/cc814ce \
  --target d9fc248=/path/to/d9fc248 \
  --target current=. \
  --output-json benchmarks/results/dream_tradeoff.json \
  --output-md benchmarks/results/dream_tradeoff.md
```

> **注意：以下结果是合成语料 + fake provider 的评测结果，不是线上生产指标，也不能当作真实模型质量或线上成本。**

当前结果（合成语料，非真实用户）：调用 40→8（-80.0%），token 68,199→18,523（-72.8%），
重要事实召回 23/23→15/23（65.2%），bot 行为覆盖 8/8→7/8，自我印象覆盖 1/1→0/1，
pending 0→17（其中 9 个标注为重要），3 晚模拟每晚线性增长 8 个主题。按预注册阈值判为
`NOT_ACCEPTED`：成本与去噪改善，但重要事实召回和自我印象覆盖未达标，且 pending 无界。
详见 `results/dream_tradeoff.md`。该评估不修改分诊算法，也不替代真实模型/宿主验收。

### 生成结果政策

- **规范文件**：`results/dream_tradeoff.md`（人类可读报告）、`results/dream_tradeoff.json`
  （聚合结果）、`results/dream_tradeoff_cc814ce.json` / `_d9fc248.json`（历史基线）、
  `results/dream_tradeoff_current.json`（当前树快照）。报告和聚合都从三份目标快照派生，
  不要手改报告。
- **只有 current 预期变化**：相关代码变化后重新生成 `dream_tradeoff_current.json`；
  `cc814ce` / `d9fc248` 是审计历史，不静默覆盖。若必须重录，新增带日期/版本后缀的文件并说明原因。
- **重新生成**：
  ```bash
  python benchmarks/dream_eval.py --repo . --label current \
    --output benchmarks/results/dream_tradeoff_current.json

  python benchmarks/dream_tradeoff.py \
    --input cc814ce=benchmarks/results/dream_tradeoff_cc814ce.json \
    --input d9fc248=benchmarks/results/dream_tradeoff_d9fc248.json \
    --input current=benchmarks/results/dream_tradeoff_current.json \
    --baseline cc814ce --target-label d9fc248 \
    --output-json benchmarks/results/dream_tradeoff.json \
    --output-md benchmarks/results/dream_tradeoff.md
  ```
- **平台元数据**：`environment.platform=win32` 是生成已提交快照的机器来源，不是跨平台断言；
  harness 使用内存 SQLite、固定时钟和确定性 provider，CI 在 Linux 上应复现相同计数。
- 详细政策见 [`results/README.md`](results/README.md)。
