import {
  memoryCollectionSchema,
  type MemoryRecord,
} from "../features/memory/model.ts"
import {
  detailSchema,
  eventSchema,
  updateSchema,
  type ArtifactDetail,
  type ManagementClient,
  type OperationEvent,
} from "../features/control/model.ts"
import { mockMemories } from "./mock-data.ts"

const base = mockMemories[0]
if (!base) throw new Error("Mock 示例需要至少一条基础记录")
let records = memoryCollectionSchema.parse([
  ...mockMemories,
  ...[
    { category: "example", title: "一起把事情拆成小步骤", scope: "private" },
    { category: "media", title: "一篇关于夜间徒步的文章", scope: "shared" },
    { category: "secret", title: "有件事答应替他保密", scope: "shadow" },
    {
      category: "designated",
      title: "下次问起时，把这份计划还给他",
      scope: "private",
    },
  ].map((item, index) => ({
    ...base,
    ...item,
    id: `mock_memory_family_${index}`,
    text: item.title,
    tags: [],
    versions: [{ revision: 1, at: base.updatedAt, text: item.title }],
    relatedIds: [],
  })),
])
const details = new Map<string, ArtifactDetail>()
for (const record of records) {
  const family = ["fact", "scene", "detail", "impression"].includes(
    record.category
  )
    ? "memory"
    : record.category
  let familyPayload: ArtifactDetail["artifact"]["payload"]
  switch (family) {
    case "example":
      familyPayload = {
        user: "事情好多，不知道从哪里开始",
        assistant: record.text,
      }
      break
    case "media":
      familyPayload = {
        type: "web",
        title: record.title,
        summary: record.text,
        url: "https://example.com/walk",
      }
      break
    case "secret":
      familyPayload = {
        ref: "demo-private-reference",
        shadow_text: record.text,
      }
      break
    case "designated":
      familyPayload = { text: record.text, trigger: "计划" }
      break
    case "memory":
      familyPayload = { text: record.text, level: record.category }
      break
    default:
      familyPayload = { text: record.text }
  }
  const payload = {
    subject_kind: "third_party",
    owner_umo: record.session,
    tags: [...record.tags],
    ...familyPayload,
  }
  details.set(
    record.id,
    detailSchema.parse({
      artifact: {
        header: {
          id: record.id,
          family,
          revision: record.versions[0].revision,
          state: record.state,
          scope: record.scope,
          said_by: "10001",
          subject_id: "10002",
          time: {
            created: "2026-10-19T15:00:00+08:00",
            updated: record.updatedAt,
            valid_from: "2026-10-19",
            valid_to: "2026-12-31",
            expires: null,
          },
          lineage: {
            sources: record.id === base.id ? ["demo-source-001"] : [],
          },
        },
        payload,
      },
      versions: record.versions.map((item) => ({
        revision: item.revision,
        at: item.at,
        blob: `demo-content-hash-v${item.revision}`,
        header: JSON.stringify({
          id: record.id,
          family,
          revision: item.revision,
          scope: record.scope,
          state: record.state,
        }),
        content: JSON.stringify({ ...payload, text: item.text }),
      })),
      sources:
        record.id === base.id
          ? [
              {
                id: "demo-source-001",
                umo: record.session,
                at: record.updatedAt,
                role: "user",
                blob: "demo-source-hash",
                text: "虚构来源示例：下午想喝浅烘焙咖啡，不加糖。",
              },
            ]
          : [],
      ledger:
        record.id === base.id
          ? [
              {
                seq: 1,
                at: record.updatedAt,
                op: "revise",
                entity: record.id,
                before_hash: "2",
                after_hash: "3",
                reason: "虚构预览：补充晚间低咖啡因偏好",
                prev_hash: "",
                self_hash: "demo-ledger-hash",
              },
            ]
          : [],
    })
  )
}
let events: OperationEvent[] = [
  {
    id: "boot",
    at: "2026-10-21T08:00:00Z",
    kind: "plugin",
    status: "ready",
    message: "已加载 14 条有效记忆",
    taskId: "",
  },
  {
    id: "run",
    at: "2026-10-21T08:02:00Z",
    kind: "extract",
    status: "running",
    message: "任务已开始",
    taskId: "demo-extract-01",
  },
  {
    id: "done",
    at: "2026-10-21T08:02:03Z",
    kind: "extract",
    status: "succeeded",
    message: "已处理 2 个会话，写入 3 条记忆",
    taskId: "demo-extract-01",
  },
  {
    id: "phase",
    at: "2026-10-21T08:02:02Z",
    kind: "extract",
    status: "succeeded",
    message: "阶段已完成 （虚构预览）",
    taskId: "demo-extract-01",
    level: "INFO",
    stage: "topic.extract",
    durationMs: 1240,
    source: {
      module: "seekmemory.main",
      file: "main.py",
      function: "_flush",
      line: 329,
    },
    context: { session: "napcat:GroupMessage:10001", messages: 8, written: 3 },
  },
  {
    id: "warning",
    at: "2026-10-21T08:03:00Z",
    kind: "extract",
    status: "warning",
    message: "记忆校验失败： ValueError （虚构预览）",
    taskId: "demo-extract-02",
    level: "WARNING",
    stage: "artifact.validate",
    source: {
      module: "seekmemory.perceive.absorb",
      file: "perceive/absorb.py",
      function: "absorb",
      line: 209,
    },
    context: { rejected: 1 },
  },
  {
    id: "failure",
    at: "2026-10-21T08:03:02Z",
    kind: "extract",
    status: "failed",
    message: "阶段中断 （虚构预览）",
    taskId: "demo-extract-02",
    level: "ERROR",
    stage: "topic.extract",
    durationMs: 3012,
    source: {
      module: "seekmemory.main",
      file: "main.py",
      function: "_flush",
      line: 329,
    },
    context: { messages: 8, retained: 8 },
    error: {
      type: "TimeoutError",
      frames: [
        {
          module: "seekmemory.main",
          file: "main.py",
          function: "_flush",
          line: 332,
        },
        {
          module: "seekmemory.perceive.absorb",
          file: "perceive/absorb.py",
          function: "absorb",
          line: 166,
        },
      ],
    },
  },
]
  .map((event) => eventSchema.parse(event))
  .sort((a, b) => b.at.localeCompare(a.at))

export const mockClient: ManagementClient = {
  async records() {
    return records
  },
  async status() {
    return {
      ready: true,
      checks: ["engine", "ledger", "provider", "journal"].map((name) => ({
        name,
        ok: true,
        detail: "Mock 检测，未连接真实服务",
      })),
      activeTask: null,
      pending: [{ session: "napcat:GroupMessage:10001", count: 8 }],
      pendingTopics: [
        {
          id: "tp_mock_coffee",
          session: "napcat:GroupMessage:10001",
          count: 5,
          oldestAt: "2026-10-20T14:00:00+08:00",
        },
        {
          id: "tp_mock_travel",
          session: "napcat:GroupMessage:10001",
          count: 3,
          oldestAt: "2026-10-21T09:00:00+08:00",
        },
      ],
      extractionPolicy: {
        backlogThreshold: 30,
        topicTtlSeconds: 86400,
        maxTopicsPerBatch: 6,
      },
      capacity: {
        state: "normal",
        actions: ["schedule_extraction"],
        reasons: [],
        pressure: 0.08,
        snapshot: {
          sourceRows: 32,
          sourceBytes: 4096,
          pendingRows: 8,
          deferredRows: 0,
          deadRows: 0,
          databaseBytes: 1048576,
          artifactCount: 12,
          artifactBytes: 8192,
          contextChars: 120,
          traceRows: 3,
        },
        queue: { pending: 8, retrying: 0, deferred: 0, extracted: 24, dead: 0 },
      },
      checkpointPending: 2,
      schedulerCount: 4,
      config: {
        owner_umo: "napcat:FriendMessage:10001",
        observe_groups: true,
        summary_time: "23:50",
        weekly_day: 6,
        checkpoint_seconds: 1800,
        budget_chars: 600,
      },
    }
  },
  async events() {
    return events
  },
  async detail(id) {
    const detail = details.get(id)
    if (!detail) throw new Error("记忆不存在")
    return structuredClone(detail)
  },
  async update(input) {
    const command = updateSchema.parse(input)
    const detail = details.get(command.id)
    if (!detail || detail.artifact.header.revision !== command.expectedRevision)
      throw new Error("版本冲突，请重新加载")
    const at = new Date().toISOString()
    const textValue = command.payload["text"]
    const text =
      typeof textValue === "string"
        ? textValue
        : JSON.stringify(command.payload)
    detail.artifact = {
      header: {
        ...detail.artifact.header,
        revision: command.expectedRevision + 1,
        scope: command.scope,
        state: command.state,
      },
      payload: command.payload,
    }
    detail.versions.unshift({
      revision: detail.artifact.header.revision,
      at,
      blob: "demo-new-hash",
      content: JSON.stringify(command.payload),
    })
    detail.ledger.push({
      op: command.state === "forgotten" ? "forget" : "revise",
      at,
      reason: command.reason,
      before_hash: String(command.expectedRevision),
      after_hash: String(detail.artifact.header.revision),
    })
    records = memoryCollectionSchema.parse(
      records.map((record): MemoryRecord =>
        record.id !== command.id
          ? record
          : {
              ...record,
              text,
              title: text.slice(0, 60),
              scope: command.scope,
              state: command.state,
              updatedAt: at,
              versions: [
                { revision: command.expectedRevision + 1, at, text },
                ...record.versions,
              ],
            }
      )
    )
  },
  async diagnose({ query, umo }) {
    const visible = records.filter(
      (record) =>
        record.state === "active" &&
        (record.scope !== "private" || record.session === umo)
    )
    const picked = visible.filter((record) =>
      record.text.includes(query.trim())
    )
    // 轮流演示四种披露级别，不模拟后端的主体披露算法。
    const levels = ["full", "paraphrase", "hint", "silence"] as const
    const disclosure: Record<string, string> = {}
    const blocks: string[] = []
    for (const [index, record] of picked.entries()) {
      const level = levels[index % levels.length] ?? "silence"
      disclosure[record.id] = level
      if (level === "full") blocks.push(record.text)
      else if (level === "paraphrase")
        blocks.push("曾提到过一件相关的事，细节不在这里展开。（Mock）")
      else if (level === "hint") blocks.push("隐约记得一件相关的事。（Mock）")
    }
    const block = blocks.join("\n")
    return {
      block,
      info: {
        mock: true,
        mode: "strict",
        picked: blocks.length,
        pinned: 0,
        chars: block.length,
        disclosure,
      },
      visible: visible.map((record) => record.id),
      excluded: records
        .filter(
          (record) => record.state === "active" && !visible.includes(record)
        )
        .map((record) => record.id),
    }
  },
  async task(kind) {
    const id = "demo-" + crypto.randomUUID()
    events = [
      eventSchema.parse({
        id,
        at: new Date().toISOString(),
        kind,
        status: "succeeded",
        message: "Mock 任务已完成，未调用模型或修改真实数据",
        taskId: id,
      }),
      ...events,
    ]
    return id
  },
  async cancel() {
    throw new Error("Mock 中没有正在运行的真实任务")
  },
}
