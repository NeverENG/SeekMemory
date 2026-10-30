import assert from "node:assert/strict"
import { test } from "node:test"
import { Window } from "happy-dom"
import { act, createElement, type ReactNode } from "react"
import { createServer } from "vite"
import { z } from "zod"
import { mockClient } from "../src/dev/mock-client.ts"
import type {
  ManagementClient,
  RuntimeStatus,
} from "../src/features/control/model.ts"

void test("connection form labels credentials, blocks duplicate submission while loading, and can retry after an error", async () => {
  const dom = new Window({ url: "http://127.0.0.1:8766/" })
  const before = Object.getOwnPropertyDescriptors(globalThis)
  const globals = {
    window: dom,
    document: dom.document,
    navigator: dom.navigator,
    HTMLElement: dom.HTMLElement,
    IS_REACT_ACT_ENVIRONMENT: true,
  }
  for (const [key, value] of Object.entries(globals))
    Object.defineProperty(globalThis, key, { configurable: true, value })
  const vite = await createServer({
    server: { middlewareMode: true, watch: null },
    appType: "custom",
  })
  const { createRoot } = await import("react-dom/client")
  const node = document.createElement("div")
  document.body.append(node)
  const root = createRoot(node)
  type Props = {
    defaultUrl: string
    notice: string
    onConnect: (url: string, token: string) => Promise<void>
  }
  const exported = z
    .object({
      ConnectionForm: z.custom<(props: Props) => ReactNode>(
        (value) => typeof value === "function"
      ),
    })
    .parse(
      await vite.ssrLoadModule("/src/features/connection/connection-form.tsx")
    )
  let rejectConnection: (reason: Error) => void = () =>
    assert.fail("connection not pending")
  let calls = 0
  try {
    await act(async () =>
      root.render(
        createElement(exported.ConnectionForm, {
          defaultUrl: "http://127.0.0.1:8766/api/",
          notice: "",
          onConnect: async (url) => {
            assert.equal(url, "http://127.0.0.1:8766/api/")
            calls++
            return new Promise<void>((_resolve, reject) => {
              rejectConnection = reject
            })
          },
        })
      )
    )
    assert.equal(
      node.querySelector('label[for="console-api"]')?.textContent,
      "API 地址"
    )
    assert.equal(
      node.querySelector('label[for="console-token"]')?.textContent,
      "管理员令牌"
    )
    const password = node.querySelector("#console-token")
    assert.equal(password?.getAttribute("type"), "password")
    assert.equal(password?.getAttribute("autocomplete"), "off")
    const form = dom.document.querySelector("form")
    assert.ok(form)
    await act(async () =>
      form.dispatchEvent(
        new dom.Event("submit", { bubbles: true, cancelable: true })
      )
    )
    assert.equal(calls, 1)
    assert.equal(node.querySelector("button")?.disabled, true)
    assert.equal(
      node.querySelector("#console-api")?.hasAttribute("disabled"),
      true
    )
    await act(async () =>
      form.dispatchEvent(
        new dom.Event("submit", { bubbles: true, cancelable: true })
      )
    )
    assert.equal(calls, 1)
    await act(async () => rejectConnection(new Error("PRIVATE_SENTINEL")))
    assert.match(
      node.querySelector('[role="alert"]')?.textContent ?? "",
      /连接失败/
    )
    assert.ok(!node.textContent?.includes("PRIVATE_SENTINEL"))
    assert.equal(node.querySelector("button")?.disabled, false)
    assert.equal(dom.localStorage.length, 0)
    assert.equal(dom.sessionStorage.length, 0)
    type RuntimeProps = {
      status: RuntimeStatus
      busy: boolean
      client: ManagementClient
      onAction: () => void
    }
    const runtime = z
      .object({
        RuntimePanel: z.custom<(props: RuntimeProps) => ReactNode>(
          (value) => typeof value === "function"
        ),
      })
      .parse(
        await vite.ssrLoadModule(
          "/src/features/control/views/runtime-panel.tsx"
        )
      )
    const status = await mockClient.status()
    await act(async () =>
      root.render(
        createElement(runtime.RuntimePanel, {
          status: {
            ...status,
            persona: null,
            capabilities: { maintenanceTasks: false },
          },
          busy: false,
          client: mockClient,
          onAction: () => assert.fail("unavailable maintenance cannot start"),
        })
      )
    )
    assert.match(node.textContent ?? "", /独立控制台未启用/)
    assert.ok(!node.textContent?.includes("AstrBot"))
    for (const button of node.querySelectorAll("button"))
      assert.equal(button.disabled, true)
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
