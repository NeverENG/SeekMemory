# 开源 AI 记忆系统横向对比

> 调研时间：2026-10-21 · 数据来自 GitHub API 与各项目 README（少数条目读了源码/官方文档，逐条标注）

**数据口径**：Star、语言、License、最近提交均取自 `api.github.com/repos/<owner>/<repo>`，时间为 2026-10-21 02:12–02:20（Asia/Shanghai）。「最近提交」是 `pushed_at`，包含非默认分支的 push，不等于默认分支最后一次 commit。机制描述以 README 为准；README 没写清的，读了仓库源码或官方文档，并注明。凡是没有一手依据的，写「未验证」，不猜。

## 一句话结论

- **要"记住用户说过的事实"**：Mem0 最省事，生态最全，代价是冷、没有人格、每次写入都要调模型。
- **要"某件事什么时候为真、什么时候被推翻"**：Graphiti/Zep 的双时间图谱是这批里唯一做对的，代价是要养一个图数据库 + 搜索引擎。
- **要"agent 自己整理记忆、可审计可回滚"**：Letta 的 MemFS（git + Markdown）或 PowerContext 的 Source/Artifact + revision。
- **要"陪伴养成"**：MemoryOS 在学术上最接近（分层 + heat 淘汰 + 用户画像），AstrBot 生态里 memory_companion / iris_chat_memory / angel_memory 已经把"分层 + 衰减 + 画像 + 权限"做成了插件。
- **SeekMemory 的位置**：在本次调研范围内，它是唯一一个把「艾宾浩斯遗忘曲线 + 四层沉淀 + 按 scope 分人的印象 + 每轮零模型调用的预算组装」塞进**纯标准库 + 单文件 SQLite** 的插件。它的强项是"像人"和"零边际成本"，短板是没有语义检索、没有多模态、只能单机，而且基准是自建的、规模很小。

一句话：**别人做的是"记忆基础设施"，SeekMemory 做的是"记忆的人格后果"。**

## 项目概览

| 项目 | Star | 语言 | 最近提交 | 许可 | 存储 | 一句话定位 |
|---|---:|---|---|---|---|---|
| [Letta](https://github.com/letta-ai/letta)（原 MemGPT） | 25,206 | 空（旧版 Python，新版 TS） | 2026-10-18 | Apache-2.0 | 旧版 Postgres/SQLite + 向量库；新版 git + Markdown | agent 自己编辑记忆的"有状态 agent 平台" |
| [Mem0](https://github.com/mem0ai/mem0) | 67,527 | Python | 2026-10-20 | Apache-2.0 | Qdrant 默认 + SQLite 历史，20+ 向量库适配 | 给 agent 用的记忆层 SDK / 服务 |
| [Graphiti](https://github.com/getzep/graphiti)（Zep 开源内核） | 32,085 | Python | 2026-10-20 | Apache-2.0 | Neo4j / FalkorDB / Neptune + OpenSearch | 双时间知识图谱，事实带有效期 |
| [A-MEM](https://github.com/agiresearch/A-MEM) | 1,204 | Python | 2025-12-12 | MIT | ChromaDB | Zettelkasten 式自演化笔记网络 |
| [MemoryOS](https://github.com/BAI-LAB/MemoryOS) | 1,608 | Python | 2026-07-07 | Apache-2.0 | 本地 JSON + embedding（另有 ChromaDB 分支） | 仿操作系统分层的短/中/长期人格记忆 |
| [langmem](https://github.com/langchain-ai/langmem) | 1,715 | Python | 2026-10-02 | MIT | LangGraph BaseStore（内存/Postgres/任意） | 记忆原语 + prompt 优化器 |
| [cognee](https://github.com/topoteretes/cognee) | 32,591 | Python | 2026-10-20 | Apache-2.0 | Kuzu 图 + LanceDB 向量 + SQLite | 文档/代码 → 知识图谱的记忆管线 |
| [PowerContext](https://github.com/oceanbase/powercontext) | 1,351 | Python | 2026-10-20 | Apache-2.0 | SQLite / 内嵌 seekdb | 工作上下文服务，Source/Artifact + revision |
| **SeekMemory**（本仓库） | 1 | Python | 2026-10-20 | MIT | 单文件 SQLite | 给 IM bot 的分层记忆 + 人格养成 |

AstrBot 生态（同平台，单独列，因为它们才是 SeekMemory 的直接竞品）：

| 插件 | Star | 最近提交 | 许可 | 存储 | 一句话定位 |
|---|---:|---|---|---|---|
| [self_learning](https://github.com/NickCharlie/astrbot_plugin_self_learning) | 419 | 2026-10-20 | AGPL-3.0 | PostgreSQL 默认，SQLite/MySQL 可选 | 对话风格/黑话学习 + 人格演化审查 + 社交关系 |
| [angel_memory](https://github.com/kawayiYokami/astrbot_plugin_angel_memory) | 189 | 2026-09-15 | GPLv3（API 报 NOASSERTION） | SQLite + Tantivy 索引 | 三层认知 + 灵魂能量槽 + 睡眠巩固 |
| [persistent-memory](https://github.com/zhanzhao2/astrbot-plugin-persistent-memory) | 87 | 2026-03-07 | MIT | LanceDB | 向量 + BM25 混合检索的持久记忆 |
| [self_evolution](https://github.com/Renyus/astrbot_plugin_self_evolution) | 81 | 2026-05-06 | 未标注（API NOASSERTION） | SQLite | 人格状态模拟（能量/心情/社交需求）+ 长期记忆 |
| [memory_companion](https://github.com/menglimi/astrbot_plugin_memory_companion) | 53 | 2026-10-11 | 无 | SQLite | 陪伴向记忆中枢：核心记忆 + 断言 + RRF/MMR + 权限 |
| [iris_chat_memory](https://github.com/leafliber/astrbot_plugin_iris_chat_memory) | 21 | 2026-09-12 | AGPL-3.0 | FAISS + SQLite | 三层记忆 + 用户画像 + 知识图谱 |
| [simple_long_memory](https://github.com/piexian/astrbot_plugin_simple_long_memory) | 17 | 2026-09-15 | AGPL-3.0 | AstrBot 内置知识库（向量） | 最轻的"抽取-注入-过期"实现 |

## 机制对比

### 主流项目 + SeekMemory

| 项目 | 存储后端 | 记忆结构 | 检索方式 | 遗忘机制 | 人格支持 | 多用户隔离 | 时间建模 | Token 策略 | 依赖重量 | 适合陪伴养成？ |
|---|---|---|---|---|---|---|---|---|---|---|
| **Letta（旧版 MemGPT）** | Postgres/SQLite 元数据 + 向量库存 archival passages | 三块：core memory blocks（persona/human，常驻）、recall（消息历史）、archival（段落） | archival 向量检索 + agent 主动调用工具读写；分页由 agent 自己决定 | 无自动衰减。靠 agent 改写/删除 block 和文件；MemFS 的 git 历史保留一切 | **是**。`persona` 是独立 block/文件，与 `human` 分开 | 按 agent 隔离；agent 内多用户靠 block；cloud 有 shared memory | git 提交 = 版本；无 per-fact 有效期 | core/根目录文件常驻 system prompt（有大小上限）+ 子目录懒加载 + 可选检索 | 重（旧版要 server + DB + 向量库）；新版轻（文件 + 可选云） | 中。人格与自我叙事强，但没有遗忘和情绪；主线已转向编码 agent |
| **Mem0** | 默认 Qdrant（`qdrant-client` 是核心依赖），20+ 向量库适配器，SQLite `history.db` | 扁平条目：fact 字符串 + metadata + 实体链接；无层级 | 多信号融合：向量 + BM25 + 实体匹配并行打分；时间感知排序 | 新算法 ADD-only，不 UPDATE/DELETE，只累积；只有显式 delete；无衰减 | 无 | `user_id` / `agent_id` / `run_id` 过滤 | `created_at`/`updated_at` + 时间感知检索；OSS 无有效期 | 检索注入 top_k（官方 benchmark 约 6.7–7K tokens/次） | 中重（向量库 + embedding + 每次写入一次 LLM） | 低。事实召回强，但冷，不该拿它养人格 |
| **Graphiti** | Neo4j 5.26 / FalkorDB / Neptune + OpenSearch（全文+向量） | 时序知识图谱：实体节点 + 带有效期的事实边 + episode 溯源 + 社区 | 混合：语义 + BM25 + 图遍历 + rerank | 双时间失效：新事实取代旧事实时写 `invalid_at`，不是衰减；episode 不删 | 无 | `group_id` 分图 | **最强**：事件时间 + 摄入时间双时间，可查"某时刻为真" | 检索注入边/episode（带 rerank） | 重（图库 + 搜索引擎 + 每 episode 多次 LLM 调用） | 低。时间正确性最好，但单人聊天用它是杀鸡用牛刀 |
| **A-MEM** | ChromaDB | Zettelkasten 笔记：content + keywords + tags + context + links + `evolution_history` | 向量相似 + 沿 link 找邻居 | 无。evolution 会改写旧笔记的 context/tags，但不淘汰 | 无 | 无（单 collection `memories`），要自己分库 | 笔记时间戳；无有效期 | 检索注入 | 中（Chroma + embedding + 写入时 LLM 构建/演化笔记） | 低。研究原型，"新记忆改写旧记忆"值得看，缺隔离/衰减/人格 |
| **MemoryOS** | 本地 JSON 文件（`data_storage_path`）+ embedding；另有 ChromaDB 分支 | 三层：短期 QA（capacity 7）/ 中期 segment（带 heat）/ 长期 persona（user profile + user knowledge + assistant knowledge） | 三层各自召回：短期取最近、中期相似度 + heat、长期读 profile/knowledge | **有**。heat = 访问频率 + 交互长度 + 24h 时间衰减；中期容量满时 LFU 淘汰整个 session | **有**（长期 persona：用户画像 + 助手知识），但只是静态摘要、无版本 | 按 user/assistant 分目录 | heat 含 recency（τ=24h）；无有效期 | 注入检索到的 segment + profile，无硬预算 | 中（embedding 模型 + 可选 Chroma） | 中高。学术上最接近，但画像是摘要，没有"对某人的印象"分层，也没有情绪着色 |
| **langmem** | LangGraph BaseStore（InMemory / Postgres / 任意实现） | 扁平 KV，按 namespace 元组分区；prompt 优化产物另存 | `create_search_memory_tool` 语义检索，由 agent 决定何时查 | README/文档未提自动衰减；manage 工具可显式删改 | 弱。prompt optimizer 能改 system prompt，但人格不是被建模的数据 | **一等公民**：namespace 如 `("memories", user_id)` | 无 | 热路径检索注入或后台抽取；agentic 调用增加延迟 | 轻（库；需 LangGraph + store + embedding） | 低。是积木不是系统，衰减/人格/印象都得自己写 |
| **cognee** | 默认 Kuzu 图 + LanceDB 向量 + SQLite；1.0 起可全放 Postgres（demo） | 知识图谱（实体/关系）+ chunk + 自定义 ontology + session 蒸馏 | 图补全 + 向量 + 关键词（检索策略可选） | 有 `forget` API（删条目/数据集），手动；无衰减 | 无 | dataset + node_set，权限按 dataset | 时间戳；无有效期/版本链 | 检索注入 | 重（图 + 向量 + 抽取管线 + 模型） | 低。文档/知识库向 |
| **PowerContext** | SQLite（最简）或内嵌 seekdb；独立 Server | Scope 下：Source journal（只追加证据）+ Memory artifact（revisioned）+ Review Inbox + Handoff + Topic Memory | `PreparedContext` 按配置选段（active Memory / approved Experience / Profile / Topic Memory），共享字节预算；语义检索需配 embedding | 生命周期 `active/forgotten/merged/retired`；forgotten 退出召回但内容与历史可恢复；无衰减曲线 | 只有可选 Profile 快照；人格不是一等公民 | Scope 隔离；README 明确 scope id **不等于**身份/鉴权 | Artifact revision 链，可按 `@REVISION` 读历史快照；无有效期 | **显式有界**（PreparedContext 字节预算，"bounded, not dumped"） | 中重（Server + HTTP/MCP；SQLite 可单机） | 低。为工作交接设计，不哄人；但 Source/Artifact/预算这套契约最值得抄 |
| **SeekMemory** | 单文件 SQLite（blobs + ledger + nodes + edges + sources + evidence） | 四层 `fact → memory → impression → persona`；通用头 + family payload；三型边 `similar/causal/temporal` | 本地五维打分（字面 ×3.0 / 标签 ×2.0 / 情绪 ×1.5 / 权重 ×1.0 / 新鲜度 ×0.5）+ 激活扩散 + 10% 随机探索；**无向量** | **有**。`R = e^(−t/S)`，S 由显著度/命中/形状/情绪决定；<0.3 标 forgotten 不删，180 天无引用才物理清 | **是**。persona 全局唯一；impression 按 scope 每人一份 | scope（private/shared/shadow）+ RBAC（owner/trusted/guest/blocked） | 绝对时间戳 + `valid_from/valid_to` + revision/lineage + 哈希链 ledger | 预算组装（配置默认 600 字，README 基准 2000 字），每轮 **0 次**模型调用 | 极轻（纯标准库 + sqlite3） | **就是为这个场景写的** |

### AstrBot 生态插件

| 插件 | 存储后端 | 记忆结构 | 检索方式 | 遗忘机制 | 人格支持 | 多用户隔离 | 时间建模 | Token 策略 | 依赖重量 | 适合陪伴养成？ |
|---|---|---|---|---|---|---|---|---|---|---|
| **self_learning** | PostgreSQL 默认，SQLite/MySQL 可选 | RawMessage + 学习会话 + 风格 few-shot + 黑话 + 记忆图 + 知识图谱 + 社交关系 | 向量/图谱 + 审查后注入（`on_llm_request`） | 未在 README 说明自动衰减；有审查、拒绝、删除、回滚 | **强**。人格演化走"学习 → 审查 → 批准/回滚" | 按群/用户；权限与审查链路 | 时间戳；无有效期 | 注入社交/黑话/记忆/few-shot/临时人格增量 | 较重（默认 PG + embedding + 多模块） | 高。功能最全，但重、AGPL、配置复杂 |
| **angel_memory** | SQLite（`note_chunks.db`）+ Tantivy 索引 | 灵魂层（4 维能量槽）/ 潜意识（后台整理）/ 主意识（4 个 LLM 工具）；核心记忆 + 笔记分页 | BM25（Tantivy + CJK 1~2-gram），可选 embedding + rerank（RRF 融合） | 睡眠巩固"清理弱记忆"；`angel_remember` 标记的内容永不遗忘 | **强**。"灵魂层"用 4 个能量槽（回忆深度/印象深度/表达欲望/创造力）经 tanh 映射到检索条数、生成长度、温度 | `conversation_scope_map`：先按人格名，再按会话 ID，未命中归 public | 记忆状态通过"共鸣"影响当前决策；无有效期 | 按能量槽动态控制注入量 | 中（Python + Tantivy） | 高。和 SeekMemory 最像的竞品，工程成熟度更高 |
| **persistent-memory** | LanceDB | 扁平记忆条目 + metadata | 向量 ANN + BM25 FTS 融合 + Jina rerank；recency/importance/time decay 多重打分 | 有 time decay 打分，无物理淘汰 | 无 | scope：`global` / `session` / `session+global` | 时间衰减进打分 | 注入 `<relevant-memories>`，并用 `UNTRUSTED DATA` 包裹防注入 | 中（LanceDB + Jina API） | 中。标准 RAG 记忆，无人格沉淀 |
| **self_evolution** | SQLite | 人格状态机（energy/mood/social_need/satiety）+ Effect + 脑内待办 + 记忆延续 | 状态推演 + 记忆注入 | Effect 带 `decay_style` / `recovery_style`，按时间差衰减 | **强**（人格状态就是核心） | 按会话/群 | 时间差推演状态；无记忆有效期 | 注入人格叙事片段 + 记忆 | 轻（SQLite） | 高。但偏"情绪状态"，长期记忆是配角 |
| **memory_companion** | SQLite | 核心记忆（Label 常驻）+ 结构化原子（owner/persona/敏感级/耐久度/有效期/证据/强化分）+ 会话摘要 + 断言层 + Bot 自我时间线 | 多路召回 RRF 融合 + MMR 去重 + 可选 embedding/rerank；短 TTL 缓存按 revision 失效 | **有**。自然衰减 + 睡眠维护压缩/归档；TTL | **强**。记忆按 Bot/人格归属；另有独立的陪伴插件管人格状态 | **最强**。私聊/群聊/自我时间线/共享/内部记忆分边界 + 对象级权限拓扑 | 有效期 + 时间窗口意图 + 注入统计 | 字数预算内先核心记忆再动态记忆；Token 可观测 | 中重（SQLite + 可选向量/rerank，模块多） | **最高**。目前 AstrBot 里设计最完整的陪伴记忆中枢 |
| **iris_chat_memory** | FAISS（L2）+ SQLite（L3/画像） | 三层：L1 缓冲 / L2 语义记忆库 / L3 知识图谱；用户画像 + 群画像 | 向量检索 + 查询改写 + 图谱路径扩展 | **有**。遗忘评分 = 近因性衰减 + 访问频率 + 置信度；低分淘汰，图谱节点也淘汰 | 弱。有人格画像，但人格本身不沉淀 | 群聊按用户区分，互不干扰 | 时间衰减进遗忘评分 | Token 预算 + 每日解析配额 | 中（FAISS + embedding） | 高。功能覆盖广，深度不如 memory_companion |
| **simple_long_memory** | AstrBot 内置知识库（向量） | 扁平条目，user/group 两种归属 | 知识库向量检索 + 可选 rerank + LLM 提炼查询 | **有**。`memory_ttl_days` 默认 30 天 | 无 | `user_id` 隔离 + 群共享开关 | TTL | 每次最多注入 5 条 | 极轻（复用 AstrBot 知识库） | 中。够用，但没有"养成" |

## 逐项目点评

### Letta / MemGPT

**核心机制**：MemGPT 的原命题是"把上下文窗口当 RAM，把外部存储当磁盘，让 LLM 自己分页"。旧版实现是三块：`persona` / `human` 两个 core memory block 常驻 system prompt，recall memory 存消息历史，archival memory 存段落并用向量库检索；agent 通过函数调用自己往 block 里写、从 archival 里搜、把不重要的东西挪走。这就是"self-editing memory"。

**变化（重要）**：`letta-ai/letta` 这个 25.2k star 的仓库现在只是**旧版 V1 server**，README 明确说活跃开发已迁到 [`letta-ai/letta-code`](https://github.com/letta-ai/letta-code)（3,664 star，TypeScript，2026-10-20 仍在提交）。新版记忆不再是 block + 向量库，而是 **MemFS**：一个属于 agent 的 git 仓库，里面是带 YAML frontmatter 的 Markdown，根目录文件（`persona.md`、`human.md`）每轮进 system prompt，有 `MEMORY.md` 索引的子目录懒加载；agent 用普通文件工具读写，提交即版本，还有"dreaming"后台子 agent 做巩固、`/doctor` 审计记忆漂移。默认**没有**向量索引，语义检索要装 `memfs-search` mod + QMD。这部分来自官方文档，不是 README。

**强在哪**：人格（persona）与用户模型（human）从第一天就是分开的一等公民，这个设计比大多数"记忆库"清醒；memfs 用 git 解决版本、冲突、回滚，思路干净；agent 自主性最强。

**弱在哪**：没有遗忘。记忆只增不减，靠 agent 自觉和 `/doctor` 体检；没有情绪权重、没有"印象"这种模糊层。旧版部署重（server + Postgres + 向量库），新版又把重心放在编码 agent 上，IM 陪伴不是它的目标场景。

**陪伴适配**：中。适合"想要一个会自己记笔记、可审计的 agent"，不适合"想要一个会淡忘、会赌气、对每个人都有不同印象的 bot"。

### Mem0

**核心机制**：一次 `add()` 调一次 LLM 做事实抽取，把对话压成短 fact 字符串，带 `user_id/agent_id/run_id` 元数据写进向量库；检索时按这些维度过滤 + 向量召回。2026-04 的新算法改成 **ADD-only**——只加不改不删，配合实体链接（实体也 embed 并跨记忆关联）和多信号检索（语义 + BM25 + 实体匹配并行打分后融合），官方称 LoCoMo 92.5 / LongMemEval 94.4，单次检索约 6.7–7K tokens。

**强在哪**：工程完成度最高。`qdrant-client` 是硬依赖，另有 20+ 向量库适配器；`history.db` 用 SQLite 记操作历史；有 library / 自托管 server / 云三档；生态、文档、迁移工具都齐全。做产品要"记住用户偏好"，接它最快。

**弱在哪**：记忆是**扁平事实条目**，没有层级、没有抽象、没有"这个人整体给我的感觉"。ADD-only 意味着旧事实不会被新事实覆盖，只能靠检索时排序，冲突要靠时间感知去猜；每条写入一次 LLM，成本随对话量线性涨。人格完全不在模型里。OSS 的图记忆（Neo4j/Kuzu 等）有文档和 `examples/graph-db-demo`，但当前主代码树里没看到独立 graphs 模块，**开箱程度未验证**。

**陪伴适配**：低。它记的是"用户偏好"，不是"关系"。

### Graphiti / Zep

**核心机制**：把对话切成 episode 摄入，LLM 从中抽实体和关系，写成 `(Entity → Relationship → Entity)` 的三元组边，每条边带**双时间**：事件真正发生的时间（valid_at）和被系统摄入的时间；事实被推翻时不是删除，而是给旧边写 `invalid_at`。所以它能回答"她现在还住在杭州吗"和"去年十月她住哪"这两个不同问题。检索是语义 + BM25 + 图遍历的混合，再 rerank。

**强在哪**：时间建模是这批项目里唯一做到"可回溯到任意时刻"的；episode 保留原始证据，每个派生事实都能溯源；支持 Pydantic 定义 ontology（prescribed）或让它自己学。Zep 的商业版换了自研图引擎，开源版仍要 Neo4j/FalkorDB/Neptune + OpenSearch。

**弱在哪**：重。一个图数据库 + 一个搜索引擎 + 每 episode 多次 LLM 调用，个人 bot 跑这套不划算；没有"人格"概念，实体摘要只是描述；对模糊的、情绪化的、互相矛盾的日常絮叨，三元组建模会丢信息——"他那天看起来很累"很难变成一个干净的事实边。

**陪伴适配**：低（部署与成本），但**时间链的思想值得抄**。SeekMemory 的 `valid_from/valid_to` 只做到"有效期"，没做到"摄入时间 vs 事件时间"的分离。

### A-MEM

**核心机制**：Zettelkasten 式的自组织笔记。每条新记忆不是裸文本，而是一张卡片：content + keywords + tags + context + links + evolution_history。写入时 LLM 先生成卡片属性，再找若干个最近邻，然后由一个"evolution agent"决定：要不要连边、连到谁、要不要**改写邻居的 tags/context**。也就是说新记忆会反过来改变旧记忆的解释。存储用 ChromaDB，检索是向量相似 + 沿 link 扩展。

**强在哪**：把"记忆是重构的，不是录制的"这件事做成了机制，而不是口号；笔记之间的 link 让检索有一步联想；代码短，好读，适合当论文基线。

**弱在哪**：没有遗忘、没有多用户隔离（单 collection `memories`）、没有人格；每条记忆写入要两次 LLM（构建 + 演化），量大时成本不低；repo 最后提交是 2025-12，维护放缓。

**陪伴适配**：低到中。它的"演化"更接近知识整理，不是"印象变了"。

### MemoryOS

**核心机制**：照搬操作系统内存管理的分层。短期存 QA 对（capacity 默认 7），满了由 Updater 整理成中期 segment；segment 有 **heat**（访问次数 + 交互长度 + 24 小时 recency 衰减），heat 过阈值就把内容蒸到长期：用户画像（性格、兴趣、背景）+ 用户知识 + 助手知识。检索时三层一起召回。中期容量满时按 **LFU 淘汰整个 session**（源码 `mid_term.py` 的 `evict_lfu`），不是逐条淘汰。

**强在哪**：这是主流项目里唯一把"用户画像 + 助手知识"当长期层、把"淘汰"当一等机制的；EMNLP 2025 Oral，LoCoMo 上有公开数字；MCP server 可以直接接；还有 ChromaDB 分支。

**弱在哪**：画像是**一次性摘要**，没有版本、没有冲突处理，改口了就是覆盖；heat 只看访问频率和时长，不看情绪、不看内容形状；"用户画像"和"助手人格"是两份静态文本，不是"对某个人的印象"；代码偏研究原型（JSON 落盘、同步阻塞），工程化程度不如 Mem0。

**陪伴适配**：中高，学术上最接近。但它回答的是"怎么记住更多"，不是"怎么忘得像人"。

### langmem

**核心机制**：不提供系统，提供三样积木：(1) `create_manage_memory_tool` / `create_search_memory_tool`，让 agent 在对话中自己存/查，命名空间是 `("memories", user_id)` 这样的元组，存在 LangGraph 的 `BaseStore` 里；(2) 后台 memory manager，在对话外抽取、合并、更新；(3) prompt optimizer，用对话轨迹和反馈反过来改写 system prompt。

**强在哪**：抽象干净，和 LangGraph 生态无缝；namespace + BaseStore 的多租户模型是这批里最正统的；prompt 优化是别人没有的角度——它优化的是"行为"，不只是"知识"。

**弱在哪**：没有任何内建的遗忘、衰减、显著性、时间模型，这些全要自己写；检索质量完全取决于你选的 store 和 embedding；"人格"只是被优化的 prompt 文本，不是可查询、可演化、可追溯的数据。

**陪伴适配**：低（需要自己搭），但如果你的技术栈是 LangGraph，它是最省事的底座。

### cognee

**核心机制**：一条摄取管线：文档/代码/对话 → 切片 → LLM 抽实体关系 → 写图（默认 Kuzu）+ 向量（默认 LanceDB）+ 关系库（默认 SQLite）。对外四个操作：`remember`（存，带 session 时可只进会话）/ `recall`（检索，可自动路由或指定策略）/ `improve`（富化、吸收反馈、把会话知识并进图）/ `forget`（删条目或数据集）；支持自定义 ontology 和 Pydantic 数据模型。1.0 之后可以把整套塞进一个 Postgres（官方标注 graph-on-Postgres 仍是 demo，生产版要授权）。

**强在哪**：文档和代码的图谱化最成熟；本地小模型（GLiNER + 本地 embedding）可以完全不用云 API；有 COGX 交换格式，能从 Mem0/Letta/Zep 迁进来；`forget` 是显式 API。

**弱在哪**：它是"知识工程"，不是"陪伴"。摄入有管线延迟，不适合每轮对话实时写；图的质量取决于抽取模型；`forget` 是删除，不是遗忘——没有衰减、没有"想不起来但还在"。

**陪伴适配**：低。适合"bot 要读大量设定集/世界观文档"这种场景，不适合记日常。

### PowerContext

**核心机制**：把"工作上下文"从对话里拿出来，做成服务端的一等对象。核心契约是 `Source`（原始证据，只追加）+ `Artifact`（可修订的理解，地址是 `FAMILY/ARTIFACT_ID@REVISION`）+ `Trigger`。一个 Scope 下装：Source journal、Memory（决策/约束/事实/下一步）、Review Inbox（Experience/Skill 候选待审）、Handoff（工作交接：Work Contract → Prepared Handoff → Acknowledgement → Task Outcome）、Topic Memory（后台从 Source 抽）。读取走 `PreparedContext`：按配置选段、套一个共享字节预算，返回 `ready` 或 `empty`。

**强在哪**：**Source 与 Artifact 分离**这件事想得最透——原始证据不可改，理解可以改，改错了能回到原话对账；revision 链让任意历史快照可读；`forgotten` 只是退出召回，内容和历史都还在，可恢复；PreparedContext 明确"有界，不倾倒"；写入有决策门控（Experience/Skill 要 review 才生效）。

**弱在哪**：为**工作交接**设计，不处理情绪、关系、模糊印象；Scope 是数据隔离不是身份认证（README 自己强调）；没有衰减曲线，`forgotten` 是显式生命周期操作；部署是 Server + HTTP/MCP，比插件重；语义检索要另配 embedding 凭证。

**陪伴适配**：低。但它是 SeekMemory 思想上的主要来源，见下一节。

### AstrBot 生态

**self_learning（419★）** 是生态里最重也最全的：默认 PostgreSQL，从真实对话里学表达风格和群黑话，学到的结果先进入**人格审查**链路，批准/拒绝/回滚都留痕，再叠加社交关系（好感度、心理状态）和记忆图/知识图谱，最后在 `on_llm_request` 注入。它把"人格演化"当成需要人类审批的变更，这个工程直觉很对。代价是配置复杂、默认要 PG、AGPL。

**angel_memory（189★）** 和 SeekMemory 的定位最接近。它有三层：灵魂层（4 个能量槽 RecallDepth / ImpressionDepth / ExpressionDesire / Creativity，用 tanh 映射到检索条数、记忆生成数、输出长度、温度）、潜意识层（后台检索/整理/巩固）、主意识层（4 个 LLM 工具：铭记、回忆、按短 ID 分页读笔记、整理笔记）。检索是 Tantivy + CJK 1~2-gram 的 BM25，可选 embedding 和 rerank，用 RRF 融合；睡眠维护会清理弱记忆；`conversation_scope_map` 先按人格名、再按会话 ID 分 scope。它的工程成熟度（分页、索引重建、备份、文件监控）比 SeekMemory 高。

**persistent-memory（87★）** 是最标准的 RAG 记忆：LanceDB 落盘，向量 + BM25 融合 + Jina rerank，打分带 recency/importance/time decay，scope 分 global/session，注入块用 `UNTRUSTED DATA` 包裹防提示注入——这个细节值得学。无人格。

**self_evolution（81★）** 的重点不是记忆而是**人格状态机**：energy / mood / social_need / satiety 四个值随时间差推演，Effect 带 `decay_style` 和 `recovery_style`，会生成"脑内待办"（"想把当时没说完的话接上"），还有日结情感轨迹。它的"被冷落会堵着"比 SeekMemory 的静态人格更动态，但长期记忆只是配角。

**memory_companion（53★）** 是 AstrBot 里设计最完整的陪伴记忆中枢：核心记忆按 Label 常驻（不依赖 RAG 命中）+ 结构化原子（owner / persona / 敏感级别 / 耐久度 / 有效期 / 证据 / 强化分 / 实际注入统计）+ 会话摘要 + **断言层**（"关于这个人什么是真的"，带出处、可合并、单值属性改口会接修订关系、旧值保留以支持过去时提问）。召回是多路 RRF + MMR 去重，排序同时看相关性、时间有效性、显著度、自然衰减、真实注入强化；权限分私聊/群聊/自我时间线/共享/内部，还有可视化权限拓扑；缓存 key 带 db revision，ACL 变了立刻失效；Token 可观测。它比 SeekMemory 多的是"断言/修订"和"权限拓扑"，少的是"四层沉淀"和"遗忘曲线"。

**iris_chat_memory（21★）** 用 FAISS + SQLite 做三层：L1 缓冲、L2 语义记忆（带遗忘评分：近因性衰减 + 访问频率 + 置信度，低分淘汰）、L3 知识图谱（实体关系 + 图增强检索 + 节点淘汰），再加用户/群画像和"梦境任务"（合并碎片、修正矛盾、发现行为模式）。功能覆盖和 SeekMemory 高度重叠，但它的"遗忘"是打分淘汰，不是留存率曲线。

**simple_long_memory（17★）** 最轻：复用 AstrBot 内置知识库，每 20 轮抽一次，召回注入最多 5 条，`memory_ttl_days` 默认 30 天过期。没有花活，但"抽取-注入-过期"三件事都做了，是很多插件的实际形态。

## SeekMemory 的位置

### 学了谁

- **PowerContext**：`Source` / `Artifact` 分离（原话只追加、理解可修订）、"通用头 + 类型化 payload"（加能力是加 `family`，不是给表加列）、`PreparedContext` 的有界预算视图、写入的决策门控。这四条在 `docs/zh/architecture/overview.md` 开头就写明了。
- **git**：内容寻址（sha256 存 blob，天然去重）、追加日志、哈希链（`ledger.prev_hash/self_hash`）、可 diff 任意时间点。
- **认知科学**：艾宾浩斯 `R = e^(−t/S)`、首因效应（最早三条不衰减）、激活扩散（语义网络里的 spread activation，落到 `similar/causal/temporal` 三型边）、闪光灯记忆（高唤醒 × 负效价几乎不忘）、metamemory（区分"我忘了"和"你没说过"）。

### 哪些是原创组合

- **四层 + 按 scope 分人的印象**：fact 不衰减、memory 衰减、impression 极慢、persona 只增修订；且 impression 是"对某个人"的，A 的印象 ≠ B 的印象。调研范围内没看到第二家把"印象"单独做成一层并绑定 scope 的。
- **情绪双维进衰减公式**：`arousal × valence` 不只是排序特征，而是乘进 `S`（高唤醒 ×1.5，低唤醒 ×0.8；负效价再叠 ×1.5 / ×0.6）。Mem0/Graphiti 都不看情绪，MemoryOS 的 heat 也不看。
- **形状系数**：`point 1.0 / span 1.2 / pattern 3.0 / rule 999.0`——"他经常加班"和"他那天加班到两点"用同一套衰减是错的，这个区分没在别处见到。
- **命中冷却 + 10% 探索**：30 分钟窗口内重复命中只算一次、跨天最多一次，防"越提越重要"的正反馈；10% 随机捞不相关的记忆，模拟"突然想起别的事"。这是产品向的设计，不是论文向的。
- **叙述式注入 + 三档不确定 + 相对时间 + metamemory**：注入的是"你印象里他有点倔"而不是 bullet list；`confidence` 分三档决定口吻；时间戳翻译成"三天前"；同话题有 forgotten 记忆时说"我忘了"而不是"你没说过"。这四条合起来才是"像人"，单看每一条都不难。
- **每轮零模型调用**：检索全在本地内存 + SQLite 完成，只有夜间抽取和每周整理调模型。这让它敢在每轮都注入记忆。

### 短板（不客气地说）

1. **没有语义检索，这是硬伤。** 打分靠字符二元组 Dice 系数 + 标签 + 情绪词，用户换个说法（"最近好累" vs 记忆里的"加班到两点"）就漏。Mem0 有向量 + BM25 + 实体三路，angel_memory 有 Tantivy CJK BM25 + 可选 embedding + rerank，iris 有 FAISS。SeekMemory 连 BM25 都没有，中文长尾词的召回明显弱于同生态竞品。激活扩散能补一点联想，但边是写入时建的，覆盖不到"说法不同"。
2. **单机、单进程、单文件 SQLite。** 没有并发写保护、没有多租户物理隔离、没有权限审计。`scope` 和 RBAC 是应用层标记，`shadow` 的"锁死"是代码里的规则，不是加密——拿到 db 文件就全看得到。
3. **没有多模态。** `family=media` 只存摘要和 URL，图片/语音内容不进记忆。iris 至少有图片描述，companion 有原文查询。
4. **基准是自建的，规模小、无对照。** 19 条模拟事件、8 个查询、30 天，98/100 是自评分，没有和 Mem0/MemoryOS 在同一数据集上的对比，也没跑 LoCoMo/LongMemEval。这个分数只能说明"实现符合自己的设计"，不能说明"比别人好"。
5. **零模型调用的另一面**：抽取质量受限于夜间一次调用 + 规则门控，白天的新信息要等；规则（情绪词表、否定检测）覆盖不到反讽和省略。
6. **人格没有评估维度。** persona 的"版本化"只是 revision 号，没有"这次改动让人格更一致还是更飘"的判据。
7. **生态几乎为零。** 1 star，没有 WebUI、没有可视化、没有导入导出、没有迁移工具。竞品这些都有。

一句话：**SeekMemory 的长处是"模型"（怎么忘、怎么沉淀、怎么像人），短处是"基础设施"（检索、并发、多模态、生态）。** 它不该去和 Mem0 拼吞吐，也不该和 Graphiti 拼时间查询；它该守住的是"同样 600 字预算，注入的内容更像一个人说出来的"。

## 场景选型表

| 你要做什么 | 推荐 | 理由 |
|---|---|---|
| 给产品加"记住用户偏好"，两周上线 | **Mem0** | SDK 成熟、20+ 向量库、文档全，接完就有 |
| 需要回答"这件事现在还算数吗 / 去年十月是什么状态" | **Graphiti / Zep** | 双时间 + 事实失效，别自己造 |
| 要 agent 自己整理记忆、可审计可回滚 | **Letta（MemFS）** | git + Markdown，版本和冲突都是现成的 |
| 团队协作、跨会话交接工作上下文 | **PowerContext** | Source/Artifact + Handoff + 有界 PreparedContext |
| 让 bot 读大量设定集/文档再回答 | **cognee** | 图谱化管线 + 自定义 ontology + 本地模型可离线 |
| 技术栈是 LangGraph，只要记忆积木 | **langmem** | namespace + BaseStore + prompt 优化，别重复造 |
| 做中文 IM 陪伴 bot，单机、零外部依赖、要"会忘" | **SeekMemory** | 四层 + 遗忘曲线 + 按人印象 + 零模型调用，装完即用 |
| 做陪伴 bot，要权限边界、断言修订、Token 可观测 | **memory_companion** | AstrBot 里设计最完整，私聊/群聊/自我时间线分权 |
| 要人格状态（会被冷落、有情绪起伏） | **self_evolution** | 四维状态机 + Effect 衰减 + 脑内待办 |
| 要向量召回 + 人格能量槽 + 成熟工程 | **angel_memory** | BM25 + 可选向量/重排，睡眠巩固，分页索引都有 |
| 群聊多人、要画像 + 知识图谱 + 淘汰 | **iris_chat_memory** | L1/L2/L3 + 遗忘评分 + 节点淘汰 |
| 人格演化必须人工审批 | **self_learning** | 学习结果进审查链路，可批准/拒绝/回滚 |
| 只想让 bot 记住几十条偏好，别搞复杂 | **simple_long_memory** | 复用 AstrBot 知识库，TTL 30 天，够用 |
| 做记忆系统的学术复现/评测 | **MemoryOS / A-MEM** | 有论文、有 LoCoMo 数字、代码短 |

**明确不适合 SeekMemory 的场景**：多租户 SaaS、需要跨语言/同义词语义召回、需要图片语音、需要百万级记忆、需要给别人开的 bot 平台。

## 附：本次调研的验证状态

| 项目 | 已验证 | 未验证 / 仅 README |
|---|---|---|
| Letta | Star/许可/提交；MemFS 结构、根目录常驻、无语义索引、dreaming（官方文档）；旧版三块结构（archive 分支的 `block.py` / `archive.py` / `passage.py` / `memory.py` schema） | 新版 MemFS 在 IM 场景的实际表现；旧版 block 的具体版本机制未逐行读码 |
| Mem0 | Star/许可/提交；`qdrant-client` 核心依赖、`history.db`、20+ 向量库适配器、ADD-only 与三路融合（README + `pyproject.toml`） | OSS 图记忆的开箱程度（有文档和 examples，主代码树未见独立 graphs 模块） |
| Graphiti | Star/许可/提交；双时间、episode、混合检索、Neo4j/FalkorDB/Neptune + OpenSearch 依赖（README） | 未实测建图成本与召回质量 |
| A-MEM | Star/许可/提交；ChromaDB、笔记属性、evolution agent 会改写邻居 tags（`memory_system.py` 源码） | 多用户隔离为"无"，依据是单 collection，未穷举所有分支 |
| MemoryOS | Star/许可/提交；三层结构、heat 公式、LFU 淘汰（`mid_term.py` 源码）、JSON 落盘 | 短期容量满后的具体 FIFO 细节未逐行核对 |
| langmem | Star/许可/提交；namespace、BaseStore、memory tools、prompt optimizer（README） | "无自动遗忘"是文档未提及，不等于代码里绝对没有 |
| cognee | Star/许可/提交；默认 Kuzu + LanceDB + SQLite（`config.py`）、forget API、COGX | Postgres 一体化仍标 demo；未实测 |
| PowerContext | Star/许可/提交；Source/Artifact/Trigger、Scope、revision、PreparedContext、SQLite/seekdb（README） | 未实测；语义检索需自配 embedding |
| AstrBot 插件 | 各自的 Star/许可/提交；存储、检索、遗忘、隔离机制均来自 README（angel/iris 的机制描述较具体） | 均未读源码验证；self_learning 的自动衰减未说明 |
| SeekMemory | 本仓库 README / DESIGN.md / schema.sql / 依赖扫描（纯标准库 + sqlite3） | 自身 benchmark 为自建小数据集，未与外部基线对比 |
