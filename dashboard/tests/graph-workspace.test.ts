import assert from "node:assert/strict"
import { test } from "node:test"
import { Window } from "happy-dom"
import { act, createElement, type ReactNode } from "react"
import { createServer } from "vite"
import { z } from "zod"
import { mockClient } from "../src/dev/mock-client.ts"
import { loadGraph } from "../src/dev/load-fixtures.ts"
import type {
  ConsoleClient,
  GraphSort,
  GraphSnapshot,
} from "../src/features/shell/model.ts"

void test("graph switches server sorting, keeps local counts, and offers library access on empty/error", async () => {
  const dom = new Window({ url: "http://localhost/#/memory" })
  const before = Object.getOwnPropertyDescriptors(globalThis)
  const globals = {
    window: dom,
    document: dom.document,
    navigator: dom.navigator,
    HTMLElement: dom.HTMLElement,
    Element: dom.Element,
    Node: dom.Node,
    requestAnimationFrame: dom.requestAnimationFrame.bind(dom),
    cancelAnimationFrame: dom.cancelAnimationFrame.bind(dom),
    getComputedStyle: dom.getComputedStyle.bind(dom),
    MutationObserver: dom.MutationObserver,
    ResizeObserver: dom.ResizeObserver,
    IS_REACT_ACT_ENVIRONMENT: true,
  }
  for (const [key, value] of Object.entries(globals))
    Object.defineProperty(globalThis, key, { configurable: true, value })
  const vite = await createServer({
    server: { middlewareMode: true, watch: null, hmr: false },
    appType: "custom",
  })
  const { createRoot } = await import("react-dom/client")
  const node = document.createElement("div")
  document.body.append(node)
  const root = createRoot(node)
  const { MemoryMap } = z
    .object({
      MemoryMap: z.custom<
        (props: {
          client: ConsoleClient
          initialNode: string
          onInspect: (id: string) => void
          readDetail: typeof mockClient.detail
        }) => ReactNode
      >((value) => typeof value === "function"),
    })
    .parse(
      await vite.ssrLoadModule(
        "/src/features/memory-graph/views/memory-map.tsx"
      )
    )
  assert.ok(mockClient.console)
  const calls: GraphSort[] = []
  const pending: Array<(value: GraphSnapshot) => void> = []
  const client: ConsoleClient = {
    ...mockClient.console,
    graph: (sort = "weight") => {
      calls.push(sort)
      return new Promise((resolve) => pending.push(resolve))
    },
  }
  const snapshot = {
    ...loadGraph(),
    limit: 120,
    nodes: loadGraph().nodes.slice(0, 120),
    edges: [],
  }
  const render = async (port: ConsoleClient) => {
    await act(async () =>
      root.render(
        createElement(MemoryMap, {
          client: port,
          initialNode: "",
          onInspect: () => {},
          readDetail: (id) => mockClient.detail(id),
        })
      )
    )
  }
  const change = async (label: string, value: string) => {
    const select = dom.document.querySelector(`select[aria-label="${label}"]`)
    assert.ok(select instanceof dom.HTMLSelectElement)
    await act(async () => {
      select.value = value
      select.dispatchEvent(new dom.Event("change", { bubbles: true }))
    })
  }
  try {
    await render(client)
    assert.deepEqual(calls, ["weight"])
    await act(async () => pending[0]?.(snapshot))
    const count = dom.document.querySelector(
      'select[aria-label="星图记忆数量上限"]'
    )
    assert.ok(count instanceof dom.HTMLSelectElement)
    assert.equal(count.value, "80")
    for (const value of ["40", "120", "80"])
      await change("星图记忆数量上限", value)
    assert.deepEqual(calls, ["weight"])
    await change("星图排序", "recent")
    assert.deepEqual(calls, ["weight", "recent"])
    assert.match(dom.document.body.textContent ?? "", /正在读取/)
    // Replacing the port while a request is pending must discard its late response.
    await render({
      ...client,
      graph: async () => ({ nodes: [], edges: [], limit: 120, total: 1000 }),
    })
    await act(async () => pending[1]?.(snapshot))
    assert.match(dom.document.body.textContent ?? "", /当前快照没有匹配的记忆/)
    assert.ok(dom.document.querySelector('a[href="#/library"]'))
    await render({
      ...client,
      graph: async () => {
        throw new Error("测试读取失败")
      },
    })
    assert.match(
      dom.document.querySelector('[role="alert"]')?.textContent ?? "",
      /测试读取失败/
    )
    assert.ok(dom.document.querySelector('a[href="#/library"]'))
  } finally {
    await act(async () => root.unmount())
    await vite.close()
    await dom.happyDOM.close()
    for (const key of Object.keys(globals)) {
      const descriptor = before[key]
      if (descriptor) Object.defineProperty(globalThis, key, descriptor)
      else Reflect.deleteProperty(globalThis, key)
    }
  }
})
