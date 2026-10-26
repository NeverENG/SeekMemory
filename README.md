# SeekMemory

**给长期相处的 AI 一份可追溯的记忆。**

记忆不是把聊天记录重新粘贴回提示词。
它应当知道一句话从何而来、关于谁、何时为真，
以及此刻说出来是否合适。

<div align="center">
  <img src="https://img.shields.io/badge/version-0.4.1-blue">
  <img src="https://img.shields.io/badge/Python-3.10%2B-blue">
  <img src="https://img.shields.io/badge/AstrBot-4.x-green">
  <img src="https://img.shields.io/badge/license-MIT-lightgrey">
</div>

<p align="center">
  <a href="docs/zh/architecture/overview.md">架构</a> /
  <a href="docs/zh/index.md">文档</a> /
  <a href="docs/en/index.md">English</a> /
  <a href="#quick-start">快速开始</a> /
  <a href="https://github.com/NeverENG/SeekMemory">GitHub</a>
</p>

---

## 一个长期相处的记忆产品

SeekMemory 是 AstrBot 的长期记忆插件。

它不会把完整对话历史重新放入每一次提示词。
它把对话存储为不可变的 **Sources**，派生出带版本的 **Artifacts**，
并且只返回当前轮所需的一小部分记忆。

有三项属性始终保持稳定：

- 它记得住：事实、场景与印象可以跨对话延续。
- 它只说合适的量：同一段记忆在不同语境下可以有不同的披露方式。
- 它可以变化：新证据会修订旧结论，同时旧修订仍可审计。

> 你：今天开会时我还是很紧张。
> 她：你上次也这么说。真开始之后，其实没那么难。
> 那场面试之后，你只说了句“随便”。

---

## 它记得一个人

记忆有分层，但这些层并不会全部灌入上下文。

```text
Fact -> Scene -> Impression -> Persona
```

- **Fact**：稳定的事实，例如“他在杭州工作”。
- **Scene**：带有时间边界的事件，例如“上周三面试之后，他沉默了很久”。
- **Impression**：在多次互动中形成的模式，例如“当他拿不准时，会把这件事变成玩笑”。
- **Persona**：只从稳定的自我印象中提炼，并由助手行为证据支撑。

Persona 不是手写的面具。
它从真实行为中生长出来，具有稳定的 ID、递增的 revision，以及可追溯的证据链。

---

## 全局记忆，语境敏感的表达

记忆可以跨私聊与群聊参与召回。
来源会话仍保留在证据链中，但它不再决定一段记忆能否被记住。

变化的是它如何被表达：

```text
high context affinity + high subject fit -> full text
medium relevance -> paraphrase
weak relevance -> hint
unsafe to express -> silence
```

披露是一个连续得分，而不是一组硬编码的 if 判断：

```text
exposure =
  context_affinity
  * subject_fit
  * scope_prior
  * relevance
  * (1 - sensitivity)
```

一段私密记忆可以影响她如何理解当前话题，而不必被逐字引用给所有人。

`secret` 记录永远不会进入候选池。
`designated` 记录保留其明确的私密投递协议。
其余记录均可全局检索，并由披露得分决定说出多少。

---

## 它只召回此刻需要的那一页

长上下文不是长期记忆。

SeekMemory 生成候选，激活记忆图，并在本地执行词法检索，
然后组装一个有边界的块：

```text
Persona -> Impression -> Scene -> Detail -> Fact -> Example
```

重要的层保留更久；短生命周期细节更早离开。
召回不会增加模型调用，也不会重放整段历史。

---

## 记忆会沉淀，也可以被修订

一段对话会经历以下步骤：

1. **Capture**：保留不可变的用户与助手 Sources；双方都进入抽取流程。
2. **Extraction**：派生 Facts、Scenes、Impressions 以及可选的机器人行为。
3. **Recall**：按当前问题检索，而不是按倒序时间检索。
4. **Disclosure**：根据 subject、context、sensitivity 与 relevance 选择 full、paraphrase、hint 或 silence。
5. **Reinforcement**：实际被使用的记忆会留下记录。
6. **Revision**：新证据可以修订旧印象；旧版本仍可审计。
7. **Forgetting**：短生命周期细节在不再重要时淡出。
8. **Persona distillation**：稳定的自我印象会产生新的 persona revision。

这些循环可以持续运行数月，而不是只为了一轮对话去表演“像人一样”。

---

## WebUI + AgentHook：让记忆可检视

该插件提供一个由 AstrBot 宿主认证的管理视图。
它不会改变普通用户被允许看到的内容。

该视图展示：

- 活跃记忆、修订历史、来源证据与 ledger 状态
- persona 修订、derived-from 关系与证据链接
- 召回预览：候选、最终注入、披露级别与被保留未披露的记忆
- 生命周期日志、任务状态与容量指标
- **Agent Run Trace**：从入站消息到模型请求、工具调用与投递的时间线
- 记忆详情抽屉：打开任意 trace ID 背后的 artifact

Run Trace 仅存储结构化元数据：

```text
run -> request -> tool -> response -> delivery
```

它不存储聊天文本、模型回答、工具参数或工具结果。
它回答的是运维问题：这段记忆是没有被召回、被披露策略扣留，还是单纯没有被模型使用？

---

## 工程基础

- **Source 不可变**：原始用户与助手轮次是真相层。
- **Artifact 带版本**：每次写入都携带 revision、lineage、evidence 与一条 ledger entry。
- **CAS 提交**：生产写入使用 compare-and-set，避免覆盖更新的 revision。
- **原子批次**：merge、lifecycle 与 persona promotion 在一个事务中完成。
- **检索与生成分离**：召回从不调用模型；模型调用从不在数据库事务内运行。
- **Fail-open runtime**：extraction、写入与 run traces 不会阻塞正常回复。
- **适配器边界**：AstrBot 是宿主；agent runtime 与 memory kernel 保持可测试。

---

## 基准测试

评估分为两组：拟人度与成本。

### 固定长对话基准

```text
19 simulated events / 8 queries / 30 days
Fixed data, reproducible, no model calls
```

| 指标 | 结果 |
|---|---:|
| 像人指数 | **100 / 100** |
| 分层命中率 | **100%** |
| 叙事率 | **100%** |
| 遗忘正确性 | **15 / 15** |
| 强化有效性 | **2.1x** |
| 召回命中率 | **100%** |

### Token 成本

| 记忆数量 | 朴素完整上下文 | SeekMemory | 压缩比 |
|---:|---:|---:|---:|
| 50 | 674 chars/turn | 17 chars/turn | **40x** |
| 200 | 2,821 chars/turn | 17 chars/turn | **166x** |
| 500 | 7,145 chars/turn | 17 chars/turn | **420x** |
| 1,000 | 14,452 chars/turn | 17 chars/turn | **850x** |

每轮额外模型调用：**0**。

### Dream 分诊 tradeoff

**注意：以下为合成语料 + fake provider 的评测结果，不是线上生产指标；仅用于衡量调用/token 与记忆覆盖的 tradeoff。**

冻结 40 个合成主题，跑生产 `DreamCycle -> IngestService.flush` 路径并对比优化前后：

| 指标 | cc814ce | d9fc248 |
|---|---:|---:|
| 抽取调用 | 40 | 8 |
| token | 68,199 | 18,523 |
| 重要事实召回 | 23/23 | 15/23 |
| bot 行为覆盖 | 8/8 | 7/8 |
| 自我印象覆盖 | 1/1 | 0/1 |
| pending 主题 | 0 | 17 |

按预注册阈值判为 `NOT_ACCEPTED`：调用/token 下降显著，但重要事实召回与自我印象覆盖未达标，
pending 每晚线性增长。数据集快照、命令、限制和建议详见
[dream_tradeoff.md](benchmarks/results/dream_tradeoff.md)；生成结果政策见
[benchmarks/results/README.md](benchmarks/results/README.md)。

### 大型群聊模拟

```text
8 users / 60 days / 2,400 messages
```

| 方法 | 每轮注入 | 召回 | 检索时间 |
|---|---:|---:|---:|
| 朴素完整上下文 | 3,012 chars | 6/6 | 0.11 ms |
| 滑动窗口（20） | 191 chars | 2/6 | 0.01 ms |
| 关键词匹配 | 66 chars | 2/6 | 0.08 ms |
| 伪向量 top-8 | 53 chars | 5/6 | 0.40 ms |
| 近期摘要（7d） | 285 chars | 3/6 | <0.01 ms |
| **SeekMemory** | **13 chars** | **5/6** | **2.40 ms** |

跨范围检查：

```text
my recall includes another user's shadow: 0
another user's recall includes my private: 0
```

### 如何读这组数字

它们衡量的是：

- 记忆是否能在固定语料上被正确检索
- 随着记忆增长，注入大小是否保持平稳
- 预算与披露是否让原始文本留在正确的位置
- 召回是否增加模型成本

它们不衡量：

- 开放域模型中的长时程推理
- 共享多用户 bot 的授权策略
- 所有自然语言矛盾或撤回
- 数月生产流量下的存储与并发成本

---

## 快速开始

```bash
git clone https://github.com/NeverENG/SeekMemory.git \
  AstrBot/data/plugins/astrbot_plugin_seekmemory
```

重启 AstrBot，并至少配置：

```text
owner_umo
observe_groups
```

To enable the single-node AgentRuntime, set:

```text
runtime_gate_enabled: true
runtime_wait_seconds: 5
runtime_tick_seconds: 5
```

插件数据目录中的运行时文件：

```text
memory.db
runtime_state.json      # fallback path
runtime_episodes.jsonl  # fallback path
run_traces.jsonl
```

SQLite 是主存储。运行时文件与 trace 文件支撑运行时状态和管理视图。

---

## 当前版本

```text
version: 0.4.1
```

当前主线包括：

- Source / Artifact / revision / evidence / ledger
- 带因子化披露的全局记忆
- 由行为证据支撑的稳定 persona 修订
- Agent Run Trace 与 WebUI 时间线
- 私聊回复、@ 优先、ambient group wait
- 延迟回复的有界重试
- 请求前工具过滤
- 持久化的单节点运行时状态

已知边界：

- 多实例幂等性尚未实现（issue #48）
- 主动决策会被记录，但不会发送
- 延迟回复不会运行完整的 AstrBot 工具循环
- Run Trace 是单进程 JSONL 存储
- 真实 AstrBot 端到端 hook 测试仍需扩充

---

## 文档

- [中文文档](docs/zh/index.md) / [English documentation](docs/en/index.md)
- [架构总览](docs/zh/architecture/overview.md)
- [开发环境与验证](docs/zh/guides/development.md)
- [管理界面操作](docs/zh/guides/webui.md)
- [贡献指南](CONTRIBUTING.md)
- [Issues](https://github.com/NeverENG/SeekMemory/issues) / [Pull Requests](https://github.com/NeverENG/SeekMemory/pulls)

## 许可证

MIT 或 Apache-2.0。
