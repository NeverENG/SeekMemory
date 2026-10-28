import type { GraphSnapshot } from "../shell/model.ts"
export type Point = { id: string; x: number; y: number }
export const kindLabels: Record<string, string> = {
  persona: "人格",
  impression: "印象",
  fact: "事实",
  scene: "场景",
  detail: "细节",
  media: "媒体资料",
  example: "对话示例",
  secret: "保密提示",
  designated: "托付记忆",
}
export const kindColors: Record<string, string> = {
  persona: "var(--graph-persona)",
  impression: "var(--graph-impression)",
  fact: "var(--graph-fact)",
  scene: "var(--graph-scene)",
  detail: "var(--graph-detail)",
  media: "var(--graph-media)",
  example: "var(--graph-example)",
  secret: "var(--graph-secret)",
  designated: "var(--graph-designated)",
}
export function layoutGraph(graph: GraphSnapshot): Point[] {
  const kinds = [...new Set(graph.nodes.map((n) => n.kind))].sort()
  const counts = new Map<string, number>()
  return graph.nodes.map((node) => {
    const cluster = kinds.indexOf(node.kind),
      i = counts.get(node.kind) ?? 0
    counts.set(node.kind, i + 1)
    const angle = (cluster * Math.PI * 2) / Math.max(1, kinds.length)
    const r = 18 * Math.sqrt(i),
      spiral = i * 2.399963229728653
    return {
      id: node.id,
      x: Math.cos(angle) * 220 + Math.cos(spiral) * r,
      y: Math.sin(angle) * 180 + Math.sin(spiral) * r,
    }
  })
}
export function filterGraph(
  graph: GraphSnapshot,
  filter: {
    query: string
    kind: string
    scope: string
    subject: string
    since: string
    focus: string
  }
): GraphSnapshot {
  const neighbors = new Set([filter.focus])
  for (const e of graph.edges) {
    if (e.source === filter.focus) neighbors.add(e.target)
    if (e.target === filter.focus) neighbors.add(e.source)
  }
  const nodes = graph.nodes.filter(
    (n) =>
      (!filter.query ||
        `${n.label} ${n.id}`
          .toLowerCase()
          .includes(filter.query.toLowerCase())) &&
      (filter.kind === "all" || n.kind === filter.kind) &&
      (filter.scope === "all" || n.scope === filter.scope) &&
      (filter.subject === "all" || n.subject === filter.subject) &&
      (!filter.since || n.createdAt >= filter.since) &&
      (!filter.focus || neighbors.has(n.id))
  )
  const ids = new Set(nodes.map((n) => n.id))
  return {
    ...graph,
    nodes,
    edges: graph.edges.filter((e) => ids.has(e.source) && ids.has(e.target)),
  }
}

export const memoryLimits = [40, 80, 120] as const
export function recentGraph(
  graph: GraphSnapshot,
  limit: number
): GraphSnapshot {
  const bound = Math.min(120, Math.max(1, Math.floor(limit) || 80))
  const timestamp = (value: string) => Date.parse(value) || 0
  const nodes = [...graph.nodes]
    .sort(
      (a, b) =>
        timestamp(b.updatedAt) - timestamp(a.updatedAt) ||
        b.id.localeCompare(a.id)
    )
    .slice(0, bound)
  const ids = new Set(nodes.map((node) => node.id))
  return {
    ...graph,
    limit: bound,
    nodes,
    edges: graph.edges.filter(
      (edge) => ids.has(edge.source) && ids.has(edge.target)
    ),
  }
}
