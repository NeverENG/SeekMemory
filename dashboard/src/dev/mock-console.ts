import { detailSchema, type ArtifactDetail } from "../features/control/model.ts"
import type { MemoryRecord } from "../features/memory/model.ts"
import { recentGraph } from "../features/memory-graph/model.ts"
import {
  seedSchema,
  bundleSchema,
  type PersonaBundle,
  type ConsoleClient,
  type PersonaSeed,
} from "../features/shell/model.ts"
import fish from "../../../persona_seeds/big_fish/persona.json" with { type: "json" }
import ojou from "../../../persona_seeds/tsundere_ojou/persona.json" with { type: "json" }
export function mockConsole(
  records: () => readonly MemoryRecord[],
  details: Map<string, ArtifactDetail>
): ConsoleClient {
  const packs = new Map<string, PersonaSeed>([
    ["official/big_fish", fish],
    ["official/tsundere_ojou", ojou],
  ])
  const bundles = new Map<string, PersonaBundle>()
  const bundleFor = (reference: string): PersonaBundle => {
    const seed = packs.get(reference)
    if (!seed) throw new Error("人格包不存在")
    return structuredClone(
      bundles.get(reference) ?? {
        format: "seekmemory.persona-pack/v1",
        seed,
        licenseText: seed.license ?? "",
        artwork: null,
      }
    )
  }
  const digest = async (seed: PersonaSeed | PersonaBundle) => {
    const bytes = await crypto.subtle.digest(
      "SHA-256",
      new TextEncoder().encode(JSON.stringify(seed))
    )
    return [...new Uint8Array(bytes)]
      .map((n) => n.toString(16).padStart(2, "0"))
      .join("")
  }
  return {
    async rollbackPersona(command) {
      const current = details.get(command.id)
      if (
        !current ||
        current.artifact.header.family !== "persona" ||
        current.artifact.header.state !== "active"
      )
        throw new Error("人格不可用")
      if (
        !command.confirmed ||
        !command.reason.trim() ||
        command.reason.trim().length > 300
      )
        throw new Error("请确认并填写回滚原因")
      const target = current.versions.find(
        (v) => Number(v["revision"]) === command.revision
      )
      if (!target || command.revision === current.artifact.header.revision)
        throw new Error("目标版本无效")
      const parsed: unknown = JSON.parse(
        typeof target["content"] === "string" ? target["content"] : "{}"
      )
      const payload = detailSchema.parse({
        ...current,
        artifact: { ...current.artifact, payload: parsed },
      }).artifact.payload
      current.artifact.payload = structuredClone(payload)
      current.artifact.header.revision++
      current.versions.push({
        revision: current.artifact.header.revision,
        at: new Date().toISOString(),
        op: "revise",
        content: JSON.stringify(payload),
        reason: command.reason.trim(),
      })
      return {
        id: command.id,
        revision: current.artifact.header.revision,
        restoredRevision: command.revision,
      }
    },
    async graph() {
      const nodes = records().map((r) => ({
        id: r.id,
        kind: r.category,
        scope: r.scope,
        subject: "10002",
        state: r.state,
        label:
          r.scope === "shadow" || ["secret", "designated"].includes(r.category)
            ? "受保护的记忆"
            : r.title,
        createdAt: r.updatedAt,
        updatedAt: r.updatedAt,
        confidence: 0.8,
        protected:
          r.scope === "shadow" || ["secret", "designated"].includes(r.category),
      }))
      return recentGraph(
        {
          nodes,
          edges: nodes.slice(1).flatMap((n, i) => [
            {
              source: n.id,
              target: nodes[i]?.id ?? n.id,
              kind: "same_subject",
            },
          ]),
          total: nodes.length,
          limit: 120,
        },
        120
      )
    },
    async impressions(offset = 0) {
      const items = records()
        .filter((r) => r.category === "impression")
        .map((r, i) => ({
          id: r.id,
          subjectId: `third:demo-${i}`,
          subjectKind: "third_party",
          displayName: ["小林", "阿遥", "旅途中的朋友"][i % 3] ?? "朋友",
          summary: r.text,
          scope: r.scope,
          updatedAt: r.updatedAt,
          confidence: 0.85,
          evidenceCount: 2,
          revision: r.versions[0].revision,
        }))
      return {
        items: items.slice(offset, offset + 100),
        offset,
        limit: 100,
        total: items.length,
      }
    },
    async dream() {
      return {
        items: [
          {
            date: "2026-10-25",
            stopped: "call_budget",
            pending: 4,
            status: "done",
            batches: 3,
            written: 8,
            calls: 5,
            usageIn: 1600,
            usageOut: 520,
            errorCount: 0,
          },
          {
            date: "2026-10-24",
            status: "failed",
            batches: 2,
            written: 2,
            calls: 3,
            usageIn: 1100,
            usageOut: 250,
            errorCount: 1,
          },
        ],
        limit: 100,
      }
    },
    async packs(collection, offset = 0) {
      const items = await Promise.all(
        [...packs]
          .filter(([ref]) => ref.startsWith(collection + "/"))
          .map(async ([reference, seed]) => ({
            reference,
            artworkRef: bundles.get(reference)?.artwork
              ? reference + "@" + (await digest(bundleFor(reference)))
              : null,
            id: seed.id,
            name: seed.name,
            version: seed.version,
            description: seed.persona.slice(0, 120),
            license: seed.license ?? "",
            source: seed.source ?? "",
            contentRating: seed.content_rating ?? "general",
            locale: seed.locale ?? "zh-CN",
          }))
      )
      return {
        items: items.slice(offset, offset + 24),
        offset,
        limit: 24,
        total: items.length,
      }
    },
    async pack(reference) {
      const seed = packs.get(reference)
      if (!seed) throw new Error("人格包不存在")
      return {
        seed: structuredClone(seed),
        digest: await digest(bundleFor(reference)),
        licenseText: bundleFor(reference).licenseText,
      }
    },
    async packArtwork(reference) {
      const art = bundleFor(reference).artwork
      if (!art) throw new Error("人格包没有封面")
      return art
    },
    async packExport(reference) {
      return bundleFor(reference)
    },
    async persona(command) {
      if (command.operation === "importPack") {
        const bundle = bundleSchema.parse(command.pack)
        const reference = "mine/" + bundle.seed.id
        const previous = packs.get(reference)
        if (
          command.expectedVersion
            ? !previous ||
              previous.version !== command.expectedVersion ||
              bundle.seed.version === command.expectedVersion
            : !!previous
        )
          throw new Error("同名人格包已存在或版本冲突")
        if (
          bundle.artwork &&
          (!bundle.licenseText.trim() ||
            !bundle.seed.license?.trim() ||
            !bundle.seed.source?.trim())
        )
          throw new Error("带封面的人格包必须声明许可证和来源")
        bundles.set(reference, structuredClone(bundle))
        packs.set(reference, structuredClone(bundle.seed))
        return { reference }
      }
      if (command.operation === "import") {
        const reference = "mine/" + command.seed.id
        if (
          packs.has(reference) &&
          (!command.expectedVersion ||
            packs.get(reference)?.version !== command.expectedVersion ||
            command.seed.version === command.expectedVersion)
        )
          throw new Error("同名人格包已存在或版本冲突")
        packs.set(reference, seedSchema.parse(command.seed))
        bundles.delete(reference)
        return { reference }
      }
      if (command.operation === "remove") {
        if (!command.reference.startsWith("mine/"))
          throw new Error("内置包不可移除")
        packs.delete(command.reference)
        bundles.delete(command.reference)
        return { reference: command.reference }
      }
      const seed = packs.get(command.reference),
        current = details.get("n_persona_mock")
      if (!seed || !current) throw new Error("人格不存在")
      if (
        command.expectedId !== current.artifact.header.id ||
        command.expectedRevision !== current.artifact.header.revision
      )
        throw new Error("人格版本已改变，请刷新")
      if (
        command.expectedDigest !== (await digest(bundleFor(command.reference)))
      )
        throw new Error("人格包内容已更新，请重新预览")
      current.artifact.header.revision++
      current.artifact.payload = {
        text: seed.persona,
        origin: "seed",
        seed_id: seed.id,
        seed_version: seed.version,
      }
      current.versions.push({
        revision: current.artifact.header.revision,
        at: new Date().toISOString(),
        op: "revise",
        content: JSON.stringify(current.artifact.payload),
      })
      return {
        id: current.artifact.header.id,
        revision: current.artifact.header.revision,
        seedId: seed.id,
        seedVersion: seed.version,
      }
    },
  }
}
