# HOST-PORTS.md · 宿主端口契约 v1

> 状态：**v1 草案**，对应 issue [#107](https://github.com/NeverENG/SeekMemory/issues/107)。
> 权威定义永远是 `app/ports.py` 与 `app/contracts.py`；本文只解释它们的**语义**，不新增实现。
> 配套的一致性测试层（`conformance`）随本文一起落地后，本文的每条断言都必须有对应用例。

**TL;DR (EN)** — Contract v1 for any host other than AstrBot. `app/ports.py` defines 8
runtime-checkable Protocols; the `ChatRequest` / `ChatResponse` dataclasses in `app/contracts.py`
**are** the wire format. A host either implements the ports in-process or exchanges the same JSON
over loopback — and in the cross-process case the host pulls work, the kernel never calls back. A
host must never: hold a kernel SQLite transaction across a model call, call a model during recall,
overwrite an Artifact without a matching `expected_revision`, or let one subject read another's
records. Subject keys must be stable; a host without a stable identifier must degrade explicitly to
a fixed key and warn instead of pretending. Of the 51 keys in `_conf_schema.json`, 34 carry kernel
semantics that must map one-to-one; the rest are host UI, scheduling, or AgentRuntime concerns.

---

## 0. 这份文档解决什么

内核（`core/`、`recall/`、`store/`、`app/`）与宿主无关，但"宿主必须提供什么"此前只存在于 AstrBot 适配器的代码里。
本文把那半边写成契约，使**第二个宿主**可以只读这两份文档就去实现，而不必反推 `adapters/astrbot_*.py`。

契约版本：`host_contract = 1`。语义发生不兼容变化时才 +1。

---

## 1. 端口清单

`app/ports.py` 定义 8 个 `runtime_checkable` 协议。宿主实现它们，内核只依赖它们。

| 端口 | 用途 | 宿主必须实现 | 内核是否会在事务内调用 |
|---|---|---|---|
| `ChatModel` | 模型调用 | **是**（否则抽取与人格合成不可用） | 否（明确禁止，见 §6） |
| `Retriever` | 候选排序 | 否（默认实现即可） | 否 |
| `SourceStore` | 不可变原始消息的写入与查询 | **是** | 是（由 store 层在事务内使用） |
| `ArtifactStore` | 派生记忆的版本化写入 | **是** | 是 |
| `ArtifactCache` | 内存视图与版本号 | **是** | 是 |
| `MetricsStore` | 容量观测 | 否（可返回空字典） | 否 |
| `LedgerStore` | 调用台账 | **是** | 否 |
| `ExtractionStore` | 抽取队列 | **是** | 是 |

"宿主必须实现"指内核在默认路径上会调用到它；「否」表示可以不提供，内核会退化为不使用该能力，而不是报错。

---

## 2. 逐端口契约

签名逐字取自 `app/ports.py`，不改写。

### 2.1 ChatModel

```python
async def complete(self, request: ChatRequest) -> ChatResponse: ...
```

- **语义**：把 `ChatRequest` 发给宿主自己的模型提供方，返回 `ChatResponse`。内核不持有任何凭据。
- **幂等**：**非幂等**。一次调用就是一次真实计费调用，宿主不得擅自重试（重试由内核按 `ExtractionStore` 的队列状态决定）。
- **失败行为**：**fail loudly** —— 抛异常。内核据此写 `WriteOutcome.model_failed=True`、`retryable=...`，并把 Source 留在待抽取队列里，不丢数据。
- **事务**：宿主**绝不可**在持有内核 SQLite 事务时被调用（见 §6 第 3 条）。
- **可选性**：技术上可选（不提供则抽取全不可用），实际是必需。

### 2.2 Retriever

```python
def retrieve(self, query: str, pool: list[Artifact]) -> list[RetrievalCandidate]: ...
```

- **语义**：在**给定候选池**内排序打分，返回候选。它不查询存储、不调用模型——池子由内核准备好传进来。
- **幂等**：是（纯函数式，同样的输入同样的输出；允许内部有随机探索，但不得有副作用）。
- **失败行为**：内核不做兜底；实现应尽量不抛。退化实现可以返回空列表，内核会当作"本轮无召回"。
- **可选性**：可选，默认 BM25 实现位于 `recall/`。

### 2.3 SourceStore

```python
def append_sources(self, sources: list[Source]) -> int: ...
def recent_sources(self, *, since: str, limit: int) -> list[Source]: ...
def source_umo(self, source_id: str) -> str: ...
def source_umos(self, source_ids: list[str]) -> dict[str, str]: ...
def sources_by_ids(self, source_ids: list[str]) -> dict[str, Source]: ...
```

- **语义**：Source 是**不可变**的原始消息真相层。写入只追加，不更新、不删除。
- **幂等**：`append_sources` **必须幂等**。参考实现用 `INSERT OR IGNORE`（`store/sources.py:38-52`），重复的 `id` 被忽略，返回值是**实际写入的行数**（重复项不计）。宿主若用别的存储，必须保持"重复 id 不重复写入、不报错"。
- **失败行为**：违反 `Source.validate()` 的输入（空 id、未知 role、空正文）直接抛 `ValueError`（`core/source.py:35-41`）。
- **返回语义**：`source_umo` 用于归属校验，未知 id 返回空字符串而不是抛错。

### 2.4 ArtifactStore

```python
def commit(self, art: Artifact, *, expected_revision: int, op: str,
           reason: str = "", source_ids: tuple[str, ...] = (),
           state_events: tuple[StateEvent, ...] = ()) -> None: ...
def commit_many(self, writes: list[tuple[Artifact, int, tuple[str, ...]]], *,
                op: str, reason: str = "") -> None: ...
def get(self, node_id: str) -> Artifact | None: ...
def by_source_ids(self, source_ids: list[str]) -> list[Artifact]: ...
def list(self, family: str | None = None, state: str | None = None) -> list[Artifact]: ...
def history(self, node_id: str) -> list[dict]: ...
def add_edge(self, src: str, dst: str, kind: str, weight: float) -> None: ...
def edges_of(self, node_id: str) -> list[tuple[str, str, float]]: ...
def set_parent(self, node_id: str, parent_id: str | None) -> None: ...
def inspect_record(self, node_id: str) -> dict: ...
```

- **语义**：Artifact 是派生记忆层，带 `revision`、证据（lineage）与账本语义。版本**只增不减**。
- **幂等 / 冲突**：`commit` 必须校验 `expected_revision` 与当前版本一致，否则抛 `VersionError`（`core/versioning.py:12`，抛点在 `store/artifacts.py:241-244`）。**绝不允许无检查覆盖**。`add_edge` 是 upsert（同 `(src,dst,kind)` 更新 weight），幂等。
- **原子性**：`commit_many` 必须整批成功或整批失败——它用于"一组版本写入必须同时成立"的场景。
- **失败行为**：`get` 未命中返回 `None`；`history` 对未知 id 返回空列表。
- **不变量**：写入 `Artifact` 时必须同时落它的证据（`source_ids`）与状态事件（`state_events`），否则账本不可复核。

### 2.5 ArtifactCache

```python
artifacts: ArtifactStore
@property
def version(self) -> int: ...
def load(self) -> None: ...
def put(self, art: Artifact) -> None: ...
def get(self, node_id: str) -> Artifact | None: ...
def active(self, family: str | None = None) -> list[Artifact]: ...
def by_level(self, level: str) -> list[Artifact]: ...
def by_subject(self, subject_id: str) -> list[Artifact]: ...
def remove(self, node_id: str) -> None: ...
def size(self) -> int: ...
```

- **语义**：存储之上的**内存视图**。`version` 每次写入后自增，内核据此判断是否需要重载。
- **幂等**：`put` / `remove` 幂等；`load` 可重复调用。
- **不变量**：`by_subject(subject_id)` **只能返回该主体的记录**——这是跨主体隐私的边界，见 §7 第 2 条。

### 2.6 MetricsStore

```python
def capacity_usage(self, now: str = "") -> dict[str, Any]: ...
```

- **语义**：只读观测，供容量治理与仪表盘使用。
- **失败行为**：返回空字典是合法的（宿主没有容量概念时）。

### 2.7 LedgerStore

```python
def entries(self) -> list[Any]: ...
def verify(self) -> bool: ...
```

- **语义**：追加式调用台账（模型调用、用量、时间）。`verify()` 用于自检台账未被篡改。
- **不变量**：只追加，不修改历史条目。宿主不得在 `entries()` 里返回不同口径的混合数据。

### 2.8 ExtractionStore

```python
def enqueue_extraction(self, source: Source, topic_id: str, created_at: str = "",
                       *, deferred: bool = False) -> bool: ...
def pending_extractions(self, now: str = "") -> list[dict]: ...
def queue_counts(self) -> dict[str, int]: ...
def release_deferred(self, limit: int = 50) -> int: ...
def ready_extraction_ids(self, now: str = "") -> set[str]: ...
def mark_extraction_succeeded(self, source_ids: list[str]) -> int: ...
def mark_extraction_failed(self, source_ids: list[str], error_type: str, *,
                           max_attempts: int = 5, now: str = "") -> int: ...
```

- **语义**：抽取队列。Source 写入后进队列，抽取成功则出队，失败则按退避重试，超过 `max_attempts` 才终结。
- **幂等**：`enqueue_extraction` 幂等（同 `source.id` 不重复入队，参考实现 `INSERT OR IGNORE`，`store/extraction.py:50`）；`mark_*` 幂等（重复标记不产生副作用）。
- **失败行为**：`mark_extraction_failed` 必须**保留**待抽取输入而不是丢弃——这是"不丢数据"的核心保证。
- **返回值**：`release_deferred` / `mark_*` 返回受影响行数；`ready_extraction_ids` 返回可立即处理的 id 集合。

---

## 3. 数据形状（要点，完整定义见源码）

| 类型 | 位置 | 关键点 |
|---|---|---|
| `Source` | `core/source.py:23-45` | `id / turn_id / session_id / speaker_id / role / text / at / reply_to / metadata`；`role ∈ {user, assistant, system, tool, external}`；不可变 |
| `Artifact` | `core/artifact.py` | 统一 `Header`（`id / family / revision / state / scope / lineage / strength / time`）+ 按 family 区分的 payload；`family ∈ {memory, example, persona, media, secret, designated}` |
| `ChatRequest` | `app/contracts.py:66-74` | `session_id / system_prompt / prompt / model / temperature / max_tokens / json_mode` |
| `ChatResponse` | `app/contracts.py:77-86` | `text / model / provider_id / usage_in / usage_cached / usage_out / response_id / latency_ms` |
| `WriteOutcome` | `app/contracts.py:53-63` | 汇总 `written / skipped / errors / model_failed / retryable / usage_*` |

---

## 4. 主体键（subject key）

内核按 `subject_id` 归档记忆。**宿主必须提供稳定的键**，否则重启或换会话后记忆会错位到别的"人"身上。

- 推荐语法：`<channel>:<scope>:<stable_user_id>`，例如 `napcat:FriendMessage:100000000`。
- 这是**一个合法实例**，不是定义本身。第二宿主可以用自己的 `<channel>`。
- 若宿主拿不到稳定标识，**必须显式退化**为固定键（如 `local:single:default`）并在日志里告警一次——**不得静默假装有归属**。
- 同一内核实例内，不同主体之间必须有硬边界：召回不得返回其他主体的私有记录（§7 第 2 条）。

---

## 5. 模型传输与调用方向

- `ChatRequest` / `ChatResponse` **就是**线格式，不新增 DTO。
- **同进程**（AstrBot）：宿主实现 `ChatModel` 对象。
- **跨进程**（第二宿主）：交换同样的 JSON。
- **调用方向固定为宿主拉取**：内核产出准备好的 `ChatRequest`，宿主取走、调模型、把 `ChatResponse` 交回。**内核绝不回调宿主**，也不需要宿主开放入站端口。
- 凭据与计费留在宿主侧，内核不保存任何密钥。

---

## 6. 宿主不得违反的不变量

1. **Source 不可变**：写入后不得更新或删除。
2. **版本只增**：`ArtifactStore.commit` 必须校验 `expected_revision`，冲突抛 `VersionError`，绝不覆盖。
3. **模型/网络调用期间不持有 SQLite 事务**：宿主实现 `ChatModel` 时若被内核在事务内调用，属于内核违约；反过来说，宿主不得在自己持有写事务时同步等待模型返回。
4. **召回期间模型调用数为 0**：`recall/` 内不含任何 `complete(` / `text_chat` 调用；宿主不得在召回路径上偷偷调模型。
5. **secret 家族永不注入**：`secret` 记录只能出现在受控的披露路径里，不进入常规注入块。
6. **跨主体不串**：`by_subject` 与召回都必须按 `subject_id` 过滤。
7. **账本只追加**：`LedgerStore.entries()` 的口径不得随时间改变。
8. **注入遵守预算**：组装出的注入块必须不超过配置的字符上限（`budget_chars` 等）。

---

## 7. 配置键切分

`_conf_schema.json` 有 51 个键，它们**不都属于内核语义**。第二宿主必须能映射第一类，其余可按自己的界面重做。

### 7.1 内核语义键（映射后行为必须一致）

| 分组 | 键 |
|---|---|
| 注入与召回 | `budget_chars`、`recall_k`、`explore_rate`、`recall_min_ev_abs`、`recall_min_ev_rel`、`bm25_enabled`、`bm25_weight`、`source_recall_enabled`、`source_recall_hours`、`source_recall_max_candidates` |
| 抽取节奏 | `idle_flush_seconds`、`min_pending`、`max_flushes_per_day`、`max_sessions_per_flush`、`checkpoint_seconds`、`backlog_flush_at`、`topic_ttl_seconds` |
| 梦境与人格 | `dream_enabled`、`dream_max_batches`、`dream_max_calls`、`dream_batch_tokens`、`dream_token_budget`、`persona_synthesis_enabled`、`persona_synthesis_interval_days`、`persona_synthesis_evidence_limit`、`persona_synthesis_evidence_chars`、`enable_reflect` |
| 容量与保留 | `max_episodes`、`capacity_thresholds`、`trace_retention_days`、`trace_max_rows` |
| 上下文预算 | `context_system_chars`、`group_context_messages`、`history_messages` |

### 7.2 宿主界面键（AstrBot 专属，第二宿主按自己的方式实现）

| 键 | 为什么是宿主的 |
|---|---|
| `owner_umo` | 值形如 `napcat:FriendMessage:100000000`，是 AstrBot/napcat 的会话标识格式；第二宿主用自己的标识，但必须能映射出 §4 的主体键 |
| `open_to`、`trusted`、`observe_groups` | AstrBot 侧的权限/可见性概念 |
| `db_path` | 宿主侧的存储落点 |
| `debug_log` | 宿主侧日志开关 |

### 7.3 调度时刻键（由宿主触发，内核不自己起定时器）

`summary_time`、`dream_time`、`weekly_day` —— 内核只提供"现在该不该抽/该不该做梦"的判断，**真正的时间驱动在宿主**。

### 7.4 AgentRuntime 键（DSH 宿主可整体不实现）

`runtime_gate_enabled`、`runtime_wait_seconds`、`runtime_tick_seconds`、`runtime_dispatch_max_attempts`、`runtime_dispatch_backoff_seconds`、`runtime_tool_filter_enabled`、`runtime_episode_retention_days`、`runtime_episode_max_rows` —— 这组属于 AstrBot 侧的 AgentRuntime 插件行为，不属于记忆内核本身。

---

## 8. 验收：conformance 层

实现位置 `tests/test_host_ports_conformance.py`，入口 `python scripts/run_tests.py --layer conformance`。

下表的 8 条契约由 **9 个用例**覆盖（第 2 条拆成 secret 与跨主体两个用例），且**现有 AstrBot 适配器不改用例就能通过**——这才是这一层可信的原因：

1. 捕获 → 召回往返，经正常披露路径取回刚写入的事实；
2. 召回不返回 `secret`，也不返回其他主体的私有记录；
3. 重复 `source.id` 幂等，返回值不重复计数；
4. `expected_revision` 不匹配抛 `VersionError`，不覆盖；
5. 召回期间模型调用计数为 0；
6. 上下文亲和度低时披露降级为 paraphrase/hint；
7. 模型调用失败后待抽取输入仍可恢复，缓存与账本均未改动；
8. 注入块不超过配置字符上限。

这 9 个用例中的关键断言都做过反向验证：人为把「secret 换成普通记忆」「受话人换成本人」「幂等期望值改错」之后，对应用例必须失败，避免空载荷跑绿。

---

## 9. 与 AstrBot 适配器的关系

AstrBot 仍是宿主的**参考实现**：`adapters/astrbot_*.py` 是同进程实现，`main.py` 是唯一 import `astrbot.api.star` 的文件。
第二个宿主（`adapters/dsh/`）是跨进程实现，用来证明这条契约真的宿主无关。

新增宿主时不必修改 `core/`、`recall/`、`store/`，也不需要本文允许之外的新接口。
