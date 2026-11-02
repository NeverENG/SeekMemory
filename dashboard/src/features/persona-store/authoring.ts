import { z } from "zod"
import {
  bundleSchema,
  type PersonaBundle,
  type ConsoleClient,
} from "../shell/model.ts"
import { settingsSchema } from "../persona/settings.ts"
import { newPackId } from "./pack-id.ts"

export type PackLookup = Awaited<ReturnType<ConsoleClient["packLookup"]>>
export interface PackDraft {
  pack: PersonaBundle
  target?: PackLookup
  title: string
}
export function nextVersion(version: string): string {
  const match = /^(\d+)\.(\d+)\.(\d+)$/.exec(version)
  return match ? `${match[1]}.${match[2]}.${Number(match[3]) + 1}` : ""
}
export function newPack(): PersonaBundle {
  return {
    format: "seekmemory.persona-pack/v1",
    seed: {
      id: newPackId(),
      version: "1.0.0",
      name: "",
      persona: "",
      style: {},
      boundaries: [],
      license: "private",
      source: "user-created persona blueprint",
      content_rating: "general",
      locale: "zh-CN",
    },
    artwork: null,
    licenseText: "",
  }
}
export function copyPack(pack: PersonaBundle): PersonaBundle {
  return {
    ...structuredClone(pack),
    seed: {
      ...structuredClone(pack.seed),
      id: newPackId(),
      name: `${pack.seed.name.slice(0, 74)}（副本）`,
      version: "1.0.0",
    },
  }
}
export function validatePack(pack: PersonaBundle, target: PackLookup | null) {
  return bundleSchema
    .transform((value) => ({
      ...value,
      seed: { ...value.seed, version: value.seed.version.trim() },
    }))
    .superRefine((value, ctx) => {
      const settings = settingsSchema.safeParse({
        ...value.seed,
        style: value.seed.style ?? {},
        boundaries: value.seed.boundaries ?? [],
      })
      if (!settings.success)
        for (const issue of settings.error.issues)
          ctx.addIssue({
            code: "custom",
            path: ["seed", ...issue.path],
            message: issue.message,
          })
      if (value.artwork)
        for (const [key, text] of [
          ["license", "请声明包含封面的许可证"],
          ["source", "请填写封面与设定的来源"],
        ] as const)
          if (!value.seed[key]?.trim())
            ctx.addIssue({ code: "custom", path: ["seed", key], message: text })
      if (value.artwork && !value.licenseText.trim())
        ctx.addIssue({
          code: "custom",
          path: ["licenseText"],
          message: "带封面时请填写许可证正文",
        })
      if (new TextEncoder().encode(value.licenseText).length > 65536)
        ctx.addIssue({
          code: "custom",
          path: ["licenseText"],
          message: "许可证正文最多 64 KiB",
        })
      if (new TextEncoder().encode(JSON.stringify(value.seed)).length > 65536)
        ctx.addIssue({
          code: "custom",
          path: ["seed"],
          message: "设定总大小最多 64 KiB，请缩短正文或风格",
        })
      if (!value.seed.version)
        ctx.addIssue({
          code: "custom",
          path: ["seed", "version"],
          message: "请填写包版本号",
        })
      if (target?.pack && value.seed.version === target.pack.seed.version)
        ctx.addIssue({
          code: "custom",
          path: ["seed", "version"],
          message: "更新时请填写与已保存版本不同的新版本号",
        })
    })
    .safeParse(pack)
}
export function packErrors(error: z.ZodError): Record<string, string> {
  return Object.fromEntries(
    error.issues.map((issue) => [
      String(
        issue.path[0] === "seed" ? (issue.path[1] ?? "form") : issue.path[0]
      ),
      issue.message,
    ])
  )
}
