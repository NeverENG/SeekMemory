# maintain：生命周期与人格沉淀

## 职责

maintain 对已提交 Artifact 做生命周期转变、相似合并、印象修订、关系连边和自我人格沉淀。MaintenanceService 编排周维护；规则本身尽量保持确定性并通过 ArtifactStore 写入。

## 生命周期与合并

- decay.py 只处理 active memory，跳过 fact；其余记忆按 strength、shape、时间计算留存率，低于阈值后写入 forgotten 修订。Persona 等其他 family 不参与这条衰减规则。
- lifecycle.py 按 expires / valid_to 把已到期 active Artifact 改为 forgotten；Source 与版本历史都保留。
- merge.py 仅当 active scene/detail 数量超过 500 时检查最早的一批候选。候选先按 subject_id 和 scope 隔离，再按字符二元组相似度聚类；至少三条才形成 impression。新节点的 derived_from 指向成员，成员进入 merged。整组通过 commit_many 原子提交。
- impression.py 在抽取新印象时只与同 subject、同 scope 的 active impression 比较：近乎同文时合并 evidence 并强化原节点；更完整的新说法则在原 ID 上追加 revision，退休重复候选。
- link.py 在同 scope active memory 间建立受数量限制的 similar / temporal 边。因果边没有自动推断。

## 机器人自我印象与 Persona

self_impression.py 只聚合六类固定 bot_behavior。每次场景必须指向实际 assistant Source 和同会话、由 reply_to 确认的 user parent；多个不同的 assistant Source 才算独立行为观察。达到至少三次且 confidence 不低于 0.9 后，按行为类别修订稳定 ID 的共享 self impression。共享文本来自固定模板，不复用用户私密自由文本。

persona.py 只从已验证的 self impression 选择最多三个行为类别。已有种子人格在原 Artifact ID 上演化；每次更新保留来源与版本历史。MaintenanceService 对已 bootstrap 的 persona 可按周期做一次有界模型综合；模型失败时保留旧人格。无种子旧安装可走确定性兼容路径。persona-seed 文件和演化流程见[人格种子指南](../../guides/persona-seed.md)。

## 未接入主流程的规则

reflect.py 能从相邻用户消息计算 wrong/right 信号，但仓库当前没有生产调用方；它不是自动反思、记忆修正或强化路径。任何文档或配置不能把它描述成已启用的线上功能。
