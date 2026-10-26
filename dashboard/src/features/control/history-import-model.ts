import { z } from "zod"

export const chatLabMemberSchema = z.strictObject({
  platformId: z.string().min(1),
  accountName: z.string(),
})
export const chatLabWarningSchema = z.strictObject({
  row: z.number().int().positive(),
  reason: z.string(),
})
export const chatLabPreviewSchema = z.strictObject({
  format: z.enum(["json", "jsonl"]),
  version: z.literal("0.0.2"),
  platform: z.string(),
  conversationType: z.literal("private"),
  name: z.string(),
  members: z.array(chatLabMemberSchema),
  senderCounts: z.record(z.string(), z.number().int().nonnegative()),
  messageCount: z.number().int().positive(),
  messageRows: z.number().int().positive(),
  skippedCount: z.number().int().nonnegative(),
  missingIdCount: z.literal(0),
  firstAt: z.string(),
  lastAt: z.string(),
  warnings: z.array(chatLabWarningSchema),
  uniqueSourceCount: z.number().int().nonnegative().optional(),
  duplicateCount: z.number().int().nonnegative().optional(),
  targetUmo: z.string().optional(),
  roleMapping: z
    .strictObject({ assistantMemberId: z.string(), userMemberId: z.string() })
    .optional(),
})
export const chatLabUploadSchema = z.strictObject({
  stageKey: z.string().regex(/^[0-9a-f]{32}$/),
  filename: z.string(),
  size: z.number().int().positive(),
  preview: chatLabPreviewSchema,
})
export const importRoleCommandSchema = z.strictObject({
  stageKey: z.string().regex(/^[0-9a-f]{32}$/),
  botPlatformId: z.string().max(256),
  targetPlatformId: z.string().max(256),
  targetUmo: z.string().min(1).max(300),
  botMemberId: z.string(),
  targetMemberId: z.string(),
})
export const importConfirmCommandSchema = importRoleCommandSchema.extend({
  confirmed: z.literal(true),
})
export const importRetryCommandSchema = z.strictObject({
  id: z.string().min(1),
  confirmed: z.literal(true),
})
export const importTaskStatusSchema = z.enum([
  "queued",
  "running",
  "interrupted",
  "completed",
  "partial",
  "failed",
  "cancelled",
  "abandoned",
])
export const importTaskSchema = z.strictObject({
  id: z.string(),
  status: importTaskStatusSchema,
  formatId: z.literal("chatlab"),
  sourceCount: z.number().int().nonnegative(),
  duplicateCount: z.number().int().nonnegative(),
  skippedCount: z.number().int().nonnegative(),
  pendingCount: z.number().int().nonnegative(),
  extractedCount: z.number().int().nonnegative(),
  failedCount: z.number().int().nonnegative(),
  errorTypes: z.array(z.string()),
  personaStatus: z.string(),
  canRetry: z.boolean(),
  createdAt: z.string(),
  updatedAt: z.string(),
  terminalAt: z.string(),
})
export const importTasksResponseSchema = z.strictObject({
  tasks: z.array(importTaskSchema),
})
export const importTaskResponseSchema = z.strictObject({
  task: importTaskSchema,
})

export type ChatLabPreview = z.infer<typeof chatLabPreviewSchema>
export type ChatLabUpload = z.infer<typeof chatLabUploadSchema>
export type ImportRoleCommand = z.infer<typeof importRoleCommandSchema>
export type ImportConfirmCommand = z.infer<typeof importConfirmCommandSchema>
export type ImportTask = z.infer<typeof importTaskSchema>
export type ImportTaskStatus = z.infer<typeof importTaskStatusSchema>

export interface HistoryImportClient {
  uploadImport(file: File): Promise<ChatLabUpload>
  validateImport(command: ImportRoleCommand): Promise<ChatLabPreview>
  confirmImport(command: ImportConfirmCommand): Promise<string>
  importTasks(): Promise<ImportTask[]>
  importTask(id: string): Promise<ImportTask>
  cancelImport(id: string): Promise<void>
  retryImport(id: string): Promise<string>
  abandonImport(id: string): Promise<void>
}

export function isImportActive(status: ImportTaskStatus): boolean {
  return status === "queued" || status === "running"
}
