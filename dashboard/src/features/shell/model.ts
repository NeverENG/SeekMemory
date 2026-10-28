import { z } from "zod"
import type { ApiResponse, ApiRequest } from "../../contracts/api.ts"

export const graphSchema = z.object({
  nodes: z
    .array(
      z.object({
        id: z.string(),
        kind: z.string(),
        scope: z.string(),
        subject: z.string(),
        state: z.string(),
        label: z.string(),
        createdAt: z.string(),
        updatedAt: z.string(),
        confidence: z.number(),
        protected: z.boolean(),
      })
    )
    .max(1000),
  edges: z
    .array(
      z.object({ source: z.string(), target: z.string(), kind: z.string() })
    )
    .max(2000),
  total: z.number().int().nonnegative(),
  limit: z.number().int(),
}) satisfies z.ZodType<ApiResponse<"graph">>
export const impressionsSchema = z.object({
  items: z
    .array(
      z.object({
        id: z.string(),
        subjectId: z.string(),
        subjectKind: z.string(),
        displayName: z.string(),
        summary: z.string(),
        scope: z.string(),
        updatedAt: z.string(),
        confidence: z.number(),
        evidenceCount: z.number().int(),
        revision: z.number().int(),
      })
    )
    .max(100),
  total: z.number().int(),
  offset: z.number().int(),
  limit: z.number().int(),
}) satisfies z.ZodType<ApiResponse<"impressions">>
export const dreamSchema = z.object({
  items: z
    .array(
      z.object({
        date: z.string(),
        status: z.string(),
        batches: z.number().int(),
        written: z.number().int(),
        calls: z.number().int(),
        usageIn: z.number().int(),
        usageOut: z.number().int(),
        errorCount: z.number().int(),
        candidates: z.number().int().nullable().exactOptional(),
        eligible: z.number().int().nullable().exactOptional(),
        selected: z.number().int().nullable().exactOptional(),
        skipped: z.number().int().nullable().exactOptional(),
        pending: z.number().int().nullable().exactOptional(),
        stopped: z.string().exactOptional(),
      })
    )
    .max(100),
  limit: z.number().int(),
}) satisfies z.ZodType<ApiResponse<"dream">>
export const artworkSchema = z.strictObject({
  mediaType: z.literal("image/png"),
  dataBase64: z
    .string()
    .min(1)
    .max(2796204)
    .regex(/^[A-Za-z0-9+/]+={0,2}$/),
}) satisfies z.ZodType<ApiResponse<"packArtwork">>
export const packSchema = z.object({
  artworkRef: z
    .string()
    .regex(/^(official|mine)\/[a-z0-9][a-z0-9._-]{1,63}@[a-f0-9]{64}$/)
    .nullable()
    .exactOptional(),
  reference: z.string(),
  id: z.string(),
  name: z.string(),
  version: z.string(),
  description: z.string(),
  license: z.string(),
  source: z.string(),
  contentRating: z.string(),
  locale: z.string(),
})
export const packsSchema = z.object({
  items: z.array(packSchema).max(24),
  total: z.number().int(),
  offset: z.number().int(),
  limit: z.number().int(),
}) satisfies z.ZodType<ApiResponse<"packs">>
export const seedSchema = z.strictObject({
  id: z
    .string()
    .min(2)
    .max(64)
    .regex(/^[a-z0-9][a-z0-9._-]{1,63}$/),
  version: z.string().min(1).max(32),
  name: z.string().min(1).max(80),
  persona: z.string().min(1).max(20000),
  style: z.record(z.string(), z.json()).exactOptional(),
  boundaries: z.array(z.string().max(300)).max(32).exactOptional(),
  corpus: z
    .array(
      z.strictObject({
        user: z.string().trim().min(1).max(2000),
        assistant: z.string().trim().min(1).max(2000),
      })
    )
    .min(12)
    .max(128)
    .refine(
      (pairs) =>
        pairs.reduce((n, p) => n + p.user.length + p.assistant.length, 0) >=
        1200,
      "语料至少需要 1200 字"
    )
    .exactOptional(),
  license: z.string().max(200).exactOptional(),
  source: z.string().max(200).exactOptional(),
  content_rating: z.string().max(32).exactOptional(),
  locale: z.string().max(20).exactOptional(),
})
export const bundleSchema = z.strictObject({
  format: z.literal("seekmemory.persona-pack/v1"),
  seed: seedSchema,
  licenseText: z.string().max(65536),
  artwork: artworkSchema.nullable(),
}) satisfies z.ZodType<ApiResponse<"packExport">>
export type PersonaBundle = z.infer<typeof bundleSchema>
export const packDetailSchema = z.object({
  licenseText: z.string().max(65536).exactOptional(),
  seed: seedSchema,
  digest: z.string().regex(/^[a-f0-9]{64}$/),
}) satisfies z.ZodType<ApiResponse<"pack">>
export const personaResultSchema = z.union([
  z.object({ reference: z.string() }),
  z.object({
    id: z.string(),
    revision: z.number().int(),
    seedId: z.string(),
    seedVersion: z.string(),
  }),
]) satisfies z.ZodType<ApiResponse<"persona">>
export const rollbackResultSchema = z.object({
  id: z.string(),
  revision: z.number().int().positive(),
  restoredRevision: z.number().int().positive(),
}) satisfies z.ZodType<ApiResponse<"rollbackPersona">>
export type GraphSnapshot = z.infer<typeof graphSchema>
export type GraphNode = GraphSnapshot["nodes"][number]
export type Impression = z.infer<typeof impressionsSchema>["items"][number]
export type DreamEntry = z.infer<typeof dreamSchema>["items"][number]
export type PersonaPack = z.infer<typeof packSchema>
export type PersonaSeed = z.infer<typeof seedSchema>
export type PersonaCommand = ApiRequest<"persona">
export interface ConsoleClient {
  rollbackPersona(
    command: ApiRequest<"rollbackPersona">
  ): Promise<z.infer<typeof rollbackResultSchema>>
  graph(): Promise<GraphSnapshot>
  impressions(offset?: number): Promise<z.infer<typeof impressionsSchema>>
  dream(): Promise<z.infer<typeof dreamSchema>>
  packs(
    collection: "official" | "mine",
    offset?: number
  ): Promise<z.infer<typeof packsSchema>>
  pack(reference: string): Promise<z.infer<typeof packDetailSchema>>
  packArtwork(reference: string): Promise<z.infer<typeof artworkSchema>>
  packExport(reference: string): Promise<PersonaBundle>
  persona(command: PersonaCommand): Promise<z.infer<typeof personaResultSchema>>
}
export const pageIds = [
  "home",
  "persona",
  "memory",
  "impressions",
  "studio",
  "store",
  "dream",
  "traces",
  "system",
] as const
export type WorkspacePage = (typeof pageIds)[number]
export function parseRoute(hash: string): {
  page: WorkspacePage
  node: string
  revision: number | null
  section?: string
} {
  const [path, query = ""] = hash.replace(/^#\/?/, "").split("?")
  const page = pageIds.find((id) => id === path) ?? "home"
  const params = new URLSearchParams(query)
  const raw = params.get("revision")
  const revision = raw && /^\d+$/.test(raw) ? Number(raw) : null
  if (page === "traces")
    return {
      page: "system",
      section: "traces",
      node: params.get("node") ?? "",
      revision,
    }
  return {
    page,
    node: params.get("node") ?? "",
    revision,
    ...(page === "system"
      ? { section: params.get("section") ?? "memory" }
      : {}),
  }
}
