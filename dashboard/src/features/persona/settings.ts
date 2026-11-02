import { z } from "zod"
import type { ArtifactDetail } from "../control/model.ts"

export const settingsSchema = z.object({
  name: z.string().trim().min(1, "请填写姓名").max(80, "姓名最多 80 字"),
  persona: z
    .string()
    .trim()
    .min(1, "请填写人格正文")
    .max(20000, "人格正文最多 20,000 字"),
  style: z
    .record(z.string(), z.json())
    .refine(
      (value) => JSON.stringify(value).length <= 20000,
      "表达风格内容过长"
    ),
  boundaries: z
    .array(
      z.string().trim().min(1, "边界不能为空").max(300, "每条边界最多 300 字")
    )
    .max(32, "最多 32 条边界"),
})
export type PersonaSettings = z.infer<typeof settingsSchema>
export type FieldErrors = Record<string, string>
export function fieldErrors(error: z.ZodError): FieldErrors {
  return Object.fromEntries(
    error.issues.map((issue) => [
      String(issue.path[0] ?? "form"),
      issue.message,
    ])
  )
}
export function settingsFromDetail(detail: ArtifactDetail): PersonaSettings {
  const p = detail.artifact.payload
  if (
    detail.artifact.header.family !== "persona" ||
    detail.artifact.header.state !== "active"
  )
    throw new Error("只能编辑当前有效人格")
  const style = z.record(z.string(), z.json()).safeParse(p["style"] ?? {})
  const boundaries = z.array(z.string()).safeParse(p["boundaries"] ?? [])
  if (!style.success || !boundaries.success)
    throw new Error("当前人格的风格或边界格式无效，请先在高级编辑中核对")
  return {
    name: typeof p["persona_name"] === "string" ? p["persona_name"] : "",
    persona: typeof p["text"] === "string" ? p["text"] : "",
    style: style.data,
    boundaries: boundaries.data,
  }
}
export function editedPayload(
  detail: ArtifactDetail,
  draft: PersonaSettings
): ArtifactDetail["artifact"]["payload"] {
  const settings = settingsSchema.parse(draft)
  const payload = {
    ...detail.artifact.payload,
    persona_name: settings.name,
    text: settings.persona,
    style: settings.style,
    boundaries: settings.boundaries,
  }
  if (
    "base_text" in payload &&
    settings.persona !== detail.artifact.payload["text"]
  )
    payload["base_text"] = settings.persona
  return payload
}
