# 模块接口契约

**所有 subagent 必须严格按这里的签名实现，不要改。**

---

## core/artifact.py

```python
from dataclasses import dataclass, field
from typing import Any

@dataclass(frozen=True)
class Strength:
    weight: float = 1.0
    confidence: float = 1.0
    arousal: float = 0.3
    valence: float = 0.0
    funny: float = 0.0

@dataclass(frozen=True)
class TimeSpan:
    created: str = ""
    updated: str = ""
    valid_from: str | None = None
    valid_to: str | None = None
    expires: str | None = None

@dataclass(frozen=True)
class Lineage:
    sources: tuple[str, ...] = ()
    derived_from: tuple[str, ...] = ()

@dataclass(frozen=True)
class Header:
    id: str
    family: str
    revision: int = 1
    state: str = "active"
    scope: str = "private"
    lineage: Lineage = field(default_factory=Lineage)
    strength: Strength = field(default_factory=Strength)
    time: TimeSpan = field(default_factory=TimeSpan)
    said_by: str = "owner"
    shareable: str = "private_only"

@dataclass(frozen=True)
class Artifact:
    header: Header
    payload: dict[str, Any]

def make(family: str, payload: dict, **header_kw) -> Artifact: ...
def revise(art: Artifact, payload: dict | None = None, **header_kw) -> Artifact: ...
def validate(art: Artifact) -> None: ...   # 抛 ValueError
def content_of(art: Artifact) -> str: ...  # 各 family 的"可读文本"
```

## core/strength.py

```python
def retention(s: Strength, shape: str, days: float) -> float: ...
    # 艾宾浩斯 × 形状系数 × 情绪系数
def decayed_weight(s: Strength, shape: str, days: float) -> float: ...
def reinforce(s: Strength, source: str) -> Strength: ...
    # source: "recall"(+0.1) | "spoken"(+0.3) | "confirmed"(+0.2)
def hit_cooldown_ok(last_window: str | None, now: str) -> bool: ...
    # 30 分钟窗口合并
```

## core/tree.py

```python
class Tree:
    def __init__(self, artifacts: ArtifactStore, cache: Cache): ...
    def children(self, node_id: str) -> list[Artifact]: ...
    def impressions(self) -> list[Artifact]: ...
    def add_under(self, child: Artifact, parent_id: str | None) -> Artifact: ...
```

## core/graph.py

```python
class Graph:
    def __init__(self, artifacts: ArtifactStore): ...
    def link(self, src: str, dst: str, kind: str, weight: float) -> None: ...
    def link_causal(self, src: str, dst: str, weight: float = 1.0) -> None: ...  # 仅接口，不自动调用
    def degree(self, node_id: str) -> int: ...
    def neighbours(self, node_id: str, kinds: tuple[str, ...] = ("similar","causal","temporal")) -> list[tuple[str, float]]: ...
```

## store/__init__.py and repositories

`Store` is composition only. It owns one SQLite connection and exposes domain repositories:

```python
class Store:
    artifacts: ArtifactRepository
    sources: SourceRepository
    extraction: ExtractionRepository
    runtime_state: RuntimeStateRepository
    runtime_episodes: RuntimeEpisodeRepository
    dreams: DreamRepository
    ledger: LedgerRepository
    metrics: StoreMetricsRepository
    conn: sqlite3.Connection
    def close(self) -> None: ...
```

Repositories live in `store/artifacts.py`, `store/sources.py`, `store/extraction.py`,
`store/runtime_state.py`, `store/runtime_episodes.py`, `store/dreams.py` and
`store/metrics.py`. SQL and migrations stay inside `store/`.

## store/cache.py

```python
class Cache:
    def __init__(self, artifacts: ArtifactRepository): ...
    @property
    def version(self) -> int: ...        # 单调递增的派生索引失效标识
    def load(self) -> None: ...          # 全量载入 active
    def put(self, art: Artifact) -> None: ...
    def get(self, node_id: str) -> Artifact | None: ...
    def active(self, family: str | None = None) -> list[Artifact]: ...
    def by_level(self, level: str) -> list[Artifact]: ...
    def remove(self, node_id: str) -> None: ...
```

## recall/seed.py

```python
def seeds(text: str, pool: list[Artifact], limit: int = 5) -> list[str]: ...
```

## recall/spread.py

```python
def activate(seed_ids: list[str], graph: Graph, cache: Cache, rounds: int = 2) -> dict[str, float]: ...
```

## recall/score.py

```python
def score(art: Artifact, text: str, activation: float, now_days: float) -> float: ...
def select(candidates: list[Artifact] | list[tuple[Artifact, float]] | list[RetrievalCandidate],
           text: str, now_days: float, k: int = 8, explore: float = 0.1,
           seed: int | str | None = None, gate: bool = True,
           min_ev_abs: float | None = None, min_ev_rel: float | None = None,
           lexical_weight: float = 2.0) -> list[Artifact]: ...
def pinned(cache: Cache) -> list[Artifact]: ...   # recall/gate.py
```

`gate=True` 时只保留相关性证据（字面 + lexical + 标签 + 情绪 + 激活）达到
`max(min_ev_abs, top_evidence × min_ev_rel)` 的候选，没有候选达标就返回 `[]`；
`weight` / `freshness` 只参与排序。纯问时间的时钟类消息直接返回 `[]`。
`gate=False` 保持旧的 top-k 行为。`pinned(cache)` 返回常驻层
（active persona 全部 + 印象层按 weight 前 2），该层不经过证据闸门。

## recall/scope.py

```python
def owner_of(art: Artifact, lookup: Callable[[str], str] | None = None) -> str: ...
def visible(pool: Iterable[Artifact], umo: str, owner_umo: str = "",
            lookup: Callable[[str], str] | None = None) -> list[Artifact]: ...
```

## recall/designated.py

```python
def triggers_of(art: Artifact) -> list[str]: ...
def matches(art: Artifact, text: str) -> bool: ...
def already_given(art: Artifact) -> bool: ...
def is_private(event) -> bool: ...
def deliverable(art: Artifact, text: str, private: bool) -> bool: ...
def mark_given(artifacts, cache, arts: list[Artifact], block: str, now: str | None = None) -> int: ...
```

## recall/assemble.py

```python
def build(arts: list[Artifact], budget: int = 2000,
          *, text: str | None = None, is_private: bool | None = None) -> str: ...
```

`text` / `is_private` 是新增的**可选**会话上下文，旧调用不受影响：传入后
`designated` 才可能交付正文（私聊 + 命中触发词 + 未 given）；不传时维持
“只给托付提示”。`scope=shadow` 无论是否传上下文都只输出影子句。

## maintain/decay.py

```python
def decay_all(artifacts: ArtifactStore, cache: Cache, today: str) -> int: ...  # 返回被标 forgotten 的数量
```

## maintain/merge.py

```python
def merge_similar(artifacts: ArtifactStore, cache: Cache, threshold: float = 0.6, limit: int = 50) -> int: ...
```

## maintain/promote.py

```python
def promote_candidates(cache: Cache, min_hits: int = 3,
                       today: str | None = None, only_umo: str = "") -> list[Artifact]: ...
    # 仅有真实独立助手证据的 bot:self 自我印象；不再接受用户印象或以年龄替代证据
```

## maintain/link.py

```python
def link_new(art: Artifact, graph: Graph | None, cache: Cache | None,
             created: str | None = None) -> int: ...
def persist(art: Artifact, artifacts: ArtifactStore, cache: Cache | None,
            graph: Graph | None) -> int: ...
    # 先写库/缓存，再建 similar/temporal；建边失败返回 0，不影响写入
```

## maintain/persona.py

```python
def compose(impressions: list[Artifact]) -> str: ...
def distill_persona(artifacts: ArtifactStore, sources: SourceStore,
                    cache: Cache, today: str | None = None) -> Artifact | None: ...
    # 取 top3 impression 拼第二人称 persona；旧 persona 置 merged，写 merge 账本
```

## maintain/reflect.py

```python
def signals(prev_user: str, cur_user: str) -> dict: ...
    # {"wrong": int, "right": int, "reasons": [...]}
```

---

## 发布契约

发布边界：`scripts/package_plugin.py` 仅接收已构建的生产视图和 Git 跟踪的后端运行文件，
输出根目录可安装的 ZIP 与 SHA-256 校验文件。缺失 SQL、入口、JS/CSS 或许可证即失败；
指定发布标签时必须与 metadata 版本一致。测试、Mock、源码映射、依赖目录和本地数据不得入包。
源码下载保持原样，安装使用 Release 附件，详见 [发布流程](../CONTRIBUTING.md#release-packaging)。

## WebUI 管理接口

宿主扫描 `pages/memory/index.html`，注入 `window.AstrBotPluginPage`。
前端调用 `apiGet("manage/records")` 等相对 endpoint；宿主转发至插件注册的
`/astrbot_plugin_seekmemory/manage/<action>`，并注入管理员请求上下文。
接口拒绝没有 `request.username` 的调用。JSON POST 请求体上限 64 KiB；文件上传使用宿主
`AstrBotPluginPage.upload(endpoint, file)` 桥接，并由插件按 JSON/JSONL 格式限制实际字节数。

| 方法与 action | 输入 | 输出 / 行为 |
|---|---|---|
| GET records | 无 | `{records}`：六个家族、三种状态/scope，完整管理目录 |
| GET detail | query `id` | `{artifact, versions, sources, ledger}`，包含原始快照和证据 |
| GET status | 无 | `{ready, checks, activeTask, pending, pendingTopics, extractionPolicy, checkpointPending, schedulerCount, config}` |
| GET events | 可选 kind/status/search | `{events, capacity:500}`，新事件在前 |
| POST update | id/expectedRevision/payload/scope/state/reason/confirmed | `{id}`，追加修订；禁止更改来源或任意头字段 |
| POST diagnose | query/umo/speaker | `{block, info, visible, excluded}`；无数据库写入 |
| POST task | kind=`extract` 或 `weekly`，confirmed=true | `{id}` 任务 ID；忙时 409 |
| POST cancel | id，confirmed=true | `{id}`；仅取消当前匹配的活动任务 |
| POST importUpload | multipart 字段 `file` | `{stageKey, filename, size, preview}`；只暂存并校验 ChatLab v0.0.2 私聊文件，不返回消息正文 |
| POST importValidate | stageKey、Bot/用户平台 ID、目标私聊 UMO、文件成员映射 | `{preview}`；预检全文件身份与角色，不正式写入 Source |
| POST importConfirm | 同预检映射、confirmed=true | `{id}`；创建后台初始化任务并立即返回 |
| GET importTasks | 无 | `{tasks}`；最近任务摘要，不含用户 ID、消息正文或暂存路径 |
| GET importTask | query `id` | `{task}`；单个任务摘要和 Source 提取进度 |
| POST importCancel | id、confirmed=true | `{id}`；取消正在运行的历史初始化任务 |
| POST importRetry | id、confirmed=true | `{id}`；在原文件保留期内用相同的已确认映射从头重试 |
| POST importAbandon | id、confirmed=true | `{id}`；提前放弃可重试任务并清理原文件 |

update 拒绝多余字段，reason 为 1–300 字符，payload 为对象且序列化长度不超过 50,000，
使用原有 family 校验器，统一调用上游 `artifacts.commit()`，通过 expected_revision 检测版本冲突。
版本、版本级证据和账本在同一事务内提交，失败整体回滚；成功后更新 Cache。
遗忘使用 `forget`，其他人工修订（含恢复）使用 `revise`；账本 before_hash/after_hash
沿用上游语义，记录修订号字符串。内容哈希从版本的 blob 字段查看。
detail 从 artifact_versions 读取历史，联合旧 evidence 和新版 artifact_evidence 读取来源。
detail 的 header 可选包含 subject_id、said_by 和 time；前端保留缺失字段，不推断旧记录归属。
detail 不补造旧数据缺失的证据或账本；catalog 当前加载完整目录后由前端分页，不提供大库流式加载。

无认证 401，方法错误 405，记录不存在 404，输入错误 400，版本冲突/任务繁忙 409，
引擎不可用 503，未预期异常 500。诊断调用 `build_block(..., dry_run=True)`，跳过 designated 的 mark_given。
模型检测失败仍返回其他检测结果；错误只记录类型，不把异常内容泄漏到生命周期日志。

`services/management_service.py` 无宿主依赖；`routes.py` 负责宿主适配；`jobs.py` 管理单一活动任务；
`journal.py` 管理有界持久化日志。每条新事件包含 `level`、`stage`、
`source:{module,file,function,line}`、`context`、`durationMs` 和可空的 `error:{type,frames}`。
`file` 为插件相对路径，外部依赖仅显示文件名；异常帧不含源码正文、局部变量或异常消息。
旧记录缺少字段时前端保留兼容默认值，位置显示“旧记录未采集源码位置”，不会伪造位置信息。
`context` 仅接受显式传入的标量计数或 ID，最多 32 项，字符串截断为 200 字符。
前端支持级别、模块、业务类型和状态组合筛选，文本搜索覆盖函数、行号、阶段、业务字段和任务 ID。

`Journal.span(kind, stage, **context)` 记录阶段起止、耗时、失败或取消，并原样抛出异常。
`Jobs` 使用实例内 ContextVar 传递任务 ID，结束后 reset，避免并发诊断请求误挂在维护任务上。
重启恢复只根据无 stage 的任务生命周期事件判定终态；中间阶段成功不代表整个任务成功。
抽取通过注入的 context-manager 回调记录 provider.call、response.parse、memory.deduplicate、
artifact.validate、artifact.persist 和 impression.revise，不导入 WebUI 或宿主模块。
缓冲沿用上游 `DialogueTurn` 与话题划分；status 同时返回会话汇总和话题摘要（ID、会话、条数、最早时间），不包含对话正文。
extractionPolicy 返回后端采用的积压阈值、TTL 秒数与批次话题上限；checkpointPending 为待强化记忆数，未初始化为 null。
话题全部时间无效时 oldestAt 为 null。日志记录 topic.extract 与话题 ID。
抽取返回上游 `WriteOutcome`，阶段日志记录 written/skipped；模型失败保留会话缓冲。
没有可用模型不消耗批次次数；单个会话失败后继续其他可用会话，批次结束再传播首个失败。
成功后才移除该会话快照中的消息，保留取消、失败以及调用期间新增的消息。
checkpoint 沿用上游同一事务提交修订和 state_events，管理诊断沿用上游检索与 disclosure 判定。
前端模型、hooks、views、宿主适配和组件适配的边界由 Oxlint 约束。
机器可读契约以根目录 [`openapi.yaml`](../openapi.yaml) 为准，描述八个管理操作、请求、成功数据与错误结构。
`dashboard/src/contracts/generated.ts` 由 `pnpm generate:api` 生成，不手工修改。
`ApiRequest` / `ApiResponse` 直接引用生成的 operation 类型；Zod 用 `satisfies` 检查传输兼容性，
并继续处理未知输入、旧日志默认值、深层只读和版本一致性等领域约束。
JSON 扩展内容在生成类型中使用 `unknown`，运行时再由 Zod 递归校验，不使用 `any`。
生成类型不会代替运行校验，也不替换 `ManagementClient` 注入接口或宿主桥接器。

`tests/test_api_contract.py` 校验真实路由/业务输出并导出临时样本；前端跨语言测试用同一 YAML 和 Zod 双重验证。
Mock 返回值也对照 YAML 校验。契约未同步生成类型、实现输出不符、样本缺失或操作覆盖不全都会使 CI 失败。
宿主集成测试在 AstrBot 可用时另行校验真实响应；独立 CI 不依赖宿主启动。
完整开发命令见 [前端工程说明](../dashboard/README.md#接口契约与类型生成)。

## 全局约束

1. 单文件 ≤ 300 行，尽量 150
2. `core/` `store/` `recall/` 不 import `astrbot`
3. 只有 `store/` 写 SQL；`store/__init__.py` 只负责组合
4. 所有函数带类型标注
5. 每个文件头部有 docstring：职责一句话


---

# v0.3.1 implemented contracts

These contracts are additive to the earlier document.

## core/source.py

```python
@dataclass(frozen=True)
class Source:
    id: str
    turn_id: str
    session_id: str
    speaker_id: str
    role: str
    text: str
    at: str = ""
    reply_to: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

def make_source_id(*, event_id: str = "", session_id: str, speaker_id: str,
                   role: str, text: str, at: str = "") -> str: ...
```

Source is append-only. Both user and assistant messages are Source rows.

## app/contracts.py

```python
@dataclass(frozen=True)
class DialogueTurn:
    session_id: str
    speaker_id: str
    role: str
    text: str
    at: str = ""
    source_id: str = ""
    topic_id: str = ""

@dataclass(frozen=True)
class WriteOutcome:
    written: int = 0
    skipped: int = 0
    ids: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    model_failed: bool = False
    retryable: bool = False
```

## core/retrieval.py

```python
@dataclass(frozen=True)
class RetrievalCandidate:
    artifact: Artifact
    activation: float = 0.0
    lexical: float = 0.0
```

`lexical` is reserved for normalized BM25 or another pluggable lexical retriever.
语义相似度不得填入 lexical。本次不实现本地向量检索，不新增占位字段。

## store repositories

```python
class ArtifactRepository:
    def commit(self, art: Artifact, *, expected_revision: int, op: str,
               reason: str = "", source_ids: tuple[str, ...] = (),
               state_events: tuple[StateEvent, ...] = ()) -> None: ...
    def by_source_ids(self, source_ids: list[str]) -> list[Artifact]: ...
    def history(self, node_id: str) -> list[dict]: ...

class SourceRepository:
    def append_sources(self, sources: list[Source]) -> int: ...
    def recent_sources(self, *, since: str, limit: int) -> list[Source]: ...
    def source_umos(self, source_ids: list[str]) -> dict[str, str]: ...
```

Artifact commit is atomic across node head, append-only version, evidence, state events and
ledger. Source admission is atomic across blobs, sources and extraction_state.

## app/checkpoint.py

```python
class CheckpointManager:
    def record(self, art: Artifact, at: str = "") -> None: ...
    def flush(self, now: str = "") -> int: ...
    def due(self) -> bool: ...
```

Checkpoint commits the revision and its StateEvent in one transaction.

## core/disclosure.py

```python
@dataclass(frozen=True)
class RecallScene:
    session_id: str
    speaker_id: str
    owner_id: str = ""
    present_ids: tuple[str, ...] = ()

def decide(art: Artifact, scene: RecallScene, relevance: float,
           origin_sessions: Iterable[str] = ()) -> DisclosureDecision: ...
def safe_text(art: Artifact, level: DisclosureLevel) -> str: ...
```

Levels are full, paraphrase, hint and silence. Cross-session content never receives raw text.

## recall/retriever.py

```python
class GraphRetriever:
    def retrieve(self, query: str, pool: list[Artifact]) -> list[RetrievalCandidate]: ...

class HybridRetriever:
    def __init__(self, graph: Graph, cache: Cache,
                 index: BM25Index | None = None) -> None: ...
    def retrieve(self, query: str, pool: list[Artifact]) -> list[RetrievalCandidate]: ...
```

二者复用 `app.ports.Retriever` 协议。HybridRetriever 保留图激活、按 ID 去重并补充 lexical；
候选仍为调用方提供的 pool。索引首次使用时从活跃缓存建立，Cache.version 改变后重建；
计分所用的文档数、df 和平均长度只来自本次 pool，不增加 SQL 或网络调用。

## recall/tokenizer.py 与 recall/bm25.py

```python
def tokenize(text: str) -> list[str]: ...

class BM25Index:
    def __init__(self, calibration_c: float = 8.0) -> None: ...
    def rebuild(self, artifacts: list[Artifact]) -> None: ...
    def put(self, art: Artifact) -> None: ...
    def remove(self, artifact_id: str) -> None: ...
    def search(self, query: str, pool: list[Artifact]) -> dict[str, float]: ...
```

分词小写化、移除非字母数字、保留重复字符 bigram；单字符保留自身，空/纯标点无词项。
不维护人工停词表。标签各自分词，不能在相邻标签之间拼出新词项。
put 按 ID 新增或替换，只索引 active；search 返回本次 pool 中正分候选的 ID→分数。
正文与标签分别计算 BM25（k1=1.2、b=0.75），经 `s/(s+C)` 后按 0.75/0.25 融合，
当前 C=8。无命中为零，分数范围 [0,1]；calibration_c 必须为有限正数。

## recall/pipeline.py 的可选检索器

def build_block(cache: Cache, graph: Graph, artifacts: ArtifactStore,
                sources: SourceStore, umo: str, text: str,
                private: bool, conf: Conf, owner_umo: str, speaker: str = "",
                log: Callable[[str], None] = lambda _msg: None, *,
                dry_run: bool = False,
                hybrid_retriever: Retriever | None = None) -> tuple[str, dict]: ...
```

`bm25_enabled=false` 时继续使用 GraphRetriever；启用时使用注入检索器，缺省可构造 HybridRetriever。
配置默认开启；未提供 bm25_enabled 时也使用混合检索，显式 false 可恢复原检索路径。
插件入口与 ManagementService 传递同一长生命周期实例。WebUI 诊断仍 dry_run，不消耗指定交付状态。
新配置 bm25_weight 默认 1.0，由管线显式传入 select 的 lexical_weight；函数默认 2.0 保留旧调用兼容。
显式关闭 bm25_enabled 时不读取 bm25_weight，忽略残留的无效权重配置。
不改变已存在的 scope、披露、证据阈值或预算规则。实现决策与限制见 [ISSUE-0024](issues/ISSUE-0024.md)。

## v0.3.2 extraction projection and capacity

```python
@dataclass(frozen=True)
class ExtractionState:
    source_id: str
    turn_id: str
    session_id: str
    topic_id: str = ""
    state: str = "pending"
    attempts: int = 0
    next_attempt_at: str = ""
    last_error: str = ""
    created_at: str = ""

class CapacityGovernor:
    def evaluate(snapshot: CapacitySnapshot) -> CapacityDecision: ...
```

`extraction_state` contains queue metadata only; dialogue content remains in
immutable Source. `pending_extractions(now="")` joins both tables to rebuild the
projection in creation order; passing `now` skips rows still inside their retry
backoff. States are `pending`, `retrying`, `deferred`, `extracted` and `dead`.
Success moves to `extracted`; failure increments `attempts`, sets
`next_attempt_at` with bounded exponential backoff (30s doubling, capped at 1h)
and moves to `dead` after `extraction_max_attempts`; neither path deletes Source.

Capacity states are `normal`, `pressured`, `saturated` and `protective`.
Actions are `schedule_extraction`, `raise_batch_size`, `backpressure`,
`compact_artifacts`, `forget_expired`, `degrade_recall`, `trim_trace` and
`alert`. `CapacityDecision.pressure` is the 0..1 ratio to the hardest limit.
`backpressure` closes ingestion admission: `Buffer.add(deferred=True)` writes
Source plus a `deferred` extraction state, and `store.extraction.release_deferred()` promotes
parked rows back once the governor returns to `normal`. Extraction batches are
selected round-robin across sessions. Thresholds accept `capacity_thresholds`
(a JSON object in plugin config) or `SEEKMEMORY_CAPACITY_<FIELD>` environment
overrides. Source deletion is never a capacity action.


## Reinforcement truth

`recall.assemble.build_with_meta()` returns `(text, final_ids, dropped_ids)`. `build_block()` exposes the same values as `final_ids` and `dropped_ids`. Only `final_ids` are recorded in the checkpoint after a successful assistant response. Checkpoint hits use a cooldown window; repeated recalls of the same Artifact inside that window count once.

## Impression lineage consistency

When an impression is reinforced or reworded, `lineage.sources` is the union of the old and incoming evidence.
`lineage.derived_from` records the incoming abstraction; it never records the artifact's own id.
A cache removal follows a successful retirement commit; a failed commit leaves the active cache entry intact.

## Source evidence recall

`RecallService.build()` remains the only recall composition path. Memory is first:
the normal Artifact retrieval and selection run before Source evidence is considered.
Only when the selected Artifact count is below `min(2, recall_k)` and
`intent_of(text) != "none"` may the pipeline issue exactly one
`SourceStore.recent_sources(since=..., limit=...)` query and one
`ArtifactStore.by_source_ids()` batch. Source candidates may cross sessions; the
permission gate remains `AccessService`, and the output privacy remains the existing
Artifact visibility/disclosure decision. Source ids are internal evidence only: Source
text is never rendered into the block, info, logs or assembly. Discovered Artifacts are
deduplicated against selected Artifacts, filtered by visible/deliverable/valid/window
rules, and appended only up to remaining `recall_k` capacity before the single final
disclosure/assembly pass. Pinned persona/impression never gates this query.

The query results are content-free counters such as `enabled`, `candidates`,
`artifacts`, `picked` and `matched`. `source_recall_enabled=false` restores the legacy
empty-recall info shape. The fallback never writes Source, delivery state or
reinforcement; only assembled Artifact ids can be marked delivered as before.

## Extraction call budget and usage

`chunk_turns()` keeps the original turn-only `MAX_TOPIC_TURNS` behavior. `IngestService`
records exact `usage_in`/`usage_cached`/`usage_out` from each `ChatResponse` on
`WriteOutcome` and exposes a content-free cumulative `usage_snapshot()`.

`dream_max_calls` (default 12) is the primary Dream budget. `IngestService.flush(...,
max_calls=...)` checks before every real extraction call, so unstarted pending rows stay
recoverable. `DreamCycle` passes the remaining call budget and records
budget/usage/stopped in its summary. `dream_token_budget` remains an optional secondary
guard checked before the next batch; it can allow at most one-call slack. Maintenance
still runs for committed work. A budget of 0 disables only the hard stop where
applicable; usage is still recorded.

## Temporal validity and query windows

`recall.temporal.valid_at()` excludes Artifacts outside `valid_from`, `valid_to` or `expires` before retrieval.
`query_window()` resolves common relative expressions (`today`, `tomorrow`, `next week`, `next month`, etc.)
into an inclusive date range; memory candidates outside that range are excluded when the query contains one.
Invalid or missing dates fail open for ordinary queries, while an explicit temporal window requires a usable event date.


## Database migration and continuity

Opening an older database adds missing node columns and copies legacy `versions` rows into `artifact_versions` with `op=migrate`. Existing payloads remain readable through `history()`. The continuity regression covers extraction, commit, recall and a corrected revision in one sequence.


## Two-sided episodes

Assistant replies enter the Source-backed projection with `role=assistant`, `turn_id` and `reply_to`.
The actual parent determines the topic even if wording differs. Batches preserve adjacent pairs;
if a parent was processed earlier, extraction reads it as context without marking it pending again.
Rendering never silently trims original rows after parent recovery.


## Self-impressions and persona

Optional `bot_action`, `bot_tone`, `bot_boundary` and `outcome` remain descriptive payload fields.
Only a valid `bot_behavior`, confidence >= 0.9 and a precise immutable user/reply pair qualify
an original scene for aggregation. The six values are defined in `core/bot_behavior.py`.
At least three different assistant Sources create a self-impression: `family=memory`,
`level=impression`, `about=self`, `subject_id=bot:self`, `scope=shared`, `said_by=inferred`.
New evidence revises the same impression id; the impression itself never increases the count.
Self-impression and persona text uses fixed generic templates, excluding user-specific free text.

Both persona entry points accept only qualified self-impressions. Persona has `subject_id=bot:self`,
one stable id and a maximum of three selected behavior traits. Text/evidence changes create a
revision; unchanged reruns do not. Its update and duplicate-head retirement use `commit_many`
before cache changes. Legacy user-derived persona is preserved in history but not injected.
No additional per-chat model or network call is introduced.


## Atomic batch writes

`artifacts.commit_many(writes, op=..., reason=...)` executes several artifact commits inside one SQLite transaction. `merge_similar()` uses it to create the impression and retire all members atomically; a failed member write leaves the cache and database unchanged.


Lifecycle expiry and retention decay also use one `commit_many()` transaction: either all selected Artifacts become `forgotten`, or none do and the cache remains intact.


## Persona timeline

The optional `persona` status object includes stable id, current text and ordered revisions.
Each revision optionally includes `derivedFrom` and `sourceIds`, read from its own historical
header. Missing historical lineage yields empty lists. Raw dialogue is loaded only through
the authenticated detail interface and filtered by the selected version's source ids.
The read-only panel can open supporting impression snapshots whose evidence fits that version;
missing links are explicitly shown, and late asynchronous replies cannot replace a new selection.


## Superseding extraction

An extraction item may include an optional `supersedes` exact-text hint. After the new Artifact commits, `IngestService.extract()` finds an active memory with the same subject and scope whose text matches that hint and sets its `valid_to` to yesterday, so recall excludes the old fact while the Source and version history remain intact.


## Evaluation and live probe

`scripts/snapshot_db.py --source ... --destination ...` creates a WAL-consistent SQLite snapshot. `scripts/live_probe.py` opens a database in SQLite read-only mode and reports source/node/persona counts, extraction states and ledger validity. `benchmarks/real_eval.py` runs extraction against an OpenAI-compatible endpoint and reports parse/schema/expected-text recall; it is manual and not part of CI.


## Runtime persistence and adapter

`JsonStateStore` persists SessionState atomically in the plugin data directory, so observe-only runtime state survives restarts. `adapters/astrbot_runtime.py` is the only place that maps host message events into `RuntimeInput`; `app/runtime` remains host-agnostic.


## Runtime scheduler

`app/runtime/scheduler.py` separates a pure `TimingPolicy` from a read-only `Scheduler`.
`TimingPolicy.evaluate(state, now)` reports a `DueRun` for an elapsed wait or retry deadline,
and `Scheduler.due(session_ids, now)` reads persisted state for each session and returns the
due runs. The scheduler performs no sends, generation, mutation, sleeping, host imports or
wall-clock reads. One broken session is skipped without blocking other sessions. Proactive
generation is not implemented and has no timing path in this layer.

## Runtime actions and episodes

`AstrBotActionPort` provides the host send port and `AstrBotModelGateway` wraps provider lookup plus `text_chat`. `AgentRuntime.dispatch_deferred()` owns the deferred lifecycle: it claims the session, builds recall context, calls `ModelGateway.complete()`, sends through `MessageSender`, records through `RunRecorder`, marks delivery and schedules bounded retry on failure. `RuntimeWorker` selects due sessions and the `AstrBotPlugin` composition callback maps the latest user Source into `RunContext`; `main.py` itself is composition only. `RunRecorder` is the single write-back service for assistant Source, the pending extraction buffer and `EpisodeRecord`. It is idempotent per `run_id`: repeated callbacks do not duplicate Source, checkpoint reinforcement or episode rows. `RepoStateStore` and `RepoEpisodeStore` persist mutable session state and append-only runtime episodes in SQLite tables (`runtime_state`, `runtime_episodes`); no message bodies are stored. `runtime_episodes.run_id` correlates the episode with the admin run trace, and a partial unique index protects non-empty run ids. `runtime_episodes.delivered` is written by the `after_message_sent` hook, not by model response generation. Runtime writes are fail-open and episode rows are pruned by `runtime_episode_retention_days` / `runtime_episode_max_rows`. JSON stores remain a fallback for tests/export only. `ToolPolicy` is advisory until the host exposes a hard deny path; `on_using_llm_tool` and `on_llm_tool_respond` record tool names, arg-key counts and result status. `runtime_gate_enabled` is false by default; when true, `event.should_call_llm()` follows the runtime decision.

## Agent run traces

`run_traces.jsonl` contains one whitelisted event per line, separate from SQLite runtime episodes.
It stores no message bodies, user/session identifiers, prompts, responses, tool arguments or
results. Tool names, generated Artifact IDs, counts, timestamps and fixed enums are allowed.
`trace_retention_days` defaults to 7 (1–365); `trace_max_rows` defaults to 5000 (1–5000 events).
Cleanup runs on startup, append and snapshot. Capacity cleanup may evict up to 1% in a batch;
ID lists and disclosure maps are capped at 256. Incomplete timelines are flagged.

Run filters overlap. `not_recalled` means a completed recall observation selected no memory;
unknown/skipped/failed observations do not establish this. `recalled_but_withheld` means at least
one memory received silence disclosure. `recalled_and_injected` means final_ids entered the
request context. `fallback_used` means recent_profile/recent_topic was selected. None proves a
model used memory in its answer. `delivered` records the separate host message-sent callback.
Tool-return status stays unknown; uncorrelated or overlapping tool calls have no guessed duration.
Writes fail open and expose persistence_error; missing diagnostic events never retry business
operations or alter recall/disclosure/tool policy. This log is not an immutable business ledger.


## Runtime timing and unread state

`RuntimeInput.at` must be populated from the host event timestamp. `SessionState` tracks `wait_until`, `quiet_until`, `cooldown_until`, `last_unread_seq`, and `read_through_seq`; `WakePolicy` returns a `RunDecision` (`WAIT` during an active wait, `IGNORE` during quiet/cooldown), and `mark_delivered()` advances the read-through watermark. `AgentRuntime` does not expose test-only quiet/wait/mark-read mutators; callers use the production transitions. These are runtime state, not Source or Artifact fields. The only decision actions are ignore, observe, wait and reply; proactive/sleep placeholders are not part of the runtime.

## Runtime memory context

`inject_memory` in `adapters/astrbot_hooks.py` asks `AgentRuntime.build_context()` through `MemoryContextPort`; `SeekMemoryContextAdapter` delegates to `RecallService`, which owns the existing recall pipeline. Runtime owns the boundary and host injection no longer calls `build_block` directly.


## Runtime integration policy

Wake attention is prioritized as private > direct (@ / reply-to-bot) > addressed (name / question / keyword) > ambient. Private and direct attention cannot be muted by wait, quiet or cooldown. `wait` is a defer for ambient group traffic and must carry a reply path; it is never a hard mute for direct attention. `ToolPolicy.filter_tool_set()` removes disallowed tools from `req.func_tool` before the model sees them. The runtime loop asks `Scheduler` / `TimingPolicy` for due persisted runtime sessions; a due ambient wait dispatches a deferred reply through the host provider, persists the assistant Source, records an episode, and retries provider/send failures with bounded per-session backoff (`runtime_dispatch_max_attempts`, `runtime_dispatch_backoff_seconds`). Proactive decisions remain trace-only for now.
