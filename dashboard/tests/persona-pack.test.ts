import assert from "node:assert/strict"
import { test } from "node:test"
import {
  parsePackFile,
  readArtwork,
} from "../src/features/persona-store/pack-file.ts"
import { bundleSchema } from "../src/features/shell/model.ts"
import { mockConsole } from "../src/dev/mock-console.ts"

const seed = {
  id: "test-pack",
  version: "1",
  name: "测试",
  persona: "设定",
  license: "CC0-1.0",
  source: "original",
}
const png =
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jgV8AAAAASUVORK5CYII="

void test("legacy JSON imports into a portable envelope without chat evidence", () => {
  const result = parsePackFile(JSON.stringify(seed))
  assert.deepEqual(result.seed, seed)
  assert.equal(result.artwork, null)
  assert.throws(() =>
    parsePackFile(JSON.stringify({ ...seed, sources: ["private"] }))
  )
  assert.throws(() => parsePackFile(" ".repeat(3 * 1024 * 1024 + 1)))
  assert.equal(
    bundleSchema.safeParse({ ...result, format: "future/v2" }).success,
    false
  )
  assert.equal(
    bundleSchema.safeParse({ ...result, artwork: { path: "/private.png" } })
      .success,
    false
  )
})

void test("complete packs round trip through import, export, update and removal", async () => {
  const client = mockConsole(() => [], new Map())
  const pack = {
    ...parsePackFile(JSON.stringify(seed)),
    licenseText: "Original CC0 fixture",
    artwork: { mediaType: "image/png" as const, dataBase64: png },
  }
  await client.persona({ operation: "importPack", pack, confirmed: true })
  assert.deepEqual(await client.packExport("mine/test-pack"), pack)
  assert.deepEqual(await client.packArtwork("mine/test-pack"), pack.artwork)
  assert.ok((await client.packs("mine")).items[0]?.artworkRef)
  await assert.rejects(
    client.persona({ operation: "importPack", pack, confirmed: true })
  )
  const updated = { ...pack, seed: { ...seed, version: "2" } }
  await client.persona({
    operation: "importPack",
    pack: updated,
    expectedVersion: "1",
    confirmed: true,
  })
  await assert.rejects(
    client.persona({
      operation: "importPack",
      pack,
      expectedVersion: "1",
      confirmed: true,
    })
  )
  assert.deepEqual(await client.packExport("mine/test-pack"), updated)
  await client.persona({
    operation: "remove",
    reference: "mine/test-pack",
    confirmed: true,
  })
  assert.equal((await client.packs("mine")).total, 0)
  await assert.rejects(client.packArtwork("mine/test-pack"))
})

void test("cover chooser checks binary signature and byte limit before preview", async () => {
  const image = await readArtwork(
    new File([Buffer.from(png, "base64")], "cover.png")
  )
  assert.equal(image.dataBase64, png)
  await assert.rejects(readArtwork(new File(["<svg/>"], "fake.png")))
  await assert.rejects(
    readArtwork(new File([new Uint8Array(2 * 1024 * 1024 + 1)], "huge.png"))
  )
})
