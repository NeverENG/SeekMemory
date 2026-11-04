import { personaBlueprint } from "../src/features/persona-store/model.ts"
import { detailSchema } from "../src/features/control/model.ts"
import assert from "node:assert/strict"
import { test } from "node:test"
import { Window } from "happy-dom"
import { act, createElement, useEffect } from "react"
import { createRoot } from "react-dom/client"
import { parseRoute, seedSchema } from "../src/features/shell/model.ts"
import { filterGraph, layoutGraph } from "../src/features/memory-graph/model.ts"
import { loadGraph } from "../src/dev/load-fixtures.ts"
import { useResource } from "../src/features/shell/use-resource.ts"
import { useRoute } from "../src/features/shell/routing.ts"

void test("hash links validate pages and preserve encoded node identities", () => {
  assert.deepEqual(parseRoute("#/memory?node=a%2Fb%20c"), {
    page: "memory",
    node: "a/b c",
    revision: null,
  })
  assert.equal(parseRoute("#/persona?revision=3").revision, 3)
  assert.equal(parseRoute("#/persona?revision=wrong").revision, null)
  assert.equal(parseRoute("#/untrusted").page, "home")
  assert.deepEqual(
    parseRoute("#/traces?node=run-1"),
    parseRoute("#/system?section=traces&node=run-1")
  )
  assert.equal(parseRoute("#/system?section=traces").section, "traces")
})
void test("graph filtering intersects scope, identity, date and actual neighbors", () => {
  const graph = loadGraph(),
    original = JSON.stringify(graph)
  const result = filterGraph(graph, {
    query: "",
    kind: "all",
    scope: "shared",
    subject: "all",
    since: "2026-10-01",
    focus: "load-1",
  })
  assert.deepEqual(
    new Set(result.nodes.map((n) => n.id)),
    new Set(["load-0", "load-1", "load-2", "load-12", "load-990"])
  )
  assert.equal(
    filterGraph(graph, {
      query: "",
      kind: "fact",
      scope: "shadow",
      subject: "all",
      since: "",
      focus: "",
    }).nodes.length,
    0
  )
  assert.equal(JSON.stringify(graph), original)
  assert.equal(new Set(layoutGraph(graph).map((p) => p.id)).size, 1000)
  assert.ok(
    layoutGraph(graph).every(
      (p) => Number.isFinite(p.x) && Number.isFinite(p.y)
    )
  )
})
void test("persona blueprint import rejects Source and evidence fields", () => {
  const seed = { id: "test-pack", version: "1", name: "test", persona: "text" }
  assert.equal(
    seedSchema.safeParse({ ...seed, sources: [{ text: "secret" }] }).success,
    false
  )
  assert.equal(
    seedSchema.safeParse({ ...seed, evidence: ["private-id"] }).success,
    false
  )
})
void test("stale async results, unmount and hash back/forward do not leak old page state", async () => {
  const dom = new Window({ url: "http://localhost/#/home" })
  const before = Object.getOwnPropertyDescriptors(globalThis)
  for (const [key, value] of Object.entries({
    window: dom,
    document: dom.document,
    IS_REACT_ACT_ENVIRONMENT: true,
  }))
    Object.defineProperty(globalThis, key, {
      value,
      configurable: true,
      writable: true,
    })
  let finish: (value: string) => void = () => {
    throw new Error("not initialized")
  }
  const slow = () =>
    new Promise<string>((resolve) => {
      finish = resolve
    })
  const fast = () => Promise.resolve("fresh")
  let vm: ReturnType<typeof useResource<string>> | undefined
  let route: ReturnType<typeof useRoute> | undefined
  function Probe({ read }: { read: () => Promise<string> }) {
    const state = useResource(read),
      page = useRoute()
    useEffect(() => {
      vm = state
      route = page
    }, [state, page])
    return null
  }
  const root = createRoot(document.createElement("div"))
  try {
    await act(async () => root.render(createElement(Probe, { read: slow })))
    assert.equal(vm?.loading, true)
    await act(async () => root.render(createElement(Probe, { read: fast })))
    assert.equal(vm?.data, "fresh")
    await act(async () => finish("stale"))
    assert.equal(vm?.data, "fresh")
    for (const hash of [
      "#/memory?node=load-2",
      "#/home",
      "#/memory?node=load-2",
    ]) {
      await act(async () => {
        dom.location.hash = hash
        dom.dispatchEvent(new dom.HashChangeEvent("hashchange"))
      })
      assert.equal(route?.page, parseRoute(hash).page)
      assert.equal(route?.node, parseRoute(hash).node)
    }
    await act(async () => root.render(createElement(Probe, { read: slow })))
    await act(async () => root.unmount())
    await act(async () => finish("after-unmount"))
  } finally {
    await dom.happyDOM.close()
    for (const key of ["window", "document", "IS_REACT_ACT_ENVIRONMENT"]) {
      const descriptor = before[key]
      if (descriptor) Object.defineProperty(globalThis, key, descriptor)
      else Reflect.deleteProperty(globalThis, key)
    }
  }
})

void test("saving a blueprint preserves provenance/style and excludes private evidence", () => {
  const detail = detailSchema.parse({
    artifact: {
      header: {
        id: "p",
        family: "persona",
        revision: 2,
        state: "active",
        scope: "shared",
      },
      payload: {
        text: "Kind persona",
        style: { tone: "warm" },
        boundaries: ["Respect privacy"],
        seed_license: "CC0-1.0",
        seed_source: "original",
        content_rating: "unrated",
        locale: "zh-CN",
        corpus: [{ user: "PRIVATE_SENTINEL", assistant: "private" }],
        source_ids: ["secret"],
      },
    },
    versions: [],
    sources: [{ text: "PRIVATE_SENTINEL" }],
    ledger: [],
  })
  const result = personaBlueprint(detail, "My pack", "my-test")
  assert.equal(result.license, "CC0-1.0")
  assert.deepEqual(result.style, { tone: "warm" })
  assert.equal(result.content_rating, "unrated")
  assert.ok(!JSON.stringify(result).includes("PRIVATE_SENTINEL"))
  assert.equal(result.corpus, undefined)
})

void test("persona diffs identify changes and preserve both exact texts, including large input", async () => {
  const { personaDiff } = await import("../src/features/persona/diff.ts")
  for (const [before, after] of [
    ["你很耐心。你喜欢咖啡。", "你很耐心。你喜欢茶。"],
    ["", "新设定"],
    ["旧设定", ""],
    ["相同", "相同"],
    ["A。".repeat(300), "B。".repeat(300)],
  ]) {
    const changes = personaDiff(before ?? "", after ?? "")
    assert.equal(
      changes
        .filter((c) => c.kind !== "added")
        .map((c) => c.text)
        .join(""),
      before
    )
    assert.equal(
      changes
        .filter((c) => c.kind !== "removed")
        .map((c) => c.text)
        .join(""),
      after
    )
  }
  const changes = personaDiff("你很耐心。你喜欢咖啡。", "你很耐心。你喜欢茶。")
  assert.deepEqual(
    changes.map((c) => c.kind),
    ["same", "removed", "added"]
  )
})

void test("application labels require namespaced provenance and distinguish growth from pack metadata", async () => {
  const { packInstallLabel } =
    await import("../src/features/persona-store/model.ts")
  const pack = {
    reference: "official/fish",
    id: "fish",
    version: "2",
    digest: "a".repeat(64),
    settingsDigest: "b".repeat(64),
  }
  assert.equal(packInstallLabel(pack, null), "")
  assert.match(packInstallLabel(pack, { seedId: "fish" }), /来源未知/)
  const packApplication = {
    reference: pack.reference,
    version: "2",
    packDigest: pack.digest,
    settingsDigest: pack.settingsDigest,
    currentSettingsDigest: pack.settingsDigest,
    artworkDigest: null,
  }
  assert.match(packInstallLabel(pack, { packApplication }), /与应用时一致/)
  assert.equal(
    packInstallLabel({ ...pack, reference: "mine/fish" }, { packApplication }),
    ""
  )
  assert.match(
    packInstallLabel(pack, {
      packApplication: {
        ...packApplication,
        currentSettingsDigest: "c".repeat(64),
      },
    }),
    /当前设定已变化/
  )
  assert.match(
    packInstallLabel({ ...pack, digest: "d".repeat(64) }, { packApplication }),
    /仅包资源或其他元数据变化/
  )
  assert.match(
    packInstallLabel(
      { ...pack, version: "3", digest: "d".repeat(64) },
      { packApplication }
    ),
    /已保存包版本不同/
  )
})

void test("Dream distinguishes budget stops from completion and disabled scheduling", async () => {
  const { dreamStatus, dreamSchedule, dreamStopReason } =
    await import("../src/features/dream/model.ts")
  assert.equal(
    dreamStatus({ status: "done", stopped: "call_budget" }),
    "预算用尽，提前停止"
  )
  assert.match(dreamStopReason({ stopped: "call_budget" }), /调用次数上限/)
  assert.match(dreamStopReason({ stopped: "token_budget" }), /Token 预算上限/)
  assert.equal(dreamStatus({ status: "done", stopped: "" }), "整理完成")
  assert.equal(
    dreamStatus({ status: "failed", stopped: "call_budget" }),
    "需要检查"
  )
  assert.match(
    dreamSchedule({ dream_enabled: false, dream_time: "03:30" }),
    /已关闭/
  )
  assert.ok(
    !dreamSchedule({ dream_enabled: false, dream_time: "03:30" }).includes(
      "03:30"
    )
  )
  assert.match(
    dreamSchedule({ dream_enabled: true, dream_time: "03:30" }),
    /每日 03:30/
  )
  assert.match(dreamSchedule(undefined), /未获取/)
})

void test("mock rollback and package install preserve historical snapshots and reject stale previews", async () => {
  const { mockConsole } = await import("../src/dev/mock-console.ts")
  const detail = detailSchema.parse({
    artifact: {
      header: {
        id: "n_persona_mock",
        family: "persona",
        revision: 2,
        state: "active",
        scope: "shared",
      },
      payload: { text: "new" },
    },
    versions: [
      { revision: 1, content: JSON.stringify({ text: "old" }) },
      { revision: 2, content: JSON.stringify({ text: "new" }) },
    ],
    sources: [],
    ledger: [],
  })
  const client = mockConsole(() => [], new Map([["n_persona_mock", detail]]))
  await assert.rejects(
    client.rollbackPersona({
      id: "n_persona_mock",
      revision: 1,
      reason: " ",
      confirmed: true,
    })
  )
  const result = await client.rollbackPersona({
    id: "n_persona_mock",
    revision: 1,
    reason: "Restore",
    confirmed: true,
  })
  assert.equal(result.revision, 3)
  assert.equal(detail.artifact.payload["text"], "old")
  assert.equal(detail.versions.length, 3)
  const preview = await client.pack("official/big_fish")
  await client.persona({
    operation: "import",
    seed: preview.seed,
    confirmed: true,
  })
  const localPreview = await client.pack("mine/big_fish")
  await client.persona({
    operation: "import",
    seed: { ...preview.seed, version: "2" },
    expectedVersion: preview.seed.version,
    confirmed: true,
  })
  await assert.rejects(
    client.persona({
      operation: "install",
      reference: "mine/big_fish",
      expectedId: "n_persona_mock",
      expectedRevision: 3,
      expectedDigest: localPreview.digest,
      confirmed: true,
    }),
    /重新预览/
  )
  assert.equal(detail.artifact.header.revision, 3)
})
