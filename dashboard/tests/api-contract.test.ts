import assert from "node:assert/strict"
import { test } from "node:test"
import { mockClient } from "../src/dev/mock-client.ts"
import { apiOperations, validateApi } from "./contract-schema.ts"

void test("Mock 返回值及修订后的数据满足 OpenAPI 契约", async () => {
  assert.equal(apiOperations.length, 17)
  validateApi("traces", 200, await mockClient.traces())
  const records = await mockClient.records()
  validateApi("records", 200, { records })
  validateApi("status", 200, await mockClient.status())
  validateApi("events", 200, {
    events: await mockClient.events(),
    capacity: 500,
  })
  for (const record of records) {
    validateApi("detail", 200, await mockClient.detail(record.id))
  }
  const first = records[0]
  assert.ok(first)
  const detail = await mockClient.detail(first.id)
  const command = {
    id: first.id,
    expectedRevision: detail.artifact.header.revision,
    payload: detail.artifact.payload,
    state: first.state,
    scope: first.scope,
    confirmed: true,
    reason: "契约测试",
  } as const
  validateApi("update", 0, command)
  await mockClient.update(command)
  validateApi("detail", 200, await mockClient.detail(first.id))
  validateApi("records", 200, { records: await mockClient.records() })
  const query = { query: "咖啡", umo: first.session, speaker: "alice" }
  validateApi("diagnose", 0, query)
  validateApi("diagnose", 200, await mockClient.diagnose(query))
  validateApi("task", 200, { id: await mockClient.task("weekly") })
  await assert.rejects(mockClient.cancel("missing"), /Mock/)
})

void test("契约校验拒绝缺字段、错误标量及缺少确认的请求", () => {
  assert.throws(() => validateApi("status", 200, { ready: true }))
  assert.throws(() =>
    validateApi("events", 200, { events: [], capacity: "500" })
  )
  assert.throws(() =>
    validateApi("task", 0, { kind: "weekly", confirmed: false })
  )
  assert.throws(() => validateApi("cancel", 0, { confirmed: true }))
})
