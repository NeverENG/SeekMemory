# DSH Platform Adapter Contract

Platform plugins own their session/event objects and platform APIs.
SeekMemory owns the canonical RuntimeInput and action contract.

## Adapter interface

```js
createPlatformAdapter({
  platform: 'qq',
  capabilities: { private: true, mention: true, replyTo: true, forward: false },
  toRuntimeInput(session, event, options) { ... },
  executeAction(request) { ... },
})
```

## Host bridge

```js
const bridge = createHostBridge({ kernel, adapter, logger })
bridge.acceptUser(session, event)
bridge.context(session, request, event)
bridge.recordReply(session, event, data)
bridge.recordDelivery(session, event, data)
bridge.recordError(session, event, data)
bridge.executeAction(request)
```

## Rules

- DSH Session/Event stay opaque to SeekMemory.
- Platform plugins do not implement attention, proactive, memory, or action-terminal policy.
- HostBridge does not register DSH hooks; platform plugins own hook registration and disposal.
- ActionRequest text is transient execution input and never enters ActionRecord audit.
- `session_id` is the conversation lane; `subject_key` is the shared memory identity.
- Contract versions: `platform_contract=1`, `runtime_contract=1`.

See issue #150 and `test/platform-contract.mjs` / `test/host-bridge.mjs`.

## 中文摘要

平台插件只实现 `toRuntimeInput` 和 `executeAction`；`host-bridge` 负责 Runtime HTTP 调用、记忆上下文和稳定错误映射，不注册 DSH hook。`session_id` 是会话 lane，`subject_key` 是共享记忆主体。

## Subject identity: kernel `owner_umo` MUST equal adapter `subjectKey`

One kernel data directory owns exactly one logical subject. `adapters/loopback/runtime.py`
(`_same_subject()`) accepts only an empty `subject_key` or one **strictly equal** to the
kernel's `owner_umo`; every other value is rejected with
`403 {"error": "subject_mismatch"}` on `/capture`, `/recall`, `/persona` and `/extract/plan`.

Hosts therefore must set:

```yaml
- id: dsh-seekmemory
  config:
    subjectMode: fixed
    subjectKey: <the same string as the kernel --config owner_umo>
```

and start the kernel with a matching config, e.g. `{"owner_umo": "napcat:FriendMessage:100000000"}`.

**False-pass warning:** the kernel reads the field named `subject_key`. Sending a different
field (for example `umo`) is silently ignored, the request falls back to `owner_umo`, and the
call still returns **200**. Never conclude "identity is aligned" from a bare 200 — use a
deliberately wrong key and confirm it returns 403.

**`subjectMode: auto` has no stable field in real DSH sessions.** The candidate chain
(`session.subjectKey / umo / ownerUmo / meta.*`) is empty in practice, so the adapter degrades
to `local:single:default` and every call 403s against a kernel whose `owner_umo` is anything
else. Use `fixed` + explicit key.

## Capture hygiene: host-injected messages are not user input

DSH delivers injected context as ordinary `user/message` session events. The origin is on
`event.data.source.kind`:

| `source.kind` | meaning |
|---|---|
| `user` | real user input — capture this |
| `plugin:seekmemory` | the recall block this adapter injected |
| `runtime-context` | runtime snapshot (includes the `seekmemory:persona` prompt section) |
| `skill-catalog` | `<system-reminder>` skill catalog |

Adapters must skip everything except `user`, otherwise recall blocks re-enter memory as if the
user had said them and get recalled again — a self-reinforcing loop:

```js
const origin = data.source?.kind;
if (role === 'user' && origin && origin !== 'user') return;
```

Measured effect on a real turn: 4 rows captured per turn before the filter, 1 after.

## Runtime file: the token changes on every kernel start

`runtime.json` is rewritten on start and carries a freshly generated bearer token. The client
caches the parsed file for `CACHE_MS = 1000` (`src/kernel-client.js:15`) and re-reads it after
expiry (`:87`), so a rotated token recovers on the next request past the cache window — a host
restart is **not** strictly required. Starting the kernel before the host is still the sane
order: a host started first has nothing to read, and any request inside the 1 s window after a
rotation sees 401.

## Persona injection ownership

Persona currently reaches the model twice: once from the adapter's
`systemPrompt.context({ name: 'seekmemory:persona' })` block, and once because the kernel pins
the persona node into the `/recall` block (`info.pinned_ids`). Agree on a single owner before
adding another injection site.

