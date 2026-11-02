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
  copyPack,
  validatePack,
} from "../src/features/persona-store/authoring.ts"
import { mockConsole } from "../src/dev/mock-console.ts"
import type {
  ConsoleClient,
  PersonaBundle,
} from "../src/features/shell/model.ts"

const pack: PersonaBundle = {
  format: "seekmemory.persona-pack/v1",
  seed: {
    id: "studio-test",
    version: "1",
    name: "Fixture",
    persona: "Warm persona",
    style: { tone: "warm", nested: { keep: [1, true] } },
    boundaries: ["Privacy"],
    license: "CC0-1.0",
    source: "Original fixture",
    locale: "en",
    content_rating: "general",
  },
  licenseText: "Original license",
  artwork: null,
}

void test("dedicated persona edits preserve provenance and metadata; copies keep authored assets and settings", () => {
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
        persona_name: "Fixture",
        text: "Original",
        style: pack.seed.style,
        boundaries: pack.seed.boundaries,
        base_text: "Original",
        custom: { keep: true },
        seed_source: "origin",
        corpus_hash: "known",
      },
    },
    versions: [],
    sources: [],
    ledger: [],
  })
  const payload = editedPayload(detail, {
    ...settingsFromDetail(detail),
    persona: "Edited",
  })
  assert.equal(payload["base_text"], "Original")
  assert.deepEqual(payload["custom"], { keep: true })
  assert.equal(payload["seed_source"], "origin")
  assert.throws(
    () =>
      settingsFromDetail({
        ...detail,
        artifact: {
          ...detail.artifact,
          payload: { ...detail.artifact.payload, style: [] },
        },
      }),
    /请先在高级编辑中核对/
  )
  const copied = copyPack(pack)
  assert.notEqual(copied.seed.id, pack.seed.id)
  assert.deepEqual(copied.seed.style, pack.seed.style)
  assert.equal(copied.licenseText, pack.licenseText)
  const invalid = validatePack(
    { ...pack, seed: { ...pack.seed, persona: " " } },
    null
  )
  assert.equal(invalid.success, false)
})

void test("pack form labels fields, preserves structured settings, and hides concurrency tokens; cancel writes nothing", async () => {
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
    server: { middlewareMode: true, watch: null },
    appType: "custom",
  })
  const { createRoot } = await import("react-dom/client")
  const node = document.createElement("div")
  document.body.append(node)
  const root = createRoot(node)
  type Props = {
    initial: { pack: PersonaBundle; title: string }
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
  const client = mockConsole(() => [], new Map())
  let saved = 0,
    cancelled = 0
  const render = async (bundle = pack) =>
    act(async () =>
      root.render(
        createElement(exported.PackEditor, {
          key: bundle.seed.id,
          initial: { pack: bundle, title: "Create fixture" },
          client,
          blocked: false,
          onSaved: async () => {
            saved++
          },
          onCancel: () => {
            cancelled++
          },
        })
      )
    )
  const button = (text: string) => {
    const value = [...node.querySelectorAll("button")].find(
      (item) => item.textContent === text
    )
    assert.ok(value, text)
    return value
  }
  try {
    await render()
    assert.equal(
      node.querySelector('input[aria-label="被更新人格包的旧版本"]'),
      null
    )
    for (const text of [
      "姓名",
      "人格正文",
      "相处边界",
      "许可证名称",
      "设定与封面来源",
      "新包版本",
    ])
      assert.ok(node.textContent?.includes(text), text)
    assert.match(node.textContent ?? "", /完整保留/)
    await act(async () => button("取消").click())
    assert.equal(cancelled, 1)
    assert.equal((await client.packs("mine")).total, 0)
    await act(async () =>
      dom.document
        .querySelector("form")
        ?.dispatchEvent(
          new dom.Event("submit", { bubbles: true, cancelable: true })
        )
    )
    assert.equal(saved, 1)
    assert.deepEqual(await client.packExport("mine/studio-test"), pack)
    // An invalid field gives an inline correction instead of losing authored metadata.
    await render({
      ...pack,
      seed: { ...pack.seed, id: "studio-invalid", persona: " " },
    })
    await act(async () =>
      dom.document
        .querySelector("form")
        ?.dispatchEvent(
          new dom.Event("submit", { bubbles: true, cancelable: true })
        )
    )
    assert.match(
      node.querySelector('[role="alert"]')?.textContent ?? "",
      /请填写人格正文/
    )
    assert.equal((await client.packs("mine")).total, 1)
    await render({ ...pack, seed: { ...pack.seed, id: "Invalid ID" } })
    assert.match(
      node.querySelector('[role="alert"]')?.textContent ?? "",
      /包标识需为 2–64 位/
    )
    assert.ok(button("保存新包").disabled)
    assert.equal((await client.packs("mine")).total, 1)
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
