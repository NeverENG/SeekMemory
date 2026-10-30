import { consoleClient } from "./console-client.ts"
import type { Bridge } from "./console-client.ts"
import { z } from "zod"
import type { ApiRequest, ApiResponse } from "../contracts/api.ts"
import { memoryCollectionSchema } from "../features/memory/model.ts"
import { tracesSchema } from "../features/control/trace-model.ts"
import {
  detailSchema,
  diagnosticSchema,
  eventsSchema,
  statusSchema,
  updateSchema,
  type ManagementClient,
} from "../features/control/model.ts"

const idResponseSchema = z.object({ id: z.string() }) satisfies z.ZodType<
  ApiResponse<"task">
>

export function managementClient(
  bridge: () => Promise<Bridge>
): ManagementClient {
  return {
    console: consoleClient(bridge),
    async traces(query = {}) {
      const host = await bridge()
      const fields = Object.fromEntries(
        Object.entries(query).filter(
          ([, value]) => value !== undefined && value !== ""
        )
      )
      return tracesSchema.parse(await host.apiGet("manage/traces", fields))
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
  }
}
