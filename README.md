# SeekMemory
**A source-grounded memory system for companion AI.**  
记忆会沉淀，印象会生长，人格会留下。

<div align="center">
  <img src="https://img.shields.io/badge/version-0.3.1-blue">
  <img src="https://img.shields.io/badge/Python-3.10%2B-blue">
  <img src="https://img.shields.io/badge/AstrBot-4.x-green">
  <img src="https://img.shields.io/badge/license-MIT-lightgrey">
</div>

<p align="center">
  <a href="docs/ARCHITECTURE.md">Architecture</a> /
  <a href="https://github.com/NeverENG/SeekMemory/issues/4">BM25 issue</a> /
  <a href="#quick-start">Quick start</a> /
  <a href="https://github.com/NeverENG/SeekMemory/issues/4">GitHub</a>
</p>

SeekMemory 是为伴侣 AI 构建的长期记忆层。每一次对话都会生成可追踪的 **Source**，从中提炼出持久 **Artifact**。对话回合仅组装下一次回复所需的上下文。

## 她记得一个人

> 你：上周三在杭州的那场面试怎么样？  
> 她：你说离开前很紧张，回来后只说算了。那样听起来并不算是一个完整的结局。

聊天记录可以回放一句话，而记忆系统必须知道这句话属于哪个事件、涉及谁、蕴含哪种情感，以及此时提及是否安全。

## 她记得，也守得住

> **你**（私下）：最近遇到点不愉快的事，别在群里提。  
> **群友**：你最近忙什么呢？  
> **她**：她最近有点累，具体的事我不方便替她说。

| | 本人私聊 | 同组 | 其他组 | 第三方 |
|----------|---------------|------------|-------------|-------------|
| Private  | full          | silence    | silence     | silence     |
| Shared   | paraphrase    | full       | hint        | silence     |
| Shadow   | hint          | hint       | silence     | silence     |
| Secret   | silence       | silence    | silence     | silence     |

矩阵决定了她如何表达记忆。她是否记得，是由记忆本身决定的。敏感记忆可以塑造她的语气，却不至于变成群组八卦。  

温柔不是反复追问，是她记得什么、对谁记得、什么时候该停。

## 记忆会沉淀  
在 SeekMemory 中，一次对话会生成 **Fact**、**Scene**、**Impression**，并最终对 **Persona** 产生影响。  
```
Fact → Scene → Impression → Persona
```
Fact: 他在杭州工作；Scene：上周三他去了一次面试，回来时格外沉静；Impression：当他不确定时，总会随手调侃，让周围的人轻松；Persona：我注意到他总是把别人忽略的细节捕捉下来，细心而又不张扬。

- **Fact**：稳定且不衰退。  
- **Scene**：随时间逐渐褪色。  
- **Impression**：受后续对话影响，持续修订。  
- **Persona**：来源于长期稳定的 **Impression**，逐步凝练。  

## 她只想起此刻需要的那一页  
长聊天历史往往不适合作为直接提示。系统会对每个候选 **Artifact** 进行以下评分：  

1. 字面重叠  
2. 关联标签  
3. 情绪匹配  
4. 激活程度  
5. 近期性  
6. 认知强度  

随后，一个“证据门”剔除与当前上下文无实质关联的记忆。剩余记忆按字节预算及层级顺序排列：  
**Persona → Impression → Scene → Detail → Fact → Example**。  

当预算紧张时，**Example** 与 **Fact** 先被压缩；**Persona** 及当前角色 **Impression** 作为核心信息，保留时间最长，保证对话连贯性。  

## 语料长成她  
SeekMemory 的核心差异在于：个人形象来自持续增长与更新的语料库。其过程可拆解为  

1. **Capture**：通过自然语言交互捕获原始信息。  
2. **Extraction**：从原始内容提炼 **Fact**、**Scene** 等结构。  
3. **Recall**：按字节预算检索与当前任务最相关的 **Artifact**。  
4. **Reinforcement**：在后续交互中强化重要的 **Impression** 与 **Persona**。  
5. **Revision**：根据新输入动态调整先前的 **Impression**。  
6. **Forgetting**：对不再重要的短期 **Scene** 与 **Detail** 进行消散。  
7. **Persona Distillation**：从已稳定的 **Impression** 里提炼出一个可持续交互的 **Persona**。  

这些循环持续了几个月，让你感觉她就像同一个人。

## 工程基础

- **Source** 是不可变、追加式的，并保留用户和助手的所有消息；  
- **Artifact** 是带版本的解释；  
- 每一次生产写操作都使用 compare-and-set 提交，配合证据链接和账本条目；  
- **SQLite** 是第一个存储，存储库端口后可切换到 PostgreSQL；LLM 调用在 **ChatModel** 后执行，永不在数据库事务中运行。

## 评测

| 细节 | 结果 |
|------|------|
| **设定** | 六组人设 |
| **周期** | 180 天 |
| **对话量** | 31 926 条 |
| **问题数** | 60 题 |
| **记忆命中率** | 49/60 |
| **人类相似度** | 4.27 |
| **关键字基准** | 42/60 |
| **全上下文注入** | 24/60 |
| **等价 token 成本** | 约 1/7 |
| **规模跑（8 位用户, 60 天, 2400 记忆）** | 13 注入字符/轮，232 倍压缩，5/6 召回 |

100/100 **固定评测集** 已饱和，下一批基准需加入时间撤回、冲突解决与跨会话归因机制。

---

<a id="quick-start"></a>
## 快速开始  

```bash
git clone https://github.com/NeverENG/SeekMemory.git AstrBot/data/plugins/astrbot_plugin_seekmemory
```

重启 AstrBot，设置 `owner_umo` 并保持 `observe_groups = true`。  

插件数据目录中的运行时文件：

- `memory.db`  
- `pending.json`  
- `calls.jsonl`

---

## WebUI

SeekMemory 附带了一个供管理员使用的 AstrBot 插件视图。它显示了记忆是如何形成和更改的，支持通过预期版本检查进行手动修订，支持维护任务，并预览召回披露。视图使用宿主认证；它不会更改机器人访问规则。有关完整指南，请参阅 [WebUI 使用说明](docs/webui/README.md)。

## 当前状态与后续计划

- **版本 0.3.1** 正在生产环境使用。  
- 正在捕获群聊和私聊的 Source；提取产生共享和私有的 Artifact；匹配查询选择实时记忆并应用披露。
- 未来工作聚焦：  
  - BM25 与混合检索（参见 issue #4）。  
  - 人设 Source 策略。  
  - 反思功能实现。  
  - RBAC；容量治理已建立 Source-backed pending、Governor 和生命周期基线。
  - 延长记忆质量基准。

---

## 贡献

在打开 P0/P1 问题或拉取请求之前，请阅读 AGENTS.md。本地问题历史记录位于 `docs/issues` 中。存储库中提供了 GitHub 问题和 PR 模板。

- 架构：docs/ARCHITECTURE.md
- 契约：docs/CONTRACT.md
- BM25 进展与验收：[Issue #4](https://github.com/NeverENG/SeekMemory/issues/4)
- 贡献指南：CONTRIBUTING.md

---

## 许可证

本项目采用 **MIT** 或 **Apache‑2.0** 许可证发布。
