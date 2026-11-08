# EVENT-CONTRACT.md · Inbound event boundary

> Current implementation: `HostRequest` and `HostGateway` in `adapters/host_gateway/`;
> `RuntimeInput` in `app/runtime/contracts/` is the decision view (#222).

## Decision

Host adapters extract SDK- or wire-specific facts; HostGateway alone constructs the
`RuntimeInput` view. `HostRequest` is transient and already reduced: neither a persisted
record nor a lossless host event. No `HostEvent` / `ContentPart` / `EventCodec` stack.

```text
AstrBot SDK event ──astrbot.events extraction──▶ HostRequest ─┐
DSH event ──Node mapping, existing HTTP input──▶ HostRequest ─┴─▶ HostGateway ─▶ RuntimeInput ─▶ AgentRuntime
```

DSH still extracts platform fields in Node; the real `scripts/serve.py` loopback uses
`adapters/loopback/runtime_ingress.py` to project the existing `input` via HostGateway
before passing it to AgentRuntime. AstrBot's compatibility
`to_runtime_input` entry is unchanged. `session_id` retains its
current session identity; `event_id` supports correlation/existing deduplication, not
authentication. For now the gateway trusts host-provided facts; it owns no authentication,
rate limits, concurrent filtering, favorability or disclosure. AgentRuntime schedules;
disclosure and action checks remain at their existing boundaries.

`RuntimeInput` retains its existing optional context fields and session semantics:

| Field | Purpose |
|---|---|
| `scene` | private / group / channel / thread / **comment** |
| `conversation_id` | group / channel / thread identifier |
| `thread_id` | comment nesting (threads in comments); empty means none |
| `self_id` | the bot's own identifier |
| `role` | owner / admin / member / bot / system |
| `addressed` | called by name or wake prefix |
| `reply_to_me` | quoting or replying to the bot |
| `event_id` | host message correlation and existing deduplication key |
| `kind` | message / edit / recall / reaction (reserved; only message handled today) |

## Why

1. Two hosts only (AstrBot, DSH): a lossless event layer costs more than it saves.
2. Rich content is normalized by the Source layer; decision logic does not need `ContentPart`.
3. Policies need **signals**, not events: relationship / relevance / heat / time window are
   generic `RuntimeInput` fields and optional host-supplied signals; policies should not depend on platform names.
4. One owner for inbound projection: transient facts cross this boundary without
   copying raw events, Sources or domain policy.

## Sending capability and proactive topics

- **No `reply_capable` field**: the runtime decides "should we speak"; whether the platform
  allows it (limits, rate limits, comment permissions) is the send port's job. Failure is
  surfaced by the port and recorded by the runtime (fail-open).
- **Proactive topics come from memory + a scheduled window** only: `TopicSource` only
  proposes candidates from memory (unfinished scenes, impression changes, relation gaps);
  whether it is due is decided by `ProactivePolicy` (#117), never random.

## Evolution triggers (revisit lossless HostEvent if any happens)

1. Non-message events must drive decisions (edit, recall, reaction, join/leave, presence).
2. A third platform whose fields `RuntimeInput` cannot express (threads/comments, anonymous identity).
3. Multimodal input (transcripts, image content) must participate in attention decisions
   directly, instead of being normalized in the Source layer.
4. One host has multiple event sources to merge (e.g. group message plus private forward).

If a lossless event is needed later, assess its contract and migration separately;
`HostRequest` is not the source of truth for raw events.

## Multi-platform targets

Confirmed targets: Telegram, WeChat, Douyin, Bilibili (plus the existing AstrBot/QQ and DSH
hosts). Their differences are mainly **conversation shape** (channel/comment/private) and
**sending capability** (voice/quote/recall), expressed by `scene`/`conversation_id` and the
send port respectively — no lossless event structure needed.
