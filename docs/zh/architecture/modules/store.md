# store：持久化与派生读模型

## 职责

store 是唯一 SQL 边界。Store 在 [store/composition.py](../../../../store/composition.py) 组合一个 SqliteDatabase 连接和各领域仓储；连接共用使跨表写入可在同一事务内完成。

## 仓储分工

| 仓储 | 持久化内容 |
|---|---|
| ArtifactRepository | 当前 nodes、内容 blobs、artifact_versions、版本级 artifact_evidence、edges、state_events 和提交账本 |
| SourceRepository | 不可变 Source 与只读 Source 查询 |
| ExtractionRepository | Source admission 的 extraction_state 投影、重试/退避/deferred/extracted/dead |
| LedgerRepository | 追加式哈希链条目和校验 |
| RuntimeStateRepository | 按会话可变的运行时状态 |
| RuntimeEpisodeRepository | 追加式运行结果与无正文动作元数据，以及共享保留清理 |
| DreamRepository | 每日 Dream 执行状态与汇总 |
| StoreMetricsRepository | 容量观测的只读计数 |
| TraceStore | 单独的有界 JSONL Agent Run Trace，不走业务 Artifact 版本链 |

SQL schema 和迁移由 SqliteDatabase 管理；仓储共享连接，不创建各自数据库文件。数据库打开时创建 schema 并补充兼容迁移。

## 事务边界

- Artifact commit 校验 expected_revision 与下一 revision，并在单个事务中写 blob、node head、版本快照、版本级证据、state event 和 ledger。commit_many 把一组更新放在一个事务中，任何一条失败则整组回滚。
- extraction admission 在同一事务内写 Source blob/row 与队列状态。队列正文通过联接 Source 读取；成功/失败只更改队列状态，不删除原始消息。
- Source ID 采用幂等写入。重复 Source 不会变成新的事实行。
- 运行时动作行在 `runtime_episodes` 中增加可空动作身份和状态元数据。已有 episode 行保留原值；迁移补充默认值、保留每个普通 run 一条 episode 的唯一索引，同时允许动作行共享 run ID。部分唯一索引确保每个 action 至多一个终态；触发器会忽略终态之后到达的尝试。动作行沿用 episode 的清理上限。
- `runtime_state` 继续以 JSON payload 保存 `SessionState`；后续回复窗口按说话人保存在 `followup_by_speaker`，旧额度字段不再解释为运行时状态。

## Cache

Cache 仅持有 active Artifact，并维护 family、level、subject 索引。读路径用它构建候选池。put/remove/load 更新单调递增的 version；HybridRetriever 用 version 确认自己的内存索引是否过期。Cache 不能取代数据库提交，也不应在 CAS 失败时提前更新。

## 恢复与诊断

Artifact 版本快照和证据是审计事实；ledger 的哈希链用于检查账本连续性。Runtime episodes、Dream 状态和 Run Trace 分属不同用途，不能拿诊断轨迹代替 Artifact 变更账本。旧行解析、schema 演进和仓储实现都留在 store。

## 接口与文件归属

`store/domain.py` 明确导出仓储集合、仓储、缓存、追踪及受支持的账本帮助函数，原包入口和实现路径保持兼容。`store/ports.py` 仅声明缓存读取接口与追踪时钟；SQLite 和文件系统类型在这个外部适配层保留为具体类型。store 文件不依赖 app、services 或宿主适配器。

| 文件 | 职责与资源归属 | 逻辑复杂度及耦合 |
|---|---|---|
| `composition.py` | 创建仓储对象，共同借用一个自有 SQLite 连接，`close()` 关闭连接 | 低：仅组装，不包含 SQL |
| `sqlite.py` | 打开和关闭连接，初始化既有结构并委托迁移，保留现有时间帮助函数 | 低至中：SQLite 和文件系统适配 |
| `migrations.py` | 有序执行兼容字段、旧版本、索引和触发器步骤 | 中：共享迁移事务，语句顺序不变 |
| `serialization.py` | 既有 JSON 编码与旧值解析，无 SQL 或时钟 | 低：纯转换，持久化字节稳定 |
| `artifact_codec.py` | 记忆数据行及头部转换，原 SQL 导入保留兼容别名 | 低至中：纯转换 |
| `artifact_sql.py` | 既有记忆 SQL 模板，不执行语句 | 低：仅语句 |
| `artifacts.py` | 版本读取及预期版本单次和分组提交、证据、事件、账本，以及明确的图和父字段写入 | 高：多表事务所有者，不写缓存 |
| `sources.py`、`extraction.py` | 不可变证据、队列接纳及结果；入队共用一个事务 | 中：证据和队列职责明确，不调用模型 |
| `ledger.py` | 唯一链条编码与哈希，以及加入调用方事务的追加函数 | 中：稳定字节契约，帮助函数不独立提交 |
| `runtime_state.py`、`runtime_episodes.py`、`dreams.py` | 分别负责调度状态、审计及每日运行事务 | 中：不拥有记忆规则 |
| `metrics.py` | 通过借用连接读取容量用量 | 低：只读查询 |
| `cache.py`、`run_trace.py` | 派生有效记忆索引及独立诊断 JSONL | 中：进程状态和文件锁，与业务事实分开 |

仓储借用连接，不关闭连接；公开写入操作负责事务。`_commit_conn`、`write_source_conn`、`append_ledger_conn` 加入调用方事务，不能独立提交。`set_parent` 是既有的独立兼容字段写入，不是记忆版本与连接的整体事务。

`tests/test_store_interface_contract.py` 验证明确接口的对象身份、帮助函数兼容及共享连接；原有迁移、内核、抽取、运行动作及导入顺序场景验证行为，不能据此声称真实宿主或模型已经运行。

## 失败时的发布与清理

Cache 先准备完整的临时索引，再替换现有视图并递增 `version`。仓储读取或数据行准备失败时，所有旧索引和变化标记都保留。`put()` 在移除原值前准备正文及索引键。缓存沿用单执行线程的归属约定，不增加跨线程事务保证。

SQLite、结构初始化或仓储构造的任一阶段失败时，关闭刚打开的连接，包含取消情况。`commit()` 和非空 `commit_many()` 在写入前验证同一允许操作清单；分组冲突仍使整组事务回滚。结构、迁移顺序、持久化值和时间转换不变。

`TraceStore.append()` 在验证或文件写入失败时设置 `persistence_error` 并抛错，保留上次已保存的内存快照。面向宿主的 `RunTracer` 隔离普通诊断异常，因此失败追踪既不会被误确认为成功，也不会中断聊天。诊断快照读取可能裁剪保留行；裁剪失败时报告持久化状态，保留上次已保存状态。诊断不能替代业务提交凭据。

`tests/test_store_failure_recovery.py` 覆盖缓存读取失败、部分重建或替换准备失败、连接清理、无效分组操作及追踪替换失败。撤销恢复提交无需数据迁移。
