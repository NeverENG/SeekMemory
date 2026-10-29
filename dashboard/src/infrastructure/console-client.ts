import {
  artworkSchema,
  bundleSchema,
  rollbackResultSchema,
  graphSchema,
  impressionsSchema,
  dreamSchema,
  packsSchema,
  packDetailSchema,
  personaResultSchema,
  type ConsoleClient,
} from "../features/shell/model.ts"
interface Bridge {
  apiGet(endpoint: string, query?: Record<string, string>): Promise<unknown>
  apiPost(endpoint: string, body: unknown): Promise<unknown>
}
export function consoleClient(bridge: () => Promise<Bridge>): ConsoleClient {
  return {
    async rollbackPersona(command) {
      return rollbackResultSchema.parse(
        await (await bridge()).apiPost("manage/rollbackPersona", command)
      )
    },
    async graph() {
      return graphSchema.parse(await (await bridge()).apiGet("manage/graph"))
    },
    async impressions(offset = 0) {
      return impressionsSchema.parse(
        await (
          await bridge()
        ).apiGet("manage/impressions", { offset: String(offset) })
      )
    },
    async dream() {
      return dreamSchema.parse(await (await bridge()).apiGet("manage/dream"))
    },
    async packs(collection, offset = 0) {
      return packsSchema.parse(
        await (
          await bridge()
        ).apiGet("manage/packs", { collection, offset: String(offset) })
      )
    },
    async pack(reference) {
      return packDetailSchema.parse(
        await (await bridge()).apiGet("manage/pack", { reference })
      )
    },
    async packArtwork(reference) {
      return artworkSchema.parse(
        await (await bridge()).apiGet("manage/packArtwork", { reference })
      )
    },
    async packExport(reference) {
      return bundleSchema.parse(
        await (await bridge()).apiGet("manage/packExport", { reference })
      )
    },
    async persona(command) {
      return personaResultSchema.parse(
        await (await bridge()).apiPost("manage/persona", command)
      )
    },
  }
}
