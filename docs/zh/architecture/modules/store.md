# store：持久化与派生读模型

## 职责

store 是唯一 SQL 边界。Store 在 [store/__init__.py](../../../../store/__init__.py) 组合一个 SqliteDatabase 连接和各领域仓储；连接共用使跨表写入可在同一事务内完成。

## 仓储分工

| 仓储 | 持久化内容 |
|---|---|
| ArtifactRepository | 当前 nodes、内容 blobs、artifact_versions、版本级 artifact_evidence、edges、state_events 和提交账本 |
| SourceRepository | 不可变 Source 与只读 Source 查询 |
| ExtractionRepository | Source admission 的 extraction_state 投影、重试/退避/deferred/extracted/dead |
| LedgerRepository | 追加式哈希链条目和校验 |
| RuntimeStateRepository | 按会话可变的运行时状态 |
| RuntimeEpisodeRepository | 追加式运行结果元数据和保留清理 |
| DreamRepository | 每日 Dream 执行状态与汇总 |
| StoreMetricsRepository | 容量观测的只读计数 |
| TraceStore | 单独的有界 JSONL Agent Run Trace，不走业务 Artifact 版本链 |

SQL schema 和迁移由 SqliteDatabase 管理；仓储共享连接，不创建各自数据库文件。数据库打开时创建 schema 并补充兼容迁移。

## 事务边界

- Artifact commit 校验 expected_revision 与下一 revision，并在单个事务中写 blob、node head、版本快照、版本级证据、state event 和 ledger。commit_many 把一组更新放在一个事务中，任何一条失败则整组回滚。
- extraction admission 在同一事务内写 Source blob/row 与队列状态。队列正文通过联接 Source 读取；成功/失败只更改队列状态，不删除原始消息。
- Source ID 采用幂等写入。重复 Source 不会变成新的事实行。

## Cache

Cache 仅持有 active Artifact，并维护 family、level、subject 索引。读路径用它构建候选池。put/remove/load 更新单调递增的 version；HybridRetriever 用 version 确认自己的内存索引是否过期。Cache 不能取代数据库提交，也不应在 CAS 失败时提前更新。

## 恢复与诊断

Artifact 版本快照和证据是审计事实；ledger 的哈希链用于检查账本连续性。Runtime episodes、Dream 状态和 Run Trace 分属不同用途，不能拿诊断轨迹代替 Artifact 变更账本。旧行解析、schema 演进和仓储实现都留在 store。
