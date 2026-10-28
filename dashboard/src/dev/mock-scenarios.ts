import type { ManagementClient } from "../features/control/model.ts"
export function scenarioClient(
  base: ManagementClient,
  scenario: "empty" | "loading" | "error"
): ManagementClient {
  const unavailable = async () => {
    if (scenario === "loading") return new Promise<never>(() => {})
    throw new Error("模拟网络错误：未连接真实宿主。切换正常数据可恢复。")
  }
  if (scenario !== "empty")
    return {
      ...base,
      status: unavailable,
      traces: unavailable,
      records: unavailable,
      events: unavailable,
      console: {
        graph: unavailable,
        impressions: unavailable,
        dream: unavailable,
        packs: unavailable,
        pack: unavailable,
        packArtwork: unavailable,
        packExport: unavailable,
        persona: unavailable,
        rollbackPersona: unavailable,
      },
    }
  return {
    ...base,
    status: async () => ({ ...(await base.status()), persona: null }),
    traces: async () => ({ ...(await base.traces()), runs: [], events: [] }),
    records: async () => [],
    events: async () => [],
    console: {
      graph: async () => ({ nodes: [], edges: [], total: 0, limit: 1000 }),
      impressions: async () => ({ items: [], total: 0, offset: 0, limit: 100 }),
      dream: async () => ({ items: [], limit: 100 }),
      packs: async () => ({ items: [], total: 0, offset: 0, limit: 24 }),
      pack: unavailable,
      packArtwork: unavailable,
      packExport: unavailable,
      persona: unavailable,
      rollbackPersona: unavailable,
    },
  }
}
