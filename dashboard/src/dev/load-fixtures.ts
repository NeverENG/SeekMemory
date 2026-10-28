import type { ManagementClient } from "../features/control/model.ts"
import type { GraphSnapshot } from "../features/shell/model.ts"
import { recentGraph } from "../features/memory-graph/model.ts"
export function loadGraph(): GraphSnapshot {
  const kinds = [
    "fact",
    "scene",
    "detail",
    "impression",
    "persona",
    "media",
    "example",
    "secret",
  ]
  const nodes = Array.from({ length: 1000 }, (_, i) => ({
    id: `load-${i}`,
    kind: kinds[i % 8] ?? "fact",
    scope: "shared",
    subject: `person-${i % 30}`,
    state: "active",
    label: `性能预览记忆 ${i}`,
    createdAt: new Date(Date.UTC(2026, 9, 25, 0, i)).toISOString(),
    updatedAt: new Date(Date.UTC(2026, 9, 25, 0, i)).toISOString(),
    confidence: 0.8,
    protected: i % 8 === 7,
  }))
  const edges = nodes.flatMap((n, i) => [
    { source: n.id, target: `load-${(i + 1) % 1000}`, kind: "related" },
    { source: n.id, target: `load-${(i + 11) % 1000}`, kind: "same_subject" },
  ])
  return { nodes, edges, total: 1000, limit: 1000 }
}
export function loadClient(base: ManagementClient): ManagementClient {
  const port = base.console
  if (!port) throw new Error("Missing console fixture")
  return {
    ...base,
    detail: async (id) => {
      const node = loadGraph().nodes.find((item) => item.id === id)
      if (!node) return base.detail(id)
      return {
        artifact: {
          header: {
            id,
            family: "memory",
            revision: 1,
            state: "active",
            scope: "shared",
          },
          payload: {
            text: `${node.label}。这是一条虚构的压力预览数据，用来检查点击后完整正文、时间和状态的展示。实际连接宿主后，此处读取选中的记忆详情。`,
          },
        },
        versions: [],
        sources: [],
        ledger: [],
      }
    },
    console: {
      ...port,
      graph: async () => recentGraph(loadGraph(), 120),
      impressions: async () => ({
        items: Array.from({ length: 100 }, (_, i) => ({
          id: `load-person-${i}`,
          subjectId: `third:${i}`,
          subjectKind: "third_party",
          displayName: `朋友 ${i}`,
          summary: "这是一段用于验证长内容布局和卡片数量的虚构印象。".repeat(
            10
          ),
          scope: "shared",
          updatedAt: "2026-10-25",
          confidence: 0.8,
          evidenceCount: 10,
          revision: 1,
        })),
        total: 100,
        offset: 0,
        limit: 100,
      }),
      dream: async () => ({
        items: Array.from({ length: 100 }, (_, i) => ({
          date: new Date(Date.UTC(2026, 9, 25 - i)).toISOString().slice(0, 10),
          status: "done",
          batches: 3,
          written: 8,
          calls: 5,
          usageIn: 1600,
          usageOut: 520,
          errorCount: 0,
        })),
        limit: 100,
      }),
    },
    traces: async () => {
      const source = await base.traces(),
        first = source.runs[0]
      if (!first) return source
      return {
        ...source,
        runs: Array.from({ length: 500 }, (_, i) => ({
          ...first,
          id: `load-run-${i}`,
        })),
      }
    },
  }
}
