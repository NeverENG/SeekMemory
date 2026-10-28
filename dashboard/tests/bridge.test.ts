import assert from "node:assert/strict"
import { afterEach, test } from "node:test"
import { astrbotClient } from "../src/infrastructure/astrbot-client.ts"
import { recentGraph } from "../src/features/memory-graph/model.ts"
import { consoleClient } from "../src/infrastructure/console-client.ts"

afterEach(() => {
  Reflect.deleteProperty(globalThis, "window")
})

void test("graph reads one snapshot capped at 120 for local display limits", async () => {
  let calls = 0
  const client = consoleClient(async () => ({
    async apiGet(endpoint, query) {
      assert.equal(endpoint, "manage/graph")
      assert.equal(query, undefined)
      calls++
      return { nodes: [], edges: [], total: 5000, limit: 120 }
    },
    async apiPost() {
      throw new Error("Read-only scenario")
    },
  }))
  const snapshot = await client.graph()
  for (const limit of [40, 80, 120]) {
    const display = recentGraph(snapshot, limit)
    assert.equal(display.total, 5000)
  }
  assert.equal(calls, 1)
})

void test("production client requires the host Page bridge and never falls back to fixtures", async () => {
  Object.defineProperty(globalThis, "window", { configurable: true, value: {} })
  await assert.rejects(astrbotClient.records(), /AstrBot/)
})

void test("Page bridge uses relative plugin endpoints and validates unknown responses", async () => {
  const calls: unknown[] = []
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: {
      AstrBotPluginPage: {
        async ready() {
          calls.push("ready")
        },
        async apiGet(endpoint: string) {
          calls.push(endpoint)
          return { records: [] }
        },
        async apiPost(endpoint: string, body: unknown) {
          calls.push({ endpoint, body })
          return { id: "task-1" }
        },
      },
    },
  })
  assert.deepEqual(await astrbotClient.records(), [])
  assert.equal(await astrbotClient.task("weekly"), "task-1")
  assert.deepEqual(calls, [
    "ready",
    "manage/records",
    "ready",
    {
      endpoint: "manage/task",
      body: { kind: "weekly", confirmed: true },
    },
  ])
  await assert.rejects(astrbotClient.status())
})
