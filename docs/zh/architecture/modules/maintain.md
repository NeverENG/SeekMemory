# maintain：生命周期与人格沉淀

## 职责

maintain 对已提交 Artifact 做生命周期转变、相似合并、印象修订、关系连边和自我人格沉淀。MaintenanceService 编排周维护；规则本身尽量保持确定性并通过 ArtifactStore 写入。

## 生命周期与合并

- decay.py 只处理 active memory，跳过 fact；其余记忆按 strength、shape、时间计算留存率，低于阈值后写入 forgotten 修订。Persona 等其他 family 不参与这条衰减规则。
- lifecycle.py 按 expires / valid_to 把已到期 active Artifact 改为 forgotten；Source 与版本历史都保留。
- merge.py 仅当 active scene/detail 数量超过 500 时检查最早的一批候选。候选先按 subject_id 和 scope 隔离，再按字符二元组相似度聚类；至少三条才形成 impression。新节点的 derived_from 指向成员，成员进入 merged。整组通过 commit_many 原子提交。
- impression.py 在抽取新印象时只与同 subject、同 scope 的 active impression 比较：近乎同文时合并 evidence 并强化原节点；更完整的新说法则在原 ID 上追加 revision，退休重复候选。两条变更通过 commit_many 原子提交，统一记录为 merge，reason 区分强化或改写；提交成功后才更新缓存。写入失败或版本冲突向服务层传播，保留合并前的两条记录及缓存。
- link.py 在同 scope active memory 间建立受数量限制的 similar / temporal 边。因果边没有自动推断。

## 机器人自我印象与 Persona

self_impression.py 只聚合六类固定 bot_behavior。每次场景必须指向实际 assistant Source 和同会话、由 reply_to 确认的 user parent；多个不同的 assistant Source 才算独立行为观察。达到至少三次且 confidence 不低于 0.9 后，按行为类别修订稳定 ID 的共享 self impression。共享文本来自固定模板，不复用用户私密自由文本。

persona.py 只从已验证的 self impression 选择最多三个行为类别。已有种子人格在原 Artifact ID 上演化；每次更新保留来源与版本历史。MaintenanceService 对已 bootstrap 的 persona 可按周期做一次有界模型综合；模型失败时保留旧人格。无种子旧安装可走确定性兼容路径。persona-seed 文件和演化流程见[人格种子指南](../../guides/persona-seed.md)。

## 关系状态巩固

relationship.py 只消费原始 `relationship-v1` 观察，并先校验 confidence、不可变 Source 是否存在、user Source 是否属于 Artifact subject，以及证据是否只有一种 private/group/unknown scope。private 证据权重为 `1.0`，group/unknown 为 `0.5`。纯规则将 counted ID 与 reviewed ID 分开，按 reason 限制同轮重复，并把单次 affinity revision 限制在 `0.10`。Maintenance 通过 expected-revision CAS 提交稳定的按 subject Relationship Artifact，成功后才更新 Cache。`relationship_mode=off` 跳过巩固；默认的 `observe` 与显式 `enforce` 都会巩固并持久化派生状态。observe 模式可以计算候选交互档案，但拒绝回复仍必须同时满足 `relationship_mode=enforce` 和 `runtime_gate_enabled=true`。

## 未接入主流程的规则

reflect.py 能从相邻用户消息计算 wrong/right 信号，但仓库当前没有生产调用方；它不是自动反思、记忆修正或强化路径。任何文档或配置不能把它描述成已启用的线上功能。

## 接口与计划归属

`maintain/domain.py` 明确导出受支持的维护用例及不可变 `RevisionWrite`、`RevisionPlan` 数据。`maintain/ports.py` 复用既有记忆、原始消息及缓存协议。旧导入和返回值继续可用。一个 `RevisionPlan` 对应一组事务，不同计划或关系主体之间不是整体原子操作。资源构造及关闭属于组装方。

| 文件 | 职责及副作用 | 逻辑复杂度和耦合 |
|---|---|---|
| `decay.py`、`lifecycle.py` | 读有效视图→准备版本组→提交→移除缓存项 | 低：有序读写，一组原子提交 |
| `expiry_policy.py` | 既有留存及到期版本判断 | 低至中：给定数据，不调用仓储 |
| `merge.py`、`merge_policy.py` | 读取主体及范围组，聚类并准备一个新建及停用版本组，提交后更新缓存 | 中至高：各聚类原子，纯聚类及措辞与读写分开 |
| `impression.py`、`impression_policy.py` | 读取对手，匹配并准备新旧版本，一个原子合并 | 中：保留主体、范围和证据条件 |
| `self_impression.py`、`self_impression_policy.py` | 读取原始配对证据及引用事件，对观察分组并准备版本，提交后更新缓存 | 高：精确不可变配对及独立计数归属 |
| `persona.py`、`persona_policy.py` | 读取已验证自身候选，在一个版本组中准备保留设定的人格并停用重复人格 | 中：不将用户私密措辞晋升为全局人格 |
| `relationship.py` | 编排按主体的内核计划、校验、预期版本提交和缓存 | 中：主体事务彼此独立 |
| `relationship_evidence.py` | 读取精确原始证据及当前状态 | 中：只读，拒绝无效身份、范围或置信度 |
| `relationship_policy.py` | 准备替换内容及来源，并分类给定证据值 | 低至中：无读写，评分规则属于内核 |
| `link.py` | 可选有限图增强及旧预期版本持久化 | 中：可选连接与记忆事务分开 |
| `reflect.py`、`promote.py` | 无生产调用方的纯反思信号及已验证自身候选兼容入口 | 低至中：如实说明接线情况 |

不同匹配规则有意分开：印象 Dice、合并及反思 Jaccard、图建联 Dice 不能互换。印象匹配使用 app 的共享字母数字规则，不再导入召回实现帮助函数。此批不改变公式、时间转换、设定内容、提示词或持久化格式。接口及导入契约、既有证据、人格、身份、关系和失败场景验证移动后的阶段。

## 已准备写入的恢复

`MaintenanceService` 唯一持有一个 `MaintenanceWriter`。各任务准备精确 `RevisionPlan`，再由写入协调器使用既有单次或分组事务。数据库写入失败保留原计划及编号；预期版本冲突丢弃旧计划，不基于新正文重算或覆盖较新内容。提交成功后，在缓存操作前记录完成并消费计划。仅需缓存的补偿追踪已提交编号，读取数据库最新版本，不重复提交版本。

根据缓存推导新计划前，协调器先重试旧工作。仍未修好的视图明确报告 `maintenance_writeback_pending`，防止旧缓存重新创建自我印象或并列人格。最终缓存尚待补偿时，服务结果包含 `writeback_pending` 数量；后台纯补偿和停止流程可以重试，不执行模型或规则。模型综合的人格草案同样使用此协调器，提交失败后可以补写而不再请求模型。重新绑定既有调用方仓储及缓存字段时，保留已准备进度并使用当前资源。

自由函数接受可选关键字 writer；旧调用方保持返回形式及缓存失败传播，长期服务注入保留的协调器并延后仅需缓存的错误。不同版本组或主体仍是独立事务。补偿限当前进程，不增加持久任务表或崩溃、跨进程保证。已提交编号补偿委托给 app 共享能力，写入协调器仅保留语义计划。

`tests/test_maintenance_failure_recovery.py` 覆盖失败计划精确编号、连续缓存失败和较新版本、无并列人格、冲突版本组原子性以及不重复人格模型调用。撤销恢复提交无需数据迁移。

已提交编号的缓存补偿通过 `app.CacheRepairs` 共享；组装根将同一实例注入检查点、抽取、上下文及维护写入协调器。业务计划仍归各用例，按所有者计数避免无关补偿混入检查点待处理总数。
