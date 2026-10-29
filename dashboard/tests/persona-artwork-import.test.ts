import assert from "node:assert/strict"
import { test } from "node:test"
import { Window } from "happy-dom"
import { act, createElement, useEffect } from "react"
import { createRoot } from "react-dom/client"
import { useArtworkImport } from "../src/features/persona-store/use-artwork-import.ts"

void test("replacing or cancelling an import discards late covers; failed reads can recover", async () => {
  const dom = new Window(),
    saved = Object.getOwnPropertyDescriptors(globalThis)
  for (const [key, value] of Object.entries({
    window: dom,
    document: dom.document,
    IS_REACT_ACT_ENVIRONMENT: true,
  }))
    Object.defineProperty(globalThis, key, { configurable: true, value })
  const bytes = Uint8Array.from([137, 80, 78, 71, 13, 10, 26, 10]),
    received: string[] = []
  let vm: ReturnType<typeof useArtworkImport> | undefined
  function Probe({ owner }: { owner: string }) {
    const state = useArtworkImport(() => received.push(owner))
    useEffect(() => {
      vm = state
    }, [state])
    return null
  }
  const root = createRoot(document.createElement("div"))
  const slowFile = () => {
    let finish: (value: ArrayBuffer) => void = () => {
      throw new Error("read not started")
    }
    const file = new File([bytes], "cover.png")
    Object.defineProperty(file, "arrayBuffer", {
      value: () => new Promise<ArrayBuffer>((resolve) => (finish = resolve)),
    })
    return { file, finish: () => finish(bytes.buffer) }
  }
  const start = (file: File) => {
    assert.ok(vm)
    return vm.readFile(file)
  }
  let pending: Promise<void> | undefined
  try {
    await act(async () =>
      root.render(createElement(Probe, { key: "old", owner: "old" }))
    )
    const old = slowFile()
    await act(async () => {
      pending = start(old.file)
    })
    assert.equal(vm?.reading, true)
    await act(async () =>
      root.render(createElement(Probe, { key: "new", owner: "new" }))
    )
    await act(async () => {
      old.finish()
      await pending
    })
    assert.deepEqual(received, [])
    await act(async () => start(new File(["invalid"], "broken.png")))
    assert.ok(vm?.error)
    assert.equal(vm?.reading, false)
    await act(async () => start(new File([bytes], "valid.png")))
    assert.equal(vm?.error, "")
    assert.deepEqual(received, ["new"])
    const cancelled = slowFile()
    await act(async () => {
      pending = start(cancelled.file)
    })
    await act(async () => root.unmount())
    await act(async () => {
      cancelled.finish()
      await pending
    })
    assert.deepEqual(received, ["new"])
  } finally {
    await act(async () => root.unmount())
    await dom.happyDOM.close()
    for (const key of ["window", "document", "IS_REACT_ACT_ENVIRONMENT"]) {
      const descriptor = saved[key]
      if (descriptor) Object.defineProperty(globalThis, key, descriptor)
      else Reflect.deleteProperty(globalThis, key)
    }
  }
})
