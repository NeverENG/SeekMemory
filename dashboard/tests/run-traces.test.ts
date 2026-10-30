import assert from "node:assert/strict"
import { test } from "node:test"
import { Window } from "happy-dom"
import { act, createElement, useEffect } from "react"
import { createRoot } from "react-dom/client"
import { useRunTraces } from "../src/features/control/use-run-traces.ts"
import {
  filterRuns,
  runTimeline,
  tracesSchema,
  type TraceSnapshot,
} from "../src/features/control/trace-model.ts"
import type { ManagementClient } from "../src/features/control/model.ts"
import type { TraceQuery } from "../src/contracts/api.ts"
import { mockClient } from "../src/dev/mock-client.ts"
import { demoTraces } from "../src/dev/mock-traces.ts"

function deferred<T>() {
  let resolve: (value: T) => void = () => {
    throw new Error("Promise not initialized")
  }
  const promise = new Promise<T>((finish) => {
    resolve = finish
  })
  return { promise, resolve }
}

async function mountTraces(client: ManagementClient) {
  const dom = new Window()
  const globals = {
    window: dom,
    document: dom.document,
    IS_REACT_ACT_ENVIRONMENT: true,
  }
  const previous = Object.getOwnPropertyDescriptors(globalThis)
  for (const [key, value] of Object.entries(globals))
    Object.defineProperty(globalThis, key, {
      configurable: true,
      writable: true,
      value,
    })
  let current: ReturnType<typeof useRunTraces> | undefined
  function Probe({ source }: { source: ManagementClient }) {
    const vm = useRunTraces(source)
    useEffect(() => {
      current = vm
    }, [vm])
    return null
  }
  const root = createRoot(document.createElement("div"))
  await act(async () => {
    root.render(createElement(Probe, { source: client }))
  })
  return {
    get vm() {
      assert.ok(current)
      return current
    },
    async replaceClient(next: ManagementClient) {
      await act(async () => {
        root.render(createElement(Probe, { source: next }))
      })
    },
    async close() {
      await act(async () => {
        root.unmount()
      })
      await dom.happyDOM.close()
      for (const key of Object.keys(globals)) {
        const descriptor = previous[key]
        if (descriptor) Object.defineProperty(globalThis, key, descriptor)
        else Reflect.deleteProperty(globalThis, key)
      }
    },
  }
}

void test("overlapping filters retain independent delivery and timeline order", () => {
  const snapshot = demoTraces("memory")
  const injected = filterRuns(snapshot, "recalled_and_injected")
  assert.equal(injected.length, 2)
  assert.equal(injected[0]?.delivered, true)
  assert.equal(injected[1]?.delivered, false)
  assert.equal(filterRuns(snapshot, "fallback_used")[0]?.id, injected[0]?.id)
  assert.equal(filterRuns(snapshot, "recalled_but_withheld").length, 2)
  assert.equal(filterRuns(snapshot, "not_recalled").length, 1)
  const first = injected[0]
  assert.ok(first)
  const reversed = { ...snapshot, events: [...snapshot.events].reverse() }
  assert.deepEqual(
    runTimeline(reversed, first.id).map((e) => e.sequence),
    [1, 2, 3, 4, 5, 6, 7]
  )
  assert.throws(() =>
    tracesSchema.parse({ ...snapshot, unexpected: "raw message" })
  )
})

void test("refresh failure clears stale results and retry recovers", async (t) => {
  let failed = false
  const h = await mountTraces({
    ...mockClient,
    async traces() {
      if (failed) throw new Error("offline")
      return demoTraces("memory")
    },
  })
  t.after(() => h.close())
  assert.equal(h.vm.total, 4)
  await act(async () => {
    h.vm.setFilter("not_recalled")
  })
  assert.equal(h.vm.total, 1)
  assert.deepEqual(h.vm.active?.flags, ["not_recalled"])
  failed = true
  await act(async () => {
    await h.vm.refresh()
  })
  assert.equal(h.vm.error, "offline")
  assert.equal(h.vm.active, null)
  failed = false
  await act(async () => {
    await h.vm.refresh()
  })
  assert.equal(h.vm.error, "")
  assert.equal(h.vm.total, 1)
})

void test("a late response from a replaced client cannot overwrite fresh traces", async (t) => {
  const old = deferred<TraceSnapshot>()
  const h = await mountTraces({ ...mockClient, traces: () => old.promise })
  t.after(() => h.close())
  assert.equal(h.vm.loading, true)
  await h.replaceClient({
    ...mockClient,
    async traces() {
      return { ...demoTraces("new"), runs: [], events: [] }
    },
  })
  await act(async () => {
    old.resolve(demoTraces("old"))
  })
  assert.equal(h.vm.total, 0)
  assert.equal(h.vm.loading, false)
})

void test("changing query clears old results and ignores late responses; clearing and retry use the active query", async (t) => {
  const old = deferred<TraceSnapshot>()
  const next = deferred<TraceSnapshot>()
  const queries: TraceQuery[] = []
  let failed = false
  const h = await mountTraces({
    ...mockClient,
    async traces(query = {}) {
      queries.push(query)
      if (queries.length === 1) return old.promise
      if (queries.length === 2) return next.promise
      if (failed) throw new Error("offline")
      return demoTraces("fresh")
    },
  })
  t.after(() => h.close())
  await act(async () =>
    h.vm.applyQuery({ status: "error", run_id: "4".repeat(32) })
  )
  assert.equal(h.vm.loading, true)
  assert.equal(h.vm.active, null)
  await act(async () => old.resolve(demoTraces("stale")))
  assert.equal(h.vm.total, 0)
  assert.equal(h.vm.loading, true)
  await act(async () =>
    next.resolve({ ...demoTraces("filtered"), runs: [], events: [] })
  )
  assert.equal(h.vm.loading, false)
  assert.equal(h.vm.total, 0)
  assert.deepEqual(queries[1], { status: "error", run_id: "4".repeat(32) })
  failed = true
  await act(async () => h.vm.applyQuery({}))
  assert.equal(h.vm.error, "offline")
  failed = false
  await act(async () => h.vm.refresh())
  assert.equal(h.vm.error, "")
  assert.equal(h.vm.total, 4)
  assert.deepEqual(queries.slice(-2), [{}, {}])
})
