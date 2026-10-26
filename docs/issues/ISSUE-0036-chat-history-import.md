# ISSUE-0036: Import private ChatLab history to initialize Bot persona and user memory

| Item | Value |
|---|---|
| ID | ISSUE-0036 |
| Priority | P1 |
| Status | in-progress |
| Owner | ImportService, ChatLab adapter, AstrBot management API |
| Date | 2026-10-26 |
| Related | GitHub #76; RFC-0001 |
| Affected version | main @ d4f7dd1 |

## Background

SeekMemory currently captures live messages and extracts memory through its existing Source-backed queue, but it has no supported way for an administrator to initialize a Bot from a user's historical private conversation. Replaying old messages through the live event path would assign import-time identity and time, couple imported traffic to live runtime behavior, and leave the administrator without a bounded preview or progress record.

The requested capability is to use one user's private ChatLab export to build both evidence-backed shared Bot behavior/persona and interaction memories scoped to that same user. This is the agreed scope for GitHub #76 and replaces that issue's original export, group-import, and CLI-first plan. The detailed product and API decisions are in [RFC-0001](../rfcs/RFC-0001-chat-history-import.md).

## Baseline and implementation status

- `core/source.py` has the live Source ID helper; it does not encode an external format/conversation/message identity tuple.
- `store/extraction.py` admits one Source and its `extraction_state` atomically. There is no bulk-import task or task-to-Source projection.
- `services/ingest_service.py` owns model extraction and Artifact writes. Dream triage can intentionally leave low-importance topics pending, so initialization must use the existing non-triage extraction behavior.
- `maintain/self_impression.py` and `maintain/persona.py` already require real paired Source evidence for shared `bot:self` behavior and persona.
- `webui/routes.py` authenticates management actions through the AstrBot request context. The plugin page bridge provides file upload support; the current management UI has no import workflow.
- This branch now adds the ChatLab adapter, `HistoryReader` port, import service,
  isolated task/Source store path, AstrBot API endpoints and administrator workflow.
- Full unit, contract and integration coverage passes locally. The 27 tests that require
  an installed AstrBot host remain skipped; the real upload-to-terminal API run is pending
  a non-production host/provider configuration and representative export from the Lead.

## Goals / scope

- Add an administrator-only AstrBot plugin page flow to upload, preview, confirm, monitor, retry, cancel, and abandon one import task.
- Accept only ChatLab v0.0.2 JSON and JSONL, one private conversation containing exactly one Bot and one target user.
- Resolve roles by exact platform IDs or explicit administrator selection; reject ambiguity and extra speakers.
- Require `platformMessageId` for every parseable message. Derive Source identity from `chatlab`, the confirmed target UMO, and the external message ID. Identical re-imports are idempotent; identity conflicts reject the import.
- Preserve event time, reply links, speaker attribution, and immutable Source evidence. Admit Source and extraction state through one bounded, transactional repository path.
- Send every valid historical topic through the existing non-triage extraction path. Store resulting user interaction memories only in the target user's UMO.
- Update shared `bot:self` only from qualified Bot-side behavior evidence, using the existing distinct-pair and confidence threshold; user messages must not become Bot personality evidence.
- Persist task summaries and task–Source progress, keep summaries for 30 days after terminal completion, and remove raw files according to the RFC lifecycle.
- Keep limits provisional until the Lead supplies representative QCE → ChatLab files: JSON 20 MiB / 100,000 messages, JSONL 512 MiB / 2,000,000 messages, and 1 GiB aggregate staging.
- After implementation, start SeekMemory in local/staging AstrBot and run the real upload-to-terminal API chain with non-production API access and representative records supplied by the Lead. Record sanitized evidence in the PR file.

## Non-goals

- Group history, multiple conversations per upload, multi-file batches, routine synchronization, user self-service, direct QQ login, and a ChatLab API connection.
- ChatLab export, a portable SeekMemory archive, and a CLI as the ordinary administrator entry point.
- New Artifact write paths, direct importer model calls, live Buffer replay, Dream importance triage, whole-instance weekly maintenance, or changes to existing Artifact schema.
- Real production validation by default. Production access or changes require separate explicit Lead authorization.

## Ownership and invariants

| Concern | Owner |
|---|---|
| ChatLab parsing and normalized message DTOs | Read-only format adapter |
| Upload staging and AstrBot request mapping | WebUI/AstrBot adapter |
| Role confirmation, Source identity, task orchestration | ImportService |
| SQL, bounded atomic Source/queue admission, import task records | `store/` repositories |
| Extraction and Artifact commits | `IngestService` / `ArtifactStore.commit()` |
| Shared self-impression and persona update | Existing maintenance/persona owner, exposed through a narrow import-specific operation |
| Admin authentication and lifecycle | Existing AstrBot management boundary and task runner |

Source remains append-only truth. Artifacts remain revisable interpretations with evidence, revision snapshots, and ledger entries. Importers cannot import storage/services/host code, write SQL, call models, or create Artifacts. No message bodies, credentials, or raw user identifiers may enter logs or task summaries.

## Acceptance criteria

- [x] The admin page accepts one JSON/JSONL file, previews safe metadata/counts/warnings, and requires explicit confirmation before processing.
- [x] Server endpoints enforce admin authentication for every import operation.
- [x] Unsupported versions, group files, structural errors, missing stable IDs, role ambiguity, extra speakers, and Source identity conflicts are rejected before formal admission.
- [x] Safely isolated JSONL line errors and invalid but identifiable rows are counted and skipped only after administrator confirmation; the result is marked partial.
- [x] Message IDs remain stable across JSON/JSONL and retries; same ID/same immutable fields skips, same ID/different fields rejects.
- [x] Historical Sources preserve chronological event time, role, speaker, target UMO, reply links, and content hashes; Source admission plus extraction state is atomic and bounded.
- [x] All valid topics are queued and processed without Dream triage; failed model calls or Artifact commits remain retryable and cannot silently mark a topic complete.
- [x] Extracted user memories remain scoped to the selected UMO. Shared `bot:self` persona updates use only qualifying paired Bot behavior evidence and existing thresholds.
- [x] Persistent task progress reports pending/extracted/failed counts by the task–Source association; task summaries and raw files follow the RFC retention lifecycle.
- [x] Synthetic tests cover parser formats, roles, identity/idempotency/conflicts, batching, failure recovery, privacy, task progress, API authentication, and target-scope behavior.
- [ ] After code completion and when the Lead supplies non-production API access and representative records, a local/staging AstrBot real-chain run is documented with sanitized API status codes, task transitions/counts, and persistence checks.
- [ ] The full repository test command passes; AstrBot boundary behavior is verified with the real host or a faithful staging copy. No production deployment is performed.

## Decision record

- 2026-10-26: Scope narrowed to initialization from one Bot–one target-user private ChatLab file, producing shared Bot persona evidence and target-user interaction memories; export/group/CLI-first requirements are outside this delivery.
- 2026-10-26: ChatLab v0.0.2 only; require stable `platformMessageId`, exact/explicit role mapping, task–Source progress, non-triage extraction, existing persona evidence gates, and provisional upload limits. See RFC-0001 for the full decisions.
- 2026-10-26: Confirmed the selected target member ID must match the user ID at the end of the target private UMO; identifiable third-party senders still reject the file even when their message row is otherwise invalid.

## Chinese translation

### 背景

SeekMemory 当前可通过 Source 队列处理实时消息，但没有管理员使用历史私聊记录初始化 Bot 的正式入口。把旧消息重新模拟为实时事件会把导入时身份和时间混入消息，并让历史流量影响实时处理，也无法提供安全预览和可追踪的进度。

本功能使用一个用户的 ChatLab 私聊导出，同时沉淀有证据支持的共享 Bot 行为/人格，以及仅归属于该用户的互动记忆。这是 GitHub #76 已确认的新范围，替代原 issue 中的导出、群聊导入和 CLI 优先计划。完整产品和 API 决策见 [RFC-0001](../rfcs/RFC-0001-chat-history-import.md)。

### 当前现状

- `core/source.py` 只有实时 Source ID helper，不能表达外部格式/会话/消息 ID 元组。
- `store/extraction.py` 可原子写入单条 Source 和 `extraction_state`，没有批量导入任务或 task–Source 关联。
- `services/ingest_service.py` 拥有模型提取和 Artifact 写入。Dream 分诊会有意保留低重要度话题待处理，因此初始化必须使用现有非分诊提取路径。
- `maintain/self_impression.py` 和 `maintain/persona.py` 已有基于真实配对 Source 证据的共享 `bot:self` 行为与人格沉淀门槛。
- `webui/routes.py` 通过 AstrBot 请求上下文认证管理接口，插件页面桥接器支持文件上传；当前管理界面没有导入流程。
- 目前没有生产可用的 ChatLab importer 或 ImportService。

### 目标范围

- 增加 AstrBot 插件管理员页面，支持上传、预览、确认、查看进度、重试、取消和放弃单次导入任务。
- 只接受 ChatLab v0.0.2 JSON/JSONL；每份文件只能包含一个 Bot 与一个目标用户的私聊。
- 通过精确平台 ID 或管理员明确选择角色；拒绝角色歧义和额外发言者。
- 每条可解析消息必须含 `platformMessageId`。Source 身份由 `chatlab`、确认后的目标 UMO 和外部消息 ID 生成。完全相同的重导入幂等；身份冲突整份拒绝。
- 保留事件时间、回复关系、发言者和不可变 Source 证据；通过有界事务路径同时写入 Source 与提取状态。
- 所有有效历史话题都走现有非分诊提取路径；用户互动记忆只能归属目标用户 UMO。
- 共享 `bot:self` 仅根据满足现有独立配对证据和置信度门槛的 Bot 行为更新，不把用户消息当作 Bot 人格证据。
- 持久化任务摘要和 task–Source 进度；终态后保留摘要 30 天；原始文件按 RFC 生命周期处理。
- 在 Lead 提供代表性 QCE → ChatLab 文件前，上传限制均为临时值：JSON 20 MiB/10 万条，JSONL 512 MiB/200 万条，全实例暂存 1 GiB。
- 实现后在本地/staging AstrBot 启动 SeekMemory；待 Lead 提供非生产 API 访问方式和代表性记录后，跑完真实上传到任务终态的 API 链路，并在 PR 文档记录脱敏证据。

### 非目标

- 群聊、一次上传多个会话、多个文件批处理、定期同步、用户自助上传、QQ 直接登录及连接 ChatLab API。
- ChatLab 导出、SeekMemory 便携归档，以及面向普通管理员的 CLI 入口。
- 新 Artifact 写入路径、导入器直接调用模型、模拟实时 Buffer、Dream 重要度分诊、全库周维护或既有 Artifact schema 改动。
- 默认进行生产真实链路验证。生产访问或修改需要 Lead 另行明确授权。

### 所有权与不变量

| 事项 | 所有者 |
|---|---|
| ChatLab 解析和规范化消息 DTO | 只读格式适配器 |
| 上传暂存和 AstrBot 请求映射 | WebUI/AstrBot 适配器 |
| 角色确认、Source 身份和任务编排 | ImportService |
| SQL、有界原子 Source/队列写入和导入任务记录 | `store/` repository |
| 提取和 Artifact commit | `IngestService` / `ArtifactStore.commit()` |
| 共享自我印象和人格更新 | 现有人格维护所有者，向导入流程暴露窄操作 |
| 管理员鉴权和生命周期 | 现有 AstrBot 管理边界与任务执行器 |

Source 仍是只追加的事实；Artifact 仍是保留证据、版本和账本的可修订解释。Importer 不得导入存储/服务/宿主代码，不得写 SQL、调用模型或创建 Artifact。日志和任务摘要不得包含聊天正文、凭据或原始用户标识。

### 验收标准

- [ ] 管理员页面接受单个 JSON/JSONL 文件，展示安全元数据、计数和警告，并要求管理员明确确认后才处理。
- [ ] 所有导入相关服务端接口都进行管理员鉴权。
- [ ] 不支持的版本、群聊、结构错误、缺少稳定 ID、角色歧义、额外发言者及 Source 身份冲突均在正式写入前拒绝。
- [ ] 可安全隔离的 JSONL 坏行和可识别但无效的消息，只有管理员确认后才计数跳过；结果标记为部分导入。
- [ ] JSON/JSONL 转换、重试和重复上传保持稳定消息 ID；相同 ID/相同不可变字段跳过，相同 ID/不同字段拒绝。
- [ ] 历史 Source 保留事件时间顺序、角色、发言者、目标 UMO、回复关系和内容哈希；Source 与提取状态通过有界原子路径写入。
- [ ] 所有有效话题入队并绕过 Dream 分诊；模型失败或 Artifact commit 失败后可重试，不得静默完成。
- [ ] 用户记忆仅归属所选 UMO；共享 `bot:self` 人格仅使用满足现有门槛的配对 Bot 行为证据。
- [ ] 持久化任务通过 task–Source 关联报告待提取/已提取/失败数量；任务摘要和原始文件遵循 RFC 保留周期。
- [ ] 合成测试覆盖 parser 格式、角色、身份/幂等/冲突、批次、失败恢复、隐私、任务进度、API 鉴权和目标范围。
- [ ] 代码完成且 Lead 提供非生产 API 和代表性记录后，在本地/staging AstrBot 完成真实链路验证；记录脱敏状态码、任务转换/计数和持久化检查。
- [ ] 全量仓库测试通过；AstrBot 边界在真实宿主或忠实 staging 副本验证；不进行生产部署。

### 决策记录

- 2026-10-26：范围收敛为从单份 Bot–目标用户私聊 ChatLab 文件初始化共享 Bot 人格证据和目标用户互动记忆；本次不做导出、群聊或 CLI 优先入口。
- 2026-10-26：只接收 ChatLab v0.0.2；要求稳定 `platformMessageId`、精确/明确角色映射、task–Source 进度、非分诊提取、沿用人格证据门槛和临时上传限制。完整决策见 RFC-0001。
