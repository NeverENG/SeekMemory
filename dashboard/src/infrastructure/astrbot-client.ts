import { z } from "zod"
import type { ApiRequest, ApiResponse } from "../contracts/api.ts"
import { memoryCollectionSchema } from "../features/memory/model.ts"
import { tracesSchema } from "../features/control/trace-model.ts"
import {
  chatLabPreviewSchema,
  chatLabUploadSchema,
  importConfirmCommandSchema,
  importRetryCommandSchema,
  importRoleCommandSchema,
  importTaskResponseSchema,
  importTasksResponseSchema,
} from "../features/control/history-import-model.ts"
import {
  detailSchema,
  diagnosticSchema,
  eventsSchema,
  statusSchema,
  updateSchema,
  type ManagementClient,
} from "../features/control/model.ts"

interface PluginBridge {
  ready(): Promise<unknown>
  apiGet(endpoint: string, query?: Record<string, string>): Promise<unknown>
  apiPost(endpoint: string, body: unknown): Promise<unknown>
  upload(endpoint: string, file: File): Promise<unknown>
}
declare global {
  interface Window {
    AstrBotPluginPage?: PluginBridge
  }
}

async function bridge(): Promise<PluginBridge> {
  const current = window.AstrBotPluginPage
  if (!current)
    throw new Error("请从 AstrBot 的 SeekMemory 插件视图打开此页面。")
  let timer: ReturnType<typeof setTimeout> | undefined
  try {
    await Promise.race([
      current.ready(),
      new Promise<never>((_resolve, reject) => {
        timer = setTimeout(
          () => reject(new Error("宿主连接超时，请重新打开插件视图。")),
          10000
        )
      }),
    ])
  } finally {
    if (timer !== undefined) clearTimeout(timer)
  }
  return current
}

const idResponseSchema = z.object({ id: z.string() }) satisfies z.ZodType<
  ApiResponse<"task">
>

export const astrbotClient: ManagementClient = {
  async traces() {
    const host = await bridge()
    return tracesSchema.parse(await host.apiGet("manage/traces"))
  },
  async records() {
    const host = await bridge()
    const data = await host.apiGet("manage/records")
    return z.object({ records: memoryCollectionSchema }).parse(data).records
  },
  async status() {
    const host = await bridge()
    const data = await host.apiGet("manage/status")
    return statusSchema.parse(data)
  },
  async detail(id) {
    const host = await bridge()
    const data = await host.apiGet("manage/detail", { id })
    return detailSchema.parse(data)
  },
  async events() {
    const host = await bridge()
    const data = await host.apiGet("manage/events")
    return eventsSchema.parse(data).events
  },
  async update(command) {
    const body = updateSchema.parse(command) satisfies ApiRequest<"update">
    const host = await bridge()
    const data = await host.apiPost("manage/update", body)
    idResponseSchema.parse(data)
  },
  async diagnose(query) {
    const body: ApiRequest<"diagnose"> = query
    const host = await bridge()
    const data = await host.apiPost("manage/diagnose", body)
    return diagnosticSchema.parse(data)
  },
  async task(kind) {
    const body = { kind, confirmed: true } satisfies ApiRequest<"task">
    const host = await bridge()
    const data = await host.apiPost("manage/task", body)
    return idResponseSchema.parse(data).id
  },
  async cancel(id) {
    const body = { id, confirmed: true } satisfies ApiRequest<"cancel">
    const host = await bridge()
    const data = await host.apiPost("manage/cancel", body)
    idResponseSchema.parse(data)
  },
  historyImport: {
    async uploadImport(file) {
      const host = await bridge()
      return chatLabUploadSchema.parse(
        await host.upload("manage/importUpload", file)
      )
    },
    async validateImport(command) {
      const body = importRoleCommandSchema.parse(command)
      const host = await bridge()
      const data: unknown = await host.apiPost("manage/importValidate", body)
      const parsed = z.object({ preview: z.unknown() }).parse(data)
      return chatLabPreviewSchema.parse(parsed.preview)
    },
    async confirmImport(command) {
      const body = importConfirmCommandSchema.parse(command)
      const host = await bridge()
      const data = await host.apiPost("manage/importConfirm", body)
      return idResponseSchema.parse(data).id
    },
    async importTasks() {
      const host = await bridge()
      const data = await host.apiGet("manage/importTasks")
      return importTasksResponseSchema.parse(data).tasks
    },
    async importTask(id) {
      const host = await bridge()
      const data = await host.apiGet("manage/importTask", { id })
      return importTaskResponseSchema.parse(data).task
    },
    async cancelImport(id) {
      const body = importRetryCommandSchema.parse({ id, confirmed: true })
      const host = await bridge()
      const data = await host.apiPost("manage/importCancel", body)
      idResponseSchema.parse(data)
    },
    async retryImport(id) {
      const body = importRetryCommandSchema.parse({ id, confirmed: true })
      const host = await bridge()
      const data = await host.apiPost("manage/importRetry", body)
      return idResponseSchema.parse(data).id
    },
    async abandonImport(id) {
      const body = importRetryCommandSchema.parse({ id, confirmed: true })
      const host = await bridge()
      const data = await host.apiPost("manage/importAbandon", body)
      idResponseSchema.parse(data)
    },
  },
}
