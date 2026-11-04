import type { ArtifactDetail } from "../control/model.ts"
import { seedSchema, type PersonaSeed } from "../shell/model.ts"
/** A blueprint contains authored persona fields, never Source bodies or evidence links. */
export function personaBlueprint(
  detail: ArtifactDetail,
  name: string,
  id: string
): PersonaSeed {
  if (detail.artifact.header.family !== "persona")
    throw new Error("只能将人格保存为蓝图")
  const payload = detail.artifact.payload
  return seedSchema.parse({
    id,
    name,
    version: "1.0.0",
    persona: payload["text"],
    style: payload["style"] ?? {},
    boundaries: payload["boundaries"] ?? [],
    license: payload["seed_license"] || "private",
    source:
      typeof payload["seed_source"] === "string"
        ? payload["seed_source"]
        : "user-created persona blueprint",
    content_rating: payload["content_rating"] || "unrated",
    locale: payload["locale"] || "zh-CN",
  })
}

/** Only an explicit namespaced baseline can establish application state. */
export function packInstallLabel(
  pack: {
    reference: string
    id: string
    version: string
    digest?: string
    settingsDigest?: string
  },
  persona:
    | Pick<
        NonNullable<import("../control/model.ts").RuntimeStatus["persona"]>,
        "seedId" | "packApplication"
      >
    | null
    | undefined
): string {
  if (!persona) return ""
  const application = persona.packApplication
  if (!application) return persona.seedId === pack.id ? " · 应用来源未知" : ""
  if (application.reference !== pack.reference) return ""
  const changed =
    application.currentSettingsDigest !== application.settingsDigest
  const base = ` · 基于此包${changed ? "，当前设定已变化" : "，当前设定与应用时一致"}`
  if (!pack.digest || !pack.settingsDigest) return base + "；无法核对已保存包"
  if (application.packDigest === pack.digest) return base
  if (application.version !== pack.version)
    return base + `；已保存包版本不同（应用时 v${application.version}）`
  return (
    base +
    (application.settingsDigest === pack.settingsDigest
      ? "；仅包资源或其他元数据变化"
      : "；已保存包设定已变化")
  )
}
