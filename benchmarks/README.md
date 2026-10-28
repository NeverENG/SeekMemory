# Benchmark

用一个模拟用户的 30 天样本，观察检索命中、留存率和注入字数。以下是离线合成数据的测量，不代表真实模型质量或线上费用。

## 怎么跑

```bash
python3 benchmarks/run.py          # 生成 benchmarks/results/latest.md
```

该入口不需要网络、AstrBot 或模型。样本内容固定，但日期和编号使用系统时钟，耗时依赖机器；完整报告不保证每次完全一致。

## 验证范围与限制

- `run.py` 组合 core、召回和存储代码，不是覆盖全部 core 能力的独立跑分，也不验证真实模型抽取质量。
- “强化有效性”来自按样本提及次数预设的权重差异，没有调用实际 `core.strength.reinforce`。它只表示样本权重比，不能证明生产强化逻辑有效。
- 没有期望答案的查询不计入旧命中率和共用对照的候选噪声；这两项分数不能反映这些查询的误召回。
- 旧“综合像人指数”是自定义加权分数，不是人格质量标准。`run.py` 生成报告，没有质量退化的失败门槛；CI 中该步骤成功不等于记忆增强或质量无退化。BM25 的冻结验收另见下文。
- 旧报告中的“Token”栏目实际用 `len()` 统计字数，没有测量模型 token 数或费用。生成报告仍保留旧标题，应按这里说明的实际口径阅读。

core 的测试入口及证据范围见[模块文档](../docs/zh/architecture/modules/core.md#core-verification)。比较版本时记录提交、样本、配置、命令和具体指标；性能数字同时记录运行环境。固定计数、耗时和真实模型效果应分别判断。

## Runtime load/soak

```bash
python3 benchmarks/runtime_load.py
```

固定时钟跨一小时模拟 1,000 个会话和 10,000 条事件；运行生产 `AgentRuntime` 决策、`RuntimeWorker` 并发/去重路径、主动策略有界 fan-out，以及 SQLite action ledger 的重复回调、重启和保留清理。模型和发送端都使用 fake port，不访问网络或模型。脚本验证队列深度、派发上限、重复回调去重、唯一终态和并发上限，并输出 p50/p95 决策延迟、派发计数、去重计数和峰值内存。耗时和内存值受运行机器影响，计数断言保持确定。

## 数据

`dataset.py` 手写 19 条事件，覆盖：

- 稳定事实（名字、职业、目标）
- 早期琐事（第 3~5 天，**应该被忘掉**）
- 情绪低潮（第 12~16 天）
- 秘密、媒体分享
- 近期高光
- 沉淀出的两条印象

配套 8 个查询，每条标注了"应该命中哪几条记忆"和"应该命中哪一层"。

## 指标

| 指标 | 怎么算 | 说明 |
|---|---|---|
| **召回命中率** | 可答题中，选中记忆文本至少包含一个期望片段的题目比例 | 不要求全部期望命中，也不检查该片段最终进入上下文 |
| **层级命中率** | 指定层级的题目中，选中列表包含该层级记忆的比例 | 不要求该条记忆同时命中期望内容 |
| **叙述化比例** | 非空注入文本中不含指定列表符号的比例 | 格式检查，不代表回复或人格像人 |
| **字数压缩比** | 全量样本文本字数 ÷ 平均实际注入字数 | 未使用模型分词器，不是 token 或费用比例 |
| **样本留存判定** | 第 30 天，重要样本留存率大于 0.3、琐事小于 0.3 的计数 | 调用实际 retention，不执行维护遗忘流程 |
| **样本权重比** | 多次提及与极少提及样本的平均预设权重之比 | 未执行实际强化函数 |

## 规模测试

固定 8 条注入上限，记忆量从 50 涨到 1000，看注入字数怎么变：

以下为已有报告的规模示例；当前结果以重新运行生成的报告为准。

| 记忆条数 | 朴素全量 | SeekMemory | 压缩比 |
|---|---|---|---|
| 50 | 674 字 | 161 字 | 4× |
| 200 | 2821 字 | 147 字 | 19× |
| 500 | 7145 字 | 147 字 | 49× |
| 1000 | 14452 字 | 147 字 | **98×** |

该示例说明固定条数和预算下，注入字数可以保持有界；不代表检索耗时、内存或实际模型费用不变。

## 结果

最新一次：`benchmarks/results/latest.md`

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
