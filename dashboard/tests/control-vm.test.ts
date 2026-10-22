import assert from "node:assert/strict"
import { test } from "node:test"
import { Window } from "happy-dom"
import { act, createElement, useEffect } from "react"
import { createRoot } from "react-dom/client"
import { useControl } from "../src/features/control/use-control.ts"
import type {
  ManagementClient,
  RuntimeStatus,
} from "../src/features/control/model.ts"
import type { MemoryRecord } from "../src/features/memory/model.ts"
import { mockMemories } from "../src/dev/mock-data.ts"

const base = mockMemories[0]
assert.ok(base)
const records: readonly MemoryRecord[] = [
  { ...base, id: "a", scope: "private", session: "session-a" },
  { ...base, id: "b", scope: "shared", session: "session-b" },
  { ...base, id: "c", scope: "shadow", session: "session-b" },
]
const idle: RuntimeStatus = {
  ready: true,
  activeTask: null,
  checks: [],
  pending: [],
  pendingTopics: [],
  extractionPolicy: {
    backlogThreshold: 30,
    topicTtlSeconds: 86400,
    maxTopicsPerBatch: 6,
  },
  capacity: {
    state: "normal",
    actions: ["schedule_extraction"],
    reasons: [],
    pressure: 0.08,
    snapshot: {
      sourceRows: 32,
      sourceBytes: 4096,
      pendingRows: 8,
      deferredRows: 0,
      deadRows: 0,
      databaseBytes: 1048576,
      artifactCount: 12,
      artifactBytes: 8192,
      contextChars: 120,
      traceRows: 3,
    },
    queue: { pending: 8, retrying: 0, deferred: 0, extracted: 24, dead: 0 },
  },
  checkpointPending: null,
  schedulerCount: 3,
  config: {},
}

function clientWith(overrides: Partial<ManagementClient>): ManagementClient {
  return {
    async records() {
      return records
    },
    async status() {
      return idle
    },
    async events() {
      return []
    },
    async detail() {
      throw new Error("Not used in workspace tests")
    },
    async update() {
      throw new Error("Not used in workspace tests")
    },
    async diagnose() {
      throw new Error("Not used in workspace tests")
    },
    async task() {
      return "new-task"
    },
    async cancel() {},
    ...overrides,
  }
}

function deferred<T>() {
  let resolve: (value: T) => void = () => {
    throw new Error("Promise not initialized")
  }
  const promise = new Promise<T>((finish) => {
    resolve = finish
  })
  return { promise, resolve }
}

async function mountControl(client: ManagementClient) {
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
  let current: ReturnType<typeof useControl> | undefined
  function Probe({ source }: { source: ManagementClient }) {
    const vm = useControl(source)
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

void test("workspace filters compose in the view model without importing UI components", async (t) => {
  const h = await mountControl(clientWith({}))
  t.after(() => h.close())
  await act(async () => {
    h.vm.setScope("shared")
    h.vm.setSession("session-b")
  })
  const source = h.vm.source
  assert.ok(source.status === "ready")
  assert.deepEqual(
    source.records.map((item) => item.id),
    ["b"]
  )
  assert.deepEqual(h.vm.sessions, ["session-a", "session-b"])
  assert.equal(records.length, 3)
})

void test("post-write refresh supersedes an in-flight read and ignores its late result", async (t) => {
  const old = deferred<readonly MemoryRecord[]>()
  let reads = 0
  const h = await mountControl(
    clientWith({
      records: () => (++reads === 1 ? old.promise : Promise.resolve([])),
    })
  )
  t.after(() => h.close())
  await act(async () => {
    await h.vm.refreshAfterWrite()
  })
  await act(async () => {
    old.resolve(records)
  })
  assert.deepEqual(h.vm.source, { status: "ready", records: [] })
  assert.equal(reads, 2)
})

void test("task confirmation keeps its original ID and prevents duplicate submissions", async (t) => {
  let runtime = { ...idle, activeTask: { id: "task-a", kind: "extract" } }
  const finished = deferred<void>()
  const cancelled: string[] = []
  const h = await mountControl(
    clientWith({
      async status() {
        return runtime
      },
      cancel(id) {
        cancelled.push(id)
        return finished.promise
      },
    })
  )
  t.after(() => h.close())
  await act(async () => {
    h.vm.requestAction("cancel")
  })
  await act(async () => {
    await h.vm.executeAction()
  })
  assert.deepEqual(cancelled, [])
  await act(async () => {
    h.vm.setConfirmed(true)
  })
  runtime = { ...idle, activeTask: { id: "task-b", kind: "weekly" } }
  await act(async () => {
    await h.vm.refresh()
  })
  const execute = h.vm.executeAction
  await act(async () => {
    const first = execute()
    await execute()
    finished.resolve()
    await first
  })
  assert.deepEqual(cancelled, ["task-a"])
  assert.equal(h.vm.action, null)
  assert.equal(h.vm.busy, false)
})

void test("replacing the injected client invalidates the previous client's reads", async (t) => {
  const old = deferred<readonly MemoryRecord[]>()
  const h = await mountControl(clientWith({ records: () => old.promise }))
  t.after(() => h.close())
  await h.replaceClient(
    clientWith({
      async records() {
        return []
      },
    })
  )
  await act(async () => {
    old.resolve(records)
  })
  assert.deepEqual(h.vm.source, { status: "ready", records: [] })
})
