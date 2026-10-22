import {
  selectAttribution,
  selectDisclosure,
} from "../src/features/control/model.ts"
import assert from "node:assert/strict"
import test from "node:test"
import {
  detailSchema,
  eventSchema,
  statusSchema,
  updateSchema,
} from "../src/features/control/model.ts"

void test("editor commands require confirmation, a revision and an audit reason", () => {
  const command = {
    id: "memory-1",
    expectedRevision: 3,
    payload: { text: "A corrected fact", level: "fact" },
    scope: "private",
    state: "active",
    reason: "Correction",
    confirmed: true,
  }
  assert.equal(updateSchema.safeParse(command).success, true)
  for (const invalid of [
    { ...command, confirmed: false },
    { ...command, reason: "  " },
    { ...command, expectedRevision: 0 },
    { ...command, payload: [] },
    { ...command, scope: "public" },
    { ...command, extra: "untrusted" },
  ])
    assert.equal(updateSchema.safeParse(invalid).success, false)
})

void test("detail keeps raw evidence and additional header fields without trusting malformed identities", () => {
  const value = {
    artifact: {
      header: {
        id: "memory-1",
        family: "secret",
        revision: 2,
        state: "forgotten",
        scope: "shadow",
        lineage: { sources: ["source-1"] },
      },
      payload: { ref: "vault", shadow_text: "A promise" },
    },
    versions: [],
    sources: [],
    ledger: [],
  }
  assert.equal(
    detailSchema.parse(value).artifact.header["lineage"] !== undefined,
    true
  )
  assert.equal(
    detailSchema.safeParse({
      ...value,
      artifact: {
        ...value.artifact,
        header: { ...value.artifact.header, revision: "2" },
      },
    }).success,
    false
  )
})

void test("runtime status supports an unavailable engine while retaining diagnostics", () => {
  const value = {
    ready: false,
    checks: [{ name: "engine", ok: false, detail: "Unavailable" }],
    activeTask: null,
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
    schedulerCount: 0,
    config: {},
  }
  assert.equal(statusSchema.parse(value).ready, false)
  assert.equal(
    statusSchema.safeParse({ ...value, schedulerCount: -1 }).success,
    false
  )
})

void test("legacy logs remain readable without fabricating source metadata", () => {
  const event = eventSchema.parse({
    id: "old",
    at: "2026-10-21",
    kind: "plugin",
    status: "ready",
    message: "Legacy event",
    taskId: "",
  })
  assert.equal(event.source, null)
  assert.equal(event.durationMs, null)
  assert.deepEqual(event.context, {})
})

void test("structured logs preserve source, context and bounded exception frames", () => {
  const source = {
    module: "seekmemory.main",
    file: "main.py",
    function: "_flush",
    line: 100,
  }
  const input = {
    id: "new",
    at: "2026-10-21",
    kind: "extract",
    status: "failed",
    message: "Stage interrupted",
    taskId: "task-1",
    level: "ERROR",
    stage: "session.extract",
    source,
    durationMs: 1200,
    context: { messages: 8 },
    error: { type: "TimeoutError", frames: [source] },
  }
  const event = eventSchema.parse(input)
  assert.deepEqual(event.source, source)
  assert.equal(event.error?.frames[0]?.function, "_flush")
  assert.equal(
    eventSchema.safeParse({ ...input, source: { ...source, line: -1 } })
      .success,
    false
  )
  assert.equal(
    eventSchema.safeParse({ ...input, context: { payload: {} } }).success,
    false
  )
})

void test("主体与事件时间保持独立，旧记录不伪造归属和日期", () => {
  const detail = detailSchema.parse({
    artifact: {
      header: {
        id: "a",
        family: "memory",
        revision: 1,
        state: "active",
        scope: "shared",
        subject_id: "subject-2",
        said_by: "speaker-1",
        time: {
          created: "2026-10-19",
          updated: "2026-10-21",
          valid_from: "2026-10-19",
          valid_to: null,
        },
      },
      payload: { subject_kind: "third_party" },
    },
    versions: [],
    sources: [],
    ledger: [],
  })
  const info = selectAttribution(detail)
  assert.equal(info.subjectId, "subject-2")
  assert.equal(info.saidBy, "speaker-1")
  assert.equal(info.subjectKind, "third_party")
  assert.equal(info.created, "2026-10-19")
  assert.equal(info.validTo, null)
  const legacy = detailSchema.parse({
    ...detail,
    artifact: {
      header: {
        id: "old",
        family: "memory",
        revision: 1,
        state: "active",
        scope: "private",
      },
      payload: {},
    },
  })
  assert.deepEqual(selectAttribution(legacy), {
    subjectId: null,
    saidBy: null,
    subjectKind: null,
    created: null,
    validFrom: null,
    validTo: null,
  })
})

void test("披露展示保留静默和未知级别，不把缺失或损坏结果当成全文许可", () => {
  const result = {
    block: "",
    info: {
      disclosure: {
        a: "full",
        b: "paraphrase",
        c: "hint",
        d: "silence",
        e: "future",
      },
    },
    visible: ["a", "b", "c", "d", "e", "unchecked"],
    excluded: [],
  }
  assert.deepEqual(
    selectDisclosure(result).map((item) => item.level),
    ["full", "paraphrase", "hint", "silence", "future"]
  )
  assert.deepEqual(selectDisclosure({ ...result, info: {} }), [])
  assert.deepEqual(
    selectDisclosure({ ...result, info: { disclosure: { a: 1 } } }),
    []
  )
})
