import { z } from "zod"
import type {
  ApiRequest,
  ApiResponse,
  ApiSchemas,
} from "../../contracts/api.ts"
import type { MemoryRecord } from "../memory/model.ts"
import type { TraceSnapshot } from "./trace-model.ts"

export const detailSchema = z.object({
  artifact: z.object({
    header: z.looseObject({
      id: z.string(),
      family: z.string(),
      revision: z.number().int().positive(),
      state: z.enum(["active", "forgotten", "merged"]),
      scope: z.enum(["private", "shared", "shadow"]),
      subject_id: z.string().exactOptional(),
      said_by: z.string().exactOptional(),
      time: z
        .looseObject({
          created: z.string().exactOptional(),
          updated: z.string().exactOptional(),
          valid_from: z.string().nullable().exactOptional(),
          valid_to: z.string().nullable().exactOptional(),
          expires: z.string().nullable().exactOptional(),
        })
        .exactOptional(),
    }),
    payload: z.record(z.string(), z.json()),
  }),
  versions: z.array(z.record(z.string(), z.json())),
  sources: z.array(z.record(z.string(), z.json())),
  ledger: z.array(z.record(z.string(), z.json())),
}) satisfies z.ZodType<ApiResponse<"detail">>
export const personaRevisionSchema = z.object({
  revision: z.number().int().nonnegative(),
  at: z.string(),
  op: z.string(),
  text: z.string(),
  derivedFrom: z.array(z.string()).default([]),
  sourceIds: z.array(z.string()).default([]),
})
export const statusSchema = z.object({
  ready: z.boolean(),
  checks: z.array(
    z.object({ name: z.string(), ok: z.boolean(), detail: z.string() })
  ),
  activeTask: z.object({ id: z.string(), kind: z.string() }).nullable(),
  pending: z.array(
    z.object({ session: z.string(), count: z.number().int().nonnegative() })
  ),
  pendingTopics: z.array(
    z.object({
      id: z.string(),
      session: z.string(),
      count: z.number().int().positive(),
      oldestAt: z.iso.datetime({ offset: true }).nullable(),
    })
  ),
  extractionPolicy: z.object({
    backlogThreshold: z.number().int(),
    topicTtlSeconds: z.number(),
    maxTopicsPerBatch: z.number().int().positive(),
  }),
  capacity: z
    .object({
      state: z.enum(["normal", "pressured", "saturated", "protective"]),
      actions: z.array(z.string()),
      reasons: z.array(z.string()),
      pressure: z.number().min(0).max(1),
      snapshot: z.object({
        sourceRows: z.number().int().nonnegative(),
        sourceBytes: z.number().int().nonnegative(),
        pendingRows: z.number().int().nonnegative(),
        deferredRows: z.number().int().nonnegative(),
        deadRows: z.number().int().nonnegative(),
        databaseBytes: z.number().int().nonnegative(),
        artifactCount: z.number().int().nonnegative(),
        artifactBytes: z.number().int().nonnegative(),
        contextChars: z.number().int().nonnegative(),
        traceRows: z.number().int().nonnegative(),
      }),
      queue: z.record(z.string(), z.number().int().nonnegative()),
    })
    .nullable(),
  persona: z
    .object({
      id: z.string(),
      revision: z.number().int().nonnegative(),
      text: z.string(),
      revisions: z.array(personaRevisionSchema),
    })
    .nullable()
    .default(null),
  budget: z
    .object({
      injection_chars: z.number().int().nonnegative(),
      system_chars: z.number().int().nonnegative(),
      group_context_messages: z.number().int().nonnegative(),
      history_messages: z.number().int().nonnegative(),
      source_recall_enabled: z.boolean(),
      source_recall_hours: z.number().int().positive(),
      source_recall_max_candidates: z.number().int().positive(),
      estimate_tokens: z.number().int().nonnegative(),
    })
    .nullable()
    .exactOptional(),
  checkpointPending: z.number().int().nonnegative().nullable(),
  schedulerCount: z.number().int().nonnegative(),
  config: z.record(z.string(), z.json()),
}) satisfies z.ZodType<ApiResponse<"status">>
const logSourceSchema = z.object({
  module: z.string(),
  file: z.string(),
  function: z.string(),
  line: z.number().int().positive(),
})
export const eventSchema = z.object({
  id: z.string(),
  at: z.string(),
  kind: z.string(),
  status: z.string(),
  message: z.string(),
  taskId: z.string(),
  level: z.enum(["DEBUG", "INFO", "WARNING", "ERROR"]).default("INFO"),
  stage: z.string().default(""),
  source: logSourceSchema.nullable().default(null),
  context: z
    .record(
      z.string(),
      z.union([z.string(), z.number(), z.boolean(), z.null()])
    )
    .default({}),
  durationMs: z.number().nonnegative().nullable().default(null),
  error: z
    .object({ type: z.string(), frames: z.array(logSourceSchema) })
    .nullable()
    .default(null),
}) satisfies z.ZodType<ApiSchemas["OperationEvent"]>
export const eventsSchema = z.object({
  events: z.array(eventSchema).max(500),
  capacity: z.literal(500),
}) satisfies z.ZodType<ApiResponse<"events">>
export const diagnosticSchema = z.object({
  block: z.string(),
  info: z.record(z.string(), z.json()),
  visible: z.array(z.string()),
  excluded: z.array(z.string()),
}) satisfies z.ZodType<ApiResponse<"diagnose">>
export const updateSchema = z.strictObject({
  id: z.string().min(1),
  expectedRevision: z.number().int().positive(),
  payload: z.record(z.string(), z.json()),
  scope: z.enum(["private", "shared", "shadow"]),
  state: z.enum(["active", "forgotten", "merged"]),
  reason: z.string().trim().min(1).max(300),
  confirmed: z.literal(true),
}) satisfies z.ZodType<ApiRequest<"update">>
export type ArtifactDetail = z.infer<typeof detailSchema>
export type RuntimeStatus = z.infer<typeof statusSchema>
export type OperationEvent = z.infer<typeof eventSchema>
export type Diagnostic = z.infer<typeof diagnosticSchema>
export type UpdateCommand = z.infer<typeof updateSchema>
export type DiagnosticQuery = ApiRequest<"diagnose">

export interface ManagementClient {
  traces(): Promise<TraceSnapshot>
  records(): Promise<readonly MemoryRecord[]>
  status(): Promise<RuntimeStatus>
  detail(id: string): Promise<ArtifactDetail>
  events(): Promise<OperationEvent[]>
  update(command: UpdateCommand): Promise<void>
  diagnose(query: DiagnosticQuery): Promise<Diagnostic>
  task(kind: "extract" | "weekly"): Promise<string>
  cancel(id: string): Promise<void>
}

/** 仅展示已记录的归属和时间，不从说话人或更新日期推断缺失信息。 */
export function selectAttribution(detail: ArtifactDetail) {
  const { header, payload } = detail.artifact
  const subjectKind = payload["subject_kind"]
  return {
    subjectId: header.subject_id || null,
    saidBy: header.said_by || null,
    subjectKind: typeof subjectKind === "string" ? subjectKind : null,
    created: header.time?.created || null,
    validFrom: header.time?.valid_from || null,
    validTo: header.time?.valid_to || null,
  }
}

/** 披露判定只覆盖后端返回的记录，不将缺失结果当成全文许可。 */
export function selectDisclosure(result: Diagnostic) {
  const parsed = z
    .record(z.string(), z.string())
    .safeParse(result.info["disclosure"])
  if (!parsed.success) return []
  return Object.entries(parsed.data).map(([id, level]) => ({ id, level }))
}
