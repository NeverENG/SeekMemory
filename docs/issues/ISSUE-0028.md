# Capacity governance: Source-backed pending projection and governor

| item | value |
|---|---|
| id | ISSUE-0028 |
| level | P2 |
| status | in-progress |
| reporter | Traveler712 |
| date | 2026-10-22 |
| related PR | PR-0028 |
| affected version | `main` @ `32cfd57` |
| GitHub | #12 |

## Problem

The production shape reported in GitHub #12 contains 1022 Sources, 50 nodes and
200 pending turns. The JSON pending buffer keeps a second copy of dialogue text
and silently truncates the oldest row at `KEEP=200`.

The immutable Source is not lost, but the extraction queue has no durable state
of its own. A full queue cannot be reconstructed reliably, and capacity pressure
is handled by one irregular flush policy rather than explicit lifecycle actions.

## Expected behavior

- Pending is a projection over immutable Source and `extraction_state`.
- Rebuilding or restarting does not truncate the queue at 200 rows.
- Source rows are never deleted by capacity governance.
- A pure governor maps a capacity snapshot to a state and a bounded action set.
- Scheduler and maintenance code consume those actions without reading dialogue
  bodies for metrics.

## Scope

Included:

- `extraction_state` schema and legacy `pending.json` migration.
- Source + extraction-state atomic enqueue.
- Pure `core/capacity.py` policy with four states and eight actions.
- Scheduler integration for extraction batches and maintenance.
- Expiry cleanup, Trace trimming and degraded recall under pressure.

Excluded:

- Network or model-provider changes.
- QQ history import.
- Source deletion or replacement.
- A distributed multi-writer queue.

## Acceptance

- [x] Four states and all eight actions are covered by unit tests.
- [x] Pending projection rebuilds from Source and never truncates at 200 rows.
- [x] Legacy pending migration leaves a recoverable `.migrated` file.
- [x] Governor transitions emit bounded lifecycle events without message text.
- [x] Full unit suite passes.

## Decision record

- 2026-10-22: implement GitHub #12 on `feat/issue-12-capacity-governance`.
