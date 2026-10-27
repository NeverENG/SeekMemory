# EVENT-CONTRACT.md · Event layering decision

> Status: **decided (v0.4.2)**. This page records why no HostEvent layer is introduced
> yet, and what would trigger a revisit. Authoritative implementation:
> `RuntimeInput` in `app/runtime/contracts.py`.

## Decision

Host events (AstrBot / DSH / future platforms) are mapped **directly to `RuntimeInput`**
by the adapter layer. No intermediate `HostEvent` / `ContentPart` / `EventCodec` layers.

```text
host event ──adapter mapping──▶ RuntimeInput ──▶ AttentionPolicy / ProactivePolicy
```

`RuntimeInput` was extended in v0.4.2 **backwards compatibly** (every field has a default):

| Field | Purpose |
|---|---|
| `scene` | private / group / channel / thread / **comment** |
| `conversation_id` | group / channel / thread identifier |
| `thread_id` | comment nesting (threads in comments); empty means none |
| `self_id` | the bot's own identifier |
| `role` | owner / admin / member / bot / system |
| `addressed` | called by name or wake prefix |
| `reply_to_me` | quoting or replying to the bot |
| `event_id` | host idempotency key |
| `kind` | message / edit / recall / reaction (reserved; only message handled today) |

## Why

1. Two hosts only (AstrBot, DSH): a lossless event layer costs more than it saves.
2. Rich content is normalized by the Source layer; decision logic does not need `ContentPart`.
3. Policies need **signals**, not events: relationship / relevance / heat / time window are
   expressed by `app/runtime/signals.py` and reused by attention, proactive and recall.
4. Parallel development boundary: #114/#116/#117 are changing `contracts.py` and adapters;
   adding another layer widens the conflict surface.

## Sending capability and proactive topics

- **No `reply_capable` field**: the runtime decides "should we speak"; whether the platform
  allows it (limits, rate limits, comment permissions) is the send port's job. Failure is
  surfaced by the port and recorded by the runtime (fail-open).
- **Proactive topics come from memory + a scheduled window** only: `TopicSource` only
  proposes candidates from memory (unfinished scenes, impression changes, relation gaps);
  whether it is due is decided by `ProactivePolicy` (#117), never random.

## Evolution triggers (introduce HostEvent when any happens)

1. Non-message events must drive decisions (edit, recall, reaction, join/leave, presence).
2. A third platform whose fields `RuntimeInput` cannot express (threads/comments, anonymous identity).
3. Multimodal input (transcripts, image content) must participate in attention decisions
   directly, instead of being normalized in the Source layer.
4. One host has multiple event sources to merge (e.g. group message plus private forward).

Migration when introduced: `HostEvent` becomes the host truth,
`HostEvent.project() -> RuntimeInput` keeps policy code unchanged; `RuntimeInput` becomes
a decision view.

## Multi-platform targets

Confirmed targets: Telegram, WeChat, Douyin, Bilibili (plus the existing AstrBot/QQ and DSH
hosts). Their differences are mainly **conversation shape** (channel/comment/private) and
**sending capability** (voice/quote/recall), expressed by `scene`/`conversation_id` and the
send port respectively — no new event structure needed.
