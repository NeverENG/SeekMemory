import type { GraphSnapshot, GraphSort } from "../features/shell/model.ts"
import { displayGraph } from "../features/memory-graph/model.ts"

/** Simulate server ranking using synthetic strengths at the mock boundary. */
export function mockGraph(
  graph: GraphSnapshot,
  sort: GraphSort
): GraphSnapshot {
  const weights = new Map(graph.nodes.map((node, i) => [node.id, 1 + (i % 7)]))
  const nodes = graph.nodes
    .filter((node) => node.state === "active")
    .sort(
      (a, b) =>
        (sort === "weight"
          ? (weights.get(b.id) ?? 1) - (weights.get(a.id) ?? 1)
          : 0) ||
        Date.parse(b.updatedAt) - Date.parse(a.updatedAt) ||
        b.id.localeCompare(a.id)
    )
  return displayGraph({ ...graph, nodes }, 120)
}
