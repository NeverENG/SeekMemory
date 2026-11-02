import assert from "node:assert/strict"
import { test } from "node:test"
import { Window } from "happy-dom"
import { act, createElement, type ReactNode } from "react"
import { createServer } from "vite"
import { z } from "zod"
import { detailSchema } from "../src/features/control/model.ts"
import {
  editedPayload,
  settingsFromDetail,
} from "../src/features/persona/settings.ts"
import {
  validatePack,
  type PackDraft,
} from "../src/features/persona-store/authoring.ts"
import { mockConsole } from "../src/dev/mock-console.ts"
import type {
  ConsoleClient,
  PersonaBundle,
} from "../src/features/shell/model.ts"

const pack: PersonaBundle = {
  format: "seekmemory.persona-pack/v1",
  seed: {
    id: "review-fixture",
    version: "1",
    name: "Saved",
    persona: "Warm persona",
    style: { nested: { keep: [true, 1] } },
    boundaries: ["Privacy"],
  },
  licenseText: "Original license",
  artwork: null,
}

void test("Chinese edits include preserved metadata in the byte limit and allow renaming unchanged grown text", () => {
  const detail = detailSchema.parse({
    artifact: {
      header: {
        id: "persona",
        family: "persona",
        revision: 3,
        state: "active",
        scope: "shared",
      },
      payload: {
        text: "星".repeat(20000) + "\n你先回应情绪。",
        persona_name: "星灯",
        base_text: "星".repeat(20000),
        custom: { keep: true },
      },
    },
    versions: [],
    sources: [],
    ledger: [],
  })
  const payload = editedPayload(detail, {
    ...settingsFromDetail(detail),
    name: "新名字",
  })
  assert.equal(payload["text"], detail.artifact.payload["text"])
  assert.deepEqual(payload["custom"], { keep: true })
  assert.throws(
    () =>
      editedPayload(
        {
          ...detail,
          artifact: {
            ...detail.artifact,
            payload: { ...detail.artifact.payload, extra: "星".repeat(70000) },
          },
        },
        settingsFromDetail(detail)
      ),
    /192 KiB.*元数据.*重试/
  )
  assert.equal(
    validatePack({ ...pack, seed: { ...pack.seed, version: "   " } }, null)
      .success,
    false
  )
  const normalized = validatePack(
    { ...pack, seed: { ...pack.seed, version: " 2 " } },
    null
  )
  assert.ok(normalized.success)
  assert.equal(normalized.data.seed.version, "2")
})

void test("pack failures retain editable drafts; only observed concurrent changes require review", async () => {
  const dom = new Window({ url: "http://localhost/" }),
    before = Object.getOwnPropertyDescriptors(globalThis)
  const globals = {
    window: dom,
    document: dom.document,
    navigator: dom.navigator,
    HTMLElement: dom.HTMLElement,
    Element: dom.Element,
    Node: dom.Node,
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
    initial: PackDraft
    client: ConsoleClient
    blocked: boolean
    onSaved: () => Promise<void>
    onCancel: () => void
  }
  const exported = z
    .object({
      PackEditor: z.custom<(props: Props) => ReactNode>(
        (value) => typeof value === "function"
      ),
    })
    .parse(
      await vite.ssrLoadModule(
        "/src/features/persona-store/views/pack-editor.tsx"
      )
    )
  let saved = 0
  const render = async (initial: PackDraft, client: ConsoleClient) =>
    act(async () =>
      root.render(
        createElement(exported.PackEditor, {
          key: initial.pack.seed.id,
          initial,
          client,
          blocked: false,
          onSaved: async () => {
            saved++
          },
          onCancel: () => {},
        })
      )
    )
  const settle = async () => {
    for (let step = 0; step < 100; step++) {
      await act(async () => {
        await new Promise((resolve) => setTimeout(resolve, 10))
      })
      if (!node.textContent?.includes("保存中…")) return
    }
    assert.fail("Save did not settle")
  }
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
  const input = (label: string) => {
    const field = [...node.querySelectorAll("label")]
      .find((value) => value.textContent?.startsWith(label))
      ?.querySelector("input")
    assert.ok(field, label)
    return field
  }
  const button = (label: string) => {
    const value = [...node.querySelectorAll("button")].find(
      (item) => item.textContent === label
    )
    assert.ok(value, label)
    return value
  }
  try {
    for (const [index, failure] of [
      new Error("Backend validation rejected"),
      new TypeError("Network unavailable"),
    ].entries()) {
      const client = mockConsole(() => [], new Map()),
        original = client.persona.bind(client)
      const baseline = {
        ...pack,
        seed: { ...pack.seed, id: `recover-${index}` },
      }
      await original({
        operation: "importPack",
        pack: baseline,
        confirmed: true,
      })
      const target = await client.packLookup(`mine/${baseline.seed.id}`)
      let rejected = false
      client.persona = async (command) => {
        if (!rejected) {
          rejected = true
          throw failure
        }
        return original(command)
      }
      // The second case also loses connectivity during the failure probe.
      const lookup = client.packLookup.bind(client)
      if (index === 1)
        client.packLookup = async () => {
          throw new Error("Still offline")
        }
      await render(
        {
          title: "Edit",
          target,
          pack: {
            ...baseline,
            seed: { ...baseline.seed, name: "Unsaved draft", version: "2" },
          },
        },
        client
      )
      await submit()
      assert.match(node.textContent ?? "", new RegExp(failure.message))
      assert.equal(input("姓名").value, "Unsaved draft")
      assert.equal(node.querySelector("fieldset")?.disabled, false)
      assert.equal(button("保存包更新").disabled, false)
      assert.doesNotMatch(node.textContent ?? "", /替换草稿/)
      assert.equal(
        (await lookup(`mine/${baseline.seed.id}`)).pack?.seed.version,
        "1"
      )
      client.packLookup = lookup
      await submit()
      assert.equal(
        (await lookup(`mine/${baseline.seed.id}`)).pack?.seed.name,
        "Unsaved draft"
      )
      assert.deepEqual(
        (await client.packExport(`mine/${baseline.seed.id}`)).seed.style,
        pack.seed.style
      )
    }
    assert.equal(saved, 2)
    const client = mockConsole(() => [], new Map())
    await client.persona({ operation: "importPack", pack, confirmed: true })
    const target = await client.packLookup("mine/review-fixture")
    await render(
      {
        title: "Conflict",
        target,
        pack: {
          ...pack,
          seed: { ...pack.seed, name: "My draft", version: "2" },
        },
      },
      client
    )
    assert.ok(target.digest)
    await client.persona({
      operation: "importPack",
      confirmed: true,
      pack: {
        ...pack,
        seed: { ...pack.seed, name: "Concurrent author", version: "3" },
      },
      expectedVersion: "1",
      expectedDigest: target.digest,
    })
    await submit()
    assert.equal(node.querySelector("fieldset")?.disabled, true)
    assert.equal(input("姓名").value, "My draft")
    assert.equal(button("保存包更新").disabled, true)
    await act(async () => button("重新载入已保存包并核对（替换草稿）").click())
    await settle()
    assert.equal(input("姓名").value, "Concurrent author")
    assert.equal(node.querySelector("fieldset")?.disabled, false)
    assert.equal(
      (await client.packLookup("mine/review-fixture")).pack?.seed.version,
      "3"
    )
    assert.equal(saved, 2)
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
