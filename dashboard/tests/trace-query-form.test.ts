import assert from "node:assert/strict"
import { test } from "node:test"
import { Window } from "happy-dom"
import { act, createElement, type ReactNode } from "react"
import { createServer } from "vite"
import { z } from "zod"
import type { TraceQuery } from "../src/contracts/api.ts"
import type { ManagementClient } from "../src/features/control/model.ts"
import type { TraceSnapshot } from "../src/features/control/trace-model.ts"
import { mockClient } from "../src/dev/mock-client.ts"
import { demoTraces } from "../src/dev/mock-traces.ts"

void test("trace query form submits local times, rejects an inverted range, clears filters and explains recorded failures", async () => {
  const dom = new Window()
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
  type FormProps = { initialRun: string; onQuery: (query: TraceQuery) => void }
  const { TraceQueryForm } = z
    .object({
      TraceQueryForm: z.custom<(props: FormProps) => ReactNode>(
        (v) => typeof v === "function"
      ),
    })
    .parse(
      await vite.ssrLoadModule(
        "/src/features/control/views/trace-query-form.tsx"
      )
    )
  const queries: TraceQuery[] = []
  try {
    await act(async () =>
      root.render(
        createElement(TraceQueryForm, {
          initialRun: "4".repeat(32),
          onQuery: (query) => queries.push(query),
        })
      )
    )
    const form = dom.document.querySelector("form")
    assert.ok(form)
    const inputFor = (label: string) => {
      const element = [...node.querySelectorAll("label")].find(
        (item) => item.textContent === label
      )
      assert.ok(element?.htmlFor)
      const input = dom.document.getElementById(element.htmlFor)
      assert.ok(input instanceof dom.HTMLInputElement)
      return input
    }
    const setInput = async (label: string, value: string) => {
      const input = inputFor(label)
      // Use the native setter so React observes the subsequent input event.
      Object.getOwnPropertyDescriptor(
        dom.HTMLInputElement.prototype,
        "value"
      )?.set?.call(input, value)
      await act(async () =>
        input.dispatchEvent(new dom.Event("input", { bubbles: true }))
      )
    }
    const submit = () =>
      act(async () =>
        form.dispatchEvent(
          new dom.Event("submit", { bubbles: true, cancelable: true })
        )
      )
    assert.equal(inputFor("运行编号").pattern, "[a-f0-9]{32}")
    await setInput("最后更新起始时间", "2026-10-29T12:00")
    await setInput("最后更新结束时间", "2026-10-29T11:00")
    await submit()
    assert.equal(queries.length, 0)
    assert.match(
      node.querySelector('[role="alert"]')?.textContent ?? "",
      /结束时间不能早于/
    )
    await setInput("最后更新结束时间", "2026-10-29T13:00")
    const select = dom.document.querySelector("select")
    assert.ok(select)
    await act(async () => {
      select.value = "error"
      select.dispatchEvent(new dom.Event("change", { bubbles: true }))
    })
    await submit()
    assert.deepEqual(queries[0], {
      run_id: "4".repeat(32),
      status: "error",
      since: new Date("2026-10-29T12:00").toISOString(),
      until: new Date("2026-10-29T13:00").toISOString(),
    })
    const clear = [...node.querySelectorAll("button")].find(
      (button) => button.textContent === "清空查询"
    )
    assert.ok(clear)
    await act(async () => clear.click())
    assert.deepEqual(queries[1], {})
    assert.equal(inputFor("运行编号").value, "")
    assert.equal(inputFor("最后更新起始时间").value, "")
    assert.equal(select.value, "all")
    assert.equal(node.querySelector('[role="alert"]'), null)

    type TraceProps = {
      client: ManagementClient
      initialRun: string
      onInspect: (id: string) => void
    }
    const { RunTraces } = z
      .object({
        RunTraces: z.custom<(props: TraceProps) => ReactNode>(
          (v) => typeof v === "function"
        ),
      })
      .parse(
        await vite.ssrLoadModule("/src/features/control/views/run-traces.tsx")
      )
    await act(async () =>
      root.render(
        createElement(RunTraces, {
          client: mockClient,
          initialRun: "4".repeat(32),
          onInspect: () => {},
        })
      )
    )
    assert.match(node.textContent ?? "", /失败步骤：Agent 结束/)
    assert.match(node.textContent ?? "", /44444444444444444444444444444444/)
    const snapshot = demoTraces("memory")
    const run = snapshot.runs[0]
    assert.ok(run)
    await act(async () =>
      root.render(
        createElement(RunTraces, {
          client: {
            ...mockClient,
            async traces(): Promise<TraceSnapshot> {
              return {
                ...snapshot,
                runs: [{ ...run, status: "interrupted", partial: true }],
                events: snapshot.events
                  .filter((e) => e.run_id === run.id)
                  .slice(0, 2),
              }
            },
          },
          initialRun: "",
          onInspect: () => {},
        })
      )
    )
    assert.match(
      node.textContent ?? "",
      /未记录运行结束；最后步骤：准备模型请求/
    )
    assert.match(node.textContent ?? "", /无法据此确认失败原因/)
    assert.match(node.textContent ?? "", /时间轴可能不完整/)
    assert.ok(!node.textContent?.includes("失败步骤："))
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
