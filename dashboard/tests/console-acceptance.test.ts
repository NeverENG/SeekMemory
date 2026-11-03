import assert from "node:assert/strict"
import { test } from "node:test"
import { newPackId } from "../src/features/persona-store/pack-id.ts"
import { seedSchema } from "../src/features/shell/model.ts"
import {
  displayGraph,
  recentGraph,
} from "../src/features/memory-graph/model.ts"
import {
  focusOrbit,
  layoutSphere,
  rotatePoint,
} from "../src/features/memory-graph/scene.ts"
import { loadGraph } from "../src/dev/load-fixtures.ts"

void test("saving a blueprint generates valid unique IDs without secure-context randomUUID", () => {
  const descriptor = Object.getOwnPropertyDescriptor(globalThis, "crypto")
  const getRandomValues = crypto.getRandomValues.bind(crypto)
  Object.defineProperty(globalThis, "crypto", {
    configurable: true,
    value: { getRandomValues },
  })
  try {
    const ids = Array.from({ length: 500 }, () => newPackId())
    assert.equal(new Set(ids).size, ids.length)
    for (const id of ids)
      assert.equal(
        seedSchema.safeParse({
          id,
          name: "Test",
          version: "1",
          persona: "A test persona",
        }).success,
        true
      )
  } finally {
    if (descriptor) Object.defineProperty(globalThis, "crypto", descriptor)
  }
})

void test("display limits remain capped at 120 and focus brings any selected node to the front", () => {
  const graph = loadGraph()
  assert.equal(recentGraph(graph, 80).nodes.length, 80)
  const full = recentGraph(graph, 1000)
  assert.equal(full.nodes.length, 120)
  assert.equal(full.limit, 120)
  const sphere = layoutSphere(full)
  assert.equal(sphere.stars.length, 120)
  for (const star of sphere.stars) {
    const projected = rotatePoint(star, focusOrbit(star))
    assert.ok(Math.abs(projected.x) < 1e-10)
    assert.ok(Math.abs(projected.y) < 1e-10)
    assert.ok(projected.z > 0.99)
  }
})

void test("display preserves server rank across limits and snapshot filters without dangling edges", () => {
  const graph = loadGraph()
  const before = JSON.stringify(graph)
  for (const limit of [40, 80, 120]) {
    const result = displayGraph(graph, limit)
    assert.deepEqual(result.nodes, graph.nodes.slice(0, limit))
    assert.ok(result.edges.length <= 2 * limit)
    const ids = new Set(result.nodes.map((n) => n.id))
    assert.ok(result.edges.every((e) => ids.has(e.source) && ids.has(e.target)))
  }
  assert.equal(JSON.stringify(graph), before)
})
