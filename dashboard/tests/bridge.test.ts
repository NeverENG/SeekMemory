import assert from "node:assert/strict"
import { afterEach, test } from "node:test"
import { astrbotClient } from "../src/infrastructure/astrbot-client.ts"

afterEach(() => {
  Reflect.deleteProperty(globalThis, "window")
})

void test("production client requires the host Page bridge and never falls back to fixtures", async () => {
  Object.defineProperty(globalThis, "window", { configurable: true, value: {} })
  await assert.rejects(astrbotClient.records(), /AstrBot/)
})

void test("Page bridge uses relative plugin endpoints and validates unknown responses", async () => {
  const calls: unknown[] = []
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: {
      AstrBotPluginPage: {
        async ready() {
          calls.push("ready")
        },
        async apiGet(endpoint: string) {
          calls.push(endpoint)
          return { records: [] }
        },
        async apiPost(endpoint: string, body: unknown) {
          calls.push({ endpoint, body })
          return { id: "task-1" }
        },
      },
    },
  })
  assert.deepEqual(await astrbotClient.records(), [])
  assert.equal(await astrbotClient.task("weekly"), "task-1")
  assert.deepEqual(calls, [
    "ready",
    "manage/records",
    "ready",
    {
      endpoint: "manage/task",
      body: { kind: "weekly", confirmed: true },
    },
  ])
  await assert.rejects(astrbotClient.status())
})

void test("history import uploads through the host file bridge and validates its metadata", async () => {
  const calls: unknown[] = []
  const preview = {
    format: "json",
    version: "0.0.2",
    platform: "qq",
    conversationType: "private",
    name: "private chat",
    members: [
      { platformId: "bot-1", accountName: "Bot" },
      { platformId: "user-1", accountName: "User" },
    ],
    senderCounts: { "bot-1": 1, "user-1": 1 },
    messageCount: 2,
    messageRows: 2,
    skippedCount: 0,
    missingIdCount: 0,
    firstAt: "2026-10-20T03:00:00+00:00",
    lastAt: "2026-10-20T03:00:01+00:00",
    warnings: [],
  }
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: {
      AstrBotPluginPage: {
        async ready() {},
        async apiGet(endpoint: string) {
          calls.push(endpoint)
          return { tasks: [] }
        },
        async apiPost(endpoint: string, body: unknown) {
          calls.push({ endpoint, body })
          return endpoint.endsWith("importValidate")
            ? {
                preview: {
                  ...preview,
                  uniqueSourceCount: 2,
                  duplicateCount: 0,
                },
              }
            : { id: "import-1" }
        },
        async upload(endpoint: string, file: File) {
          calls.push({ endpoint, filename: file.name })
          return {
            stageKey: "0123456789abcdef0123456789abcdef",
            filename: file.name,
            size: file.size,
            preview,
          }
        },
      },
    },
  })
  const historyImport = astrbotClient.historyImport
  assert.ok(historyImport)
  const file = new File(["{}"], "private.json", { type: "application/json" })
  const uploaded = await historyImport.uploadImport(file)
  assert.equal(uploaded.preview.messageCount, 2)
  const validated = await historyImport.validateImport({
    stageKey: uploaded.stageKey,
    botPlatformId: "bot-1",
    targetPlatformId: "user-1",
    targetUmo: "qq:FriendMessage:user-1",
    botMemberId: "bot-1",
    targetMemberId: "user-1",
  })
  assert.equal(validated.uniqueSourceCount, 2)
  assert.deepEqual(calls[0], {
    endpoint: "manage/importUpload",
    filename: "private.json",
  })
  assert.deepEqual(calls[1], {
    endpoint: "manage/importValidate",
    body: {
      stageKey: uploaded.stageKey,
      botPlatformId: "bot-1",
      targetPlatformId: "user-1",
      targetUmo: "qq:FriendMessage:user-1",
      botMemberId: "bot-1",
      targetMemberId: "user-1",
    },
  })
})
