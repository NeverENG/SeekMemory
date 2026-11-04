import assert from "node:assert/strict"
import { test } from "node:test"
import { Window } from "happy-dom"
import { act, createElement, type ReactNode } from "react"
import { createServer } from "vite"
import { z } from "zod"
import {
  detailSchema,
  type ManagementClient,
} from "../src/features/control/model.ts"
import { mockClient } from "../src/dev/mock-client.ts"

void test("persona size and network errors retain an editable draft while revision conflicts require review", async () => {
  const dom = new Window({ url: "http://localhost/" }),
    before = Object.getOwnPropertyDescriptors(globalThis)
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
  type Props = {
    client: ManagementClient
    id: string
    blocked: boolean
    onSaved: () => Promise<void>
    onClose: () => void
  }
  const exported = z
    .object({
      PersonaEditor: z.custom<(props: Props) => ReactNode>(
        (value) => typeof value === "function"
      ),
    })
    .parse(
      await vite.ssrLoadModule("/src/features/persona/views/persona-editor.tsx")
    )
  let closed = 0
  const settle = async () => {
    for (let step = 0; step < 100; step++) {
      await act(async () => {
        await new Promise((resolve) => setTimeout(resolve, 10))
      })
      if (!dom.document.body.textContent?.includes("保存中…")) return
    }
    assert.fail("Save did not settle")
  }
  const button = () => {
    const value = [...dom.document.querySelectorAll("button")].find(
      (item) => item.textContent === "保存当前人格的新版本"
    )
    assert.ok(value)
    return value
  }
  try {
    for (const mode of ["size", "network", "conflict"]) {
      const detail = detailSchema.parse({
        artifact: {
          header: {
            id: mode,
            family: "persona",
            revision: 2,
            state: "active",
            scope: "shared",
          },
          payload: {
            persona_name: "保留的名字",
            text: "星".repeat(9000),
            ...(mode === "size" ? { metadata: "星".repeat(70000) } : {}),
          },
        },
        versions: [],
        sources: [],
        ledger: [],
      })
      let changed = false
      const writes: Parameters<ManagementClient["update"]>[0][] = []
      const client: ManagementClient = {
        ...mockClient,
        detail: async () =>
          changed
            ? {
                ...detail,
                artifact: {
                  ...detail.artifact,
                  header: { ...detail.artifact.header, revision: 3 },
                },
              }
            : detail,
        update: async (command) => {
          writes.push(command)
          if (mode === "conflict") changed = true
          if (writes.length === 1) throw new Error("Save rejected")
          return
        },
      }
      await act(async () =>
        root.render(
          createElement(exported.PersonaEditor, {
            key: mode,
            client,
            id: mode,
            blocked: false,
            onSaved: async () => {},
            onClose: () => {
              closed++
            },
          })
        )
      )
      await settle()
      const reason = [...dom.document.querySelectorAll("label")].find(
        (item) => item.textContent === "修改原因"
      )
      assert.ok(reason?.htmlFor)
      const field = dom.document.getElementById(reason.htmlFor)
      assert.ok(field)
      await act(async () => {
        Object.getOwnPropertyDescriptor(
          dom.HTMLInputElement.prototype,
          "value"
        )?.set?.call(field, "Review correction")
        field.dispatchEvent(new dom.Event("input", { bubbles: true }))
      })
      const submit = async () => {
        await act(async () => {
          dom.document
            .querySelector("form")
            ?.dispatchEvent(
              new dom.Event("submit", { bubbles: true, cancelable: true })
            )
        })
        await settle()
      }
      await submit()
      if (mode === "size") {
        assert.match(
          dom.document.body.textContent ?? "",
          /192 KiB.*元数据.*重试/
        )
        assert.equal(writes.length, 0)
      } else assert.match(dom.document.body.textContent ?? "", /Save rejected/)
      const name = dom.document.querySelector('input[maxlength="80"]')
      assert.equal(name?.getAttribute("value"), "保留的名字")
      assert.equal(
        dom.document.querySelector("fieldset")?.disabled,
        mode === "conflict"
      )
      assert.equal(button().disabled, mode === "conflict")
      if (mode === "network") {
        await submit()
        assert.equal(writes.length, 2)
        assert.equal(writes[0]?.expectedRevision, 2)
        assert.equal(writes[1]?.expectedRevision, 2)
        assert.equal(closed, 1)
      }
    }
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
