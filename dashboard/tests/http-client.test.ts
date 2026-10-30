import assert from "node:assert/strict"
import { spawn, spawnSync } from "node:child_process"
import { mkdtempSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { resolve } from "node:path"
import { test } from "node:test"
import {
  consoleBaseUrl,
  httpClient,
} from "../src/infrastructure/http-client.ts"

void test("HTTP client uses the selected base URL, encoded queries and memory-only bearer headers", async () => {
  assert.equal(
    consoleBaseUrl("http://127.0.0.1:8766/api").href,
    "http://127.0.0.1:8766/api/"
  )
  for (const url of [
    "https://example.com/api",
    "http://user:password@localhost/api",
    "http://localhost/api?token=x",
    "http://localhost/api#x",
  ]) {
    assert.throws(() => consoleBaseUrl(url))
  }
  const originalFetch = globalThis.fetch
  const controller = new AbortController()
  const token = "test-only-token"
  try {
    globalThis.fetch = async (input, options) => {
      assert.ok(input instanceof URL)
      assert.equal(
        String(input),
        "http://127.0.0.1:9876/custom/manage/detail?id=a%2Fb+%3F%26%23"
      )
      assert.equal(
        new Headers(options?.headers).get("Authorization"),
        `Bearer ${token}`
      )
      assert.equal(options?.credentials, "omit")
      assert.equal(options?.redirect, "error")
      assert.equal(options?.cache, "no-store")
      assert.ok(!String(input).includes(token))
      return Response.json(
        { status: "error", message: "PRIVATE_SENTINEL", data: null },
        { status: 404 }
      )
    }
    const client = httpClient("http://127.0.0.1:9876/custom/", token, {
      signal: controller.signal,
      onUnauthorized() {
        assert.fail("not a login error")
      },
    })
    await assert.rejects(
      client.detail("a/b ?&#"),
      (error: unknown) =>
        error instanceof Error &&
        /不存在/.test(error.message) &&
        !error.message.includes("PRIVATE_SENTINEL")
    )
    controller.abort()
    await assert.rejects(client.detail("a/b ?&#"), /连接已结束/)
  } finally {
    globalThis.fetch = originalFetch
  }
})

void test("HTTP client reads and edits through the real standalone API without an AstrBot bridge", async () => {
  const root = resolve(import.meta.dirname, "../..")
  const data = mkdtempSync(resolve(tmpdir(), "seekmemory-http-client-"))
  const python = process.env["SEEKMEMORY_TEST_PYTHON"] ?? "python3"
  const token = "test-console-admin-token-1234567890"
  const seeded = spawnSync(
    python,
    [
      "scripts/bootstrap_persona.py",
      "--db",
      resolve(data, "memory.db"),
      "--file",
      "persona_seeds/big_fish/persona.json",
    ],
    { cwd: root, encoding: "utf8" }
  )
  assert.equal(seeded.status, 0, seeded.stderr)
  const traced = spawnSync(
    python,
    [
      "-c",
      `
from pathlib import Path
from types import SimpleNamespace
from store.run_trace import TraceStore
from app.runtime.tracing import RunTracer
import sys
extras = {}
event = SimpleNamespace(get_extra=extras.get, set_extra=extras.__setitem__)
tracer = RunTracer(TraceStore(Path(sys.argv[1]) / "run_traces.jsonl"))
tracer.begin(event)
tracer.request(event, {"query": "PRIVATE_TRACE_SENTINEL", "final_ids": ["n_1"]})
tracer.response(event, "error")
tracer.done(event, "error")
`,
      data,
    ],
    { cwd: root, encoding: "utf8" }
  )
  assert.equal(traced.status, 0, traced.stderr)
  const server = spawn(
    python,
    ["scripts/console_http.py", "--data-dir", data, "--port", "0"],
    {
      cwd: root,
      env: { ...process.env, SEEKMEMORY_CONSOLE_TOKEN: token },
      stdio: ["ignore", "pipe", "pipe"],
    }
  )
  let stderr = ""
  server.stderr.on("data", (data: Buffer) => {
    stderr += data.toString()
  })
  try {
    const url = await new Promise<string>((resolveUrl, reject) => {
      const timeout = setTimeout(
        () => reject(new Error("console startup timed out")),
        10000
      )
      server.once("error", (error) => {
        clearTimeout(timeout)
        reject(error)
      })
      server.once("exit", () => {
        clearTimeout(timeout)
        reject(new Error(stderr))
      })
      server.stdout.once("data", (data: Buffer) => {
        clearTimeout(timeout)
        const match = /http:\/\/127\.0\.0\.1:\d+/.exec(data.toString())
        if (match) resolveUrl(`${match[0]}/api/`)
        else reject(new Error("unexpected startup output"))
      })
    })
    let expired = false
    const controller = new AbortController()
    const client = httpClient(url, token, {
      signal: controller.signal,
      onUnauthorized() {
        expired = true
      },
    })
    const status = await client.status()
    assert.equal(status.ready, true)
    assert.equal(status.capabilities?.maintenanceTasks, false)
    const records = await client.records()
    assert.equal(records.length, 1)
    const id = records[0]?.id
    assert.ok(id)
    const detail = await client.detail(id)
    const command = {
      id,
      expectedRevision: detail.artifact.header.revision,
      payload: { ...detail.artifact.payload, text: "Edited through HTTP" },
      scope: detail.artifact.header.scope,
      state: detail.artifact.header.state,
      reason: "Test correction",
      confirmed: true as const,
    }
    await client.update(command)
    assert.equal(
      (await client.detail(id)).artifact.payload["text"],
      "Edited through HTTP"
    )
    await assert.rejects(client.update(command), /重新加载/)
    assert.ok(client.console)
    await client.console.graph()
    await client.console.pack("official/big_fish")
    const traces = await client.traces()
    const run = traces.runs[0]
    assert.ok(run)
    const filtered = await client.traces({
      run_id: run.id,
      status: "error",
      state: "recalled_and_injected",
      since: run.updated_at,
      until: run.updated_at,
    })
    assert.deepEqual(filtered, traces)
    assert.deepEqual(
      filtered.events.map((step) => step.event),
      ["agent_begin", "llm_request", "llm_response", "agent_done"]
    )
    assert.ok(!JSON.stringify(filtered).includes("PRIVATE_TRACE_SENTINEL"))
    assert.equal((await client.traces({ status: "completed" })).runs.length, 0)
    await assert.rejects(
      client.traces({ since: "PRIVATE_TRACE_SENTINEL" }),
      /参数无效/
    )
    await assert.rejects(client.task("weekly"), /未启用/)
    await assert.rejects(
      httpClient(url, "invalid", {
        signal: controller.signal,
        onUnauthorized() {
          expired = true
        },
      }).records(),
      /令牌无效/
    )
    assert.equal(expired, true)
    controller.abort()
    await assert.rejects(client.records(), /连接已结束/)
  } finally {
    const exited = new Promise<void>((resolveExit) =>
      server.once("exit", () => resolveExit())
    )
    if (server.exitCode === null && server.signalCode === null) {
      server.kill()
      await exited
    }
    rmSync(data, { recursive: true, force: true })
  }
  assert.ok(!stderr.includes(token))
})
