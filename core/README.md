# core：领域与端口 / Domain and ports

`core/domain/` owns domain values and rules; `core/port/` declares the external
capabilities those rules need. Neither directory owns SQL, model calls, SDK
integration or application orchestration. / 领域实现与所需外部协议分开；两者都不负责
SQL、模型调用、宿主 SDK 或用例编排。

| 区域 / Area | 实现归属 / Ownership |
|---|---|
| `domain/memory/` | Source、Artifact、版本、检索候选、强度、披露、图 |
| `domain/character/` | 人格文件、人格包、形象及自身行为规则 |
| `domain/social/` | 关系快照、关系规则及互动策略 |
| `domain/operations/` | 容量与无正文追踪投影 |
| `families/` | 各 Artifact family 的 payload 校验 |
| `port/` | 图写入与树只读协议 `GraphArtifactStore`、`TreeEdgeReader` |

`core.domain` exports the approved domain API; `core.port` exports the required
protocol. Use the owning module when a narrower import is helpful. The old
`core.<module>` and historical `core.domain.<module>` imports alias their owning
modules (including patchable module globals); `core._legacy` registers both old import families without scattered
forwarding files. `core.ports` aliases the graph
port for compatibility. Graph
orchestration receives a store through its port; tree orchestration and its
ports belong to `services.TreeService` and `app.ports` respectively. / 旧导入路径
暂作兼容入口；图由注入仓储提供能力，树属于服务层和应用端口。

Design and contracts / 设计与契约：
[中文设计](../docs/zh/architecture/modules/core.md) ·
[English design](../docs/en/architecture/modules/core.md) ·
[架构总览](../docs/zh/architecture/overview.md)
