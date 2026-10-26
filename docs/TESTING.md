# Testing Strategy

Tests are organized by the responsibility they protect, not by file size. The layer map lives in
`tests/layers.py`; the runner is `scripts/run_tests.py`.

## Layers

| Layer | What it protects | Typical tests |
|---|---|---|
| unit | Pure kernel, scoring, storage primitives, policy decisions | artifact, strength, store, gate, capacity |
| contract | Protocols, DTOs, OpenAPI and generated client shapes | public_interfaces, api_contract |
| integration | Several real components wired through a public use case | absorb, recall_pipeline, e2e_kernel |
| host | Real AstrBot lifecycle and plugin page bridge | webui_host |
| import | ChatLab parsing, stable Source admission, retry state and import use case | chatlab, history_import_store, history_import_service |
| webui | Management service and journal behavior | webui, journal |
| smoke | Packaging, import and startup surfaces | smoke, package |
| benchmark | Retrieval quality, scale and ablations | benchmarks/*.py |

`all` runs every `tests/test_*.py` file.

## Commands

```bash
python3 scripts/run_tests.py --layer unit
python3 scripts/run_tests.py --layer contract
python3 scripts/run_tests.py --layer integration
python3 scripts/run_tests.py --layer host
python3 scripts/run_tests.py --layer all
```

The direct compatibility command remains:

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -q
```

The dashboard's API contract workflow also exports real route responses before running
the frontend contract adapter tests:

```bash
python3 tests/test_api_contract.py --export dashboard/node_modules/.tmp/backend-contract.json
pnpm --dir dashboard test:contract
```

## Rules for new tests

1. Use the production entry point when the behavior belongs to a use case.
2. Assert the final observable result, not only an intermediate candidate.
3. Add a negative test for every privacy boundary.
4. Add a recovery test for every write or model failure path.
5. Keep unit tests independent of SQLite files unless persistence is the subject.
6. Do not use the legacy `upsert` path to prepare a scenario that production writes through `commit`.
7. Prefer a small scenario matrix over duplicated copies of the same assertion.

## Coverage tracker

The table tracks covered regressions and known gaps. Rows marked as covered already have a regression test; the others should be added before or with the related fix.

| Gap | Target test |
|---|---|
| Same sentence from two users was deduplicated globally | covered by `tests/test_identity_isolation.py` |
| Similar impressions from two users cross-revised | covered by `tests/test_identity_isolation.py` |
| Shared impression was pinned and bypassed disclosure | covered by `tests/test_privacy_outputs.py` |
| Bad JSON was treated as an empty extraction | covered by `tests/test_failure_recovery.py` |
| Partial commit cleared the whole batch | covered by `tests/test_failure_recovery.py` |
| A batch above the topic limit loses unprocessed turns | covered by `tests/test_failure_recovery.py` |
| Legacy buffer dropped rows above 200 | covered by `tests/test_failure_recovery.py` |
| Corrupt pending JSON silently becomes an empty queue | covered by `tests/test_failure_recovery.py` |
| Pending save failure is silent | covered by `tests/test_failure_recovery.py` |
| Cached candidate was reinforced after budget trimming | covered by `tests/test_reinforcement.py` |
| Request failure recorded a hit | covered by `tests/test_webui_host.py` (host layer) |
| Designated output bypasses disclosure | covered by `tests/test_privacy_outputs.py` |
| Same memory counted twice inside cooldown | covered by `tests/test_reinforcement.py` |
| Source ids collided across sessions | covered by `tests/test_identity_isolation.py` |
| Revision lineage pointed to itself | covered by `tests/test_lineage_consistency.py` |
| Cache removal succeeded after DB commit failure | covered by `tests/test_lineage_consistency.py` |
| Similar scenes from different subjects merged together | covered by `tests/test_identity_isolation.py` |
| Relative date in query was not resolved | covered by `tests/test_temporal.py` |
| Expired/future validity is ignored by recall | covered by `tests/test_temporal.py` |
| Old database migration only checked a column | covered by `tests/test_migration.py` |
| No continuous extraction-to-recall correction case | covered by `tests/test_continuity.py` |
| Explicit plan/fact replacement did not expire the old row | covered by `tests/test_continuity.py` |
| Batch merge left partial state after a member failure | covered by `tests/test_maintain.py` |
| Source evidence recall leaked Source text into the prompt | covered by `tests/test_source_query.py`, `tests/test_recall_pipeline.py` |
| Memory-sufficient recall still queried Source | covered by `tests/test_recall_pipeline.py` |
| Source evidence bypassed revision-scoped `by_source_ids` lookup | covered by `tests/test_source_query.py` |
| Extraction usage was lost on parse failure or not cumulative | covered by `tests/test_absorb.py` |
| Dream call budget kept starting model calls after the cap | covered by `tests/test_absorb.py`, `tests/test_dream.py` |
| Low-value Dream topics started model calls instead of staying pending | covered by `tests/test_importance.py`, `tests/test_absorb.py` |
| Dream triage counted bare dates, work terms or retrieval questions as memories | covered by `tests/test_importance.py` |
| Dream triage ranked the same pending topics twice per flush | covered by `tests/test_absorb.py` |
| Dream triage changed nightly FIFO selection | covered by `tests/test_absorb.py` |
| Dream triage ignored behavior-relevant paired bot replies or scored assistant-only topics | covered by `tests/test_importance.py` |
| Triaged behavior topic failed to reach bot_behavior lineage/self-impression path | covered by `tests/test_absorb.py` |
| Dream batching crossed sessions or split a topic chunk | covered by `tests/test_flush_batches.py` |
| Batched Dream calls bypassed call/token budgets or left inconsistent pending rows | covered by `tests/test_absorb.py` |
| Multi-topic batch evidence omission widened lineage to all batch sources | covered by `tests/test_absorb.py` |
| Multi-topic batch evidence cited Sources from more than one topic | covered by `tests/test_absorb.py` |
| Lifecycle expiry left partial forgotten state | covered by `tests/test_lifecycle.py` |
| Assistant replies were not captured as episodes | covered by `tests/test_webui_host.py` (host layer) |
| AgentRuntime policy was coupled to AstrBot | covered by `tests/test_agent_runtime.py` |
| Runtime session state was process-local only | covered by `tests/test_agent_runtime.py` |
| Runtime timestamps/cooldown/quiet/wait/read-through were untested | covered by `tests/test_agent_runtime.py` |
| AstrBot timestamp and unread mapping were untested | covered by `tests/test_runtime_adapter.py` |
| AstrBot event mapping was untested | covered by `tests/test_runtime_adapter.py` |
| Runtime actions, episodes and tool policy were untested | covered by `tests/test_runtime_actions.py` |
| Observe-only mode could accidentally change LLM gating | covered by `tests/test_webui_host.py` (host layer) |
| Runtime delivery was recorded before actual send | covered by `tests/test_webui_host.py` (host layer) |
| Runtime memory context was coupled to main injection | covered by `tests/test_agent_runtime.py`, `tests/test_seekmemory_context.py` |
| Private/direct attention was suppressed by wait | covered by `tests/test_agent_runtime.py` |
| Cross-session memory was hidden by private scope | covered by `tests/test_scope.py`, `tests/test_recall_pipeline.py` |
| Disclosure was a hard session gate instead of a factor model | covered by `tests/test_recall_feel.py`, `tests/test_kernel.py` |
| Tool guard was advisory in the request path | covered by `tests/test_webui_host.py` (host layer) |
| Scheduler policy was not run over persisted sessions | covered by `tests/test_runtime_actions.py` DB session listing |
| Due ambient wait had no reply dispatch | covered by `tests/test_webui_host.py` (host layer) |
| Deferred dispatch failure duplicated or retried forever | covered by `tests/test_webui_host.py`, `tests/test_agent_runtime.py` |
| Deferred assistant reply was not written back to memory | covered by `tests/test_webui_host.py` (host layer) |
| Deferred lifecycle lived in the AstrBot host entrypoint | covered by `tests/test_agent_runtime.py` and `tests/test_webui_host.py` |
| Runtime DB failures could break replies | covered by `tests/test_runtime_actions.py` |
| Runtime episode retention was unbounded | covered by `tests/test_runtime_actions.py` |
| User impressions were composed into persona | covered by `tests/test_self_impression.py` |
| Persona revision timeline was not exposed | covered by `tests/test_webui_host.py` (host layer) |
| Repeated bot behavior had no self-impression path | covered by `tests/test_self_impression.py` |
| Same reply or a derived impression inflated behavior frequency | covered by `tests/test_self_impression.py` |
| Persona consolidation partially committed or lost stable identity | covered by `tests/test_persona.py` |
| An old persona revision displayed a newer revision's private evidence | covered by `tests/test_webui_host.py` and `dashboard/tests/persona-evidence.test.ts` |
| Windows clock collisions silently lost runtime audit rows | covered by `tests/test_runtime_actions.py` |
| Due wait/retry selection and per-session scheduler isolation were untested | covered by `tests/test_runtime_scheduler.py` |
| Repeated run callbacks duplicated assistant Source, checkpoint or episode rows | covered by `tests/test_run_recorder.py` |

## Staging and model probes

```bash
python3 scripts/snapshot_db.py --source /path/to/memory.db --destination /tmp/staging.db
python3 scripts/live_probe.py --db /path/to/memory.db --label live --json
python3 benchmarks/real_eval.py --cases benchmarks/data/extraction_smoke.jsonl --dry-run
```

`live_probe` is read-only and reports counts, extraction states, persona revision and ledger validity.
`real_eval` uses an OpenAI-compatible endpoint configured through `SEEKMEMORY_EVAL_BASE_URL`,
`SEEKMEMORY_EVAL_API_KEY` and `SEEKMEMORY_EVAL_MODEL`; it is a manual staging probe, not a CI replacement.

## What tests cannot fully prove

- Real model extraction quality is probabilistic. Use schema tests, golden cases, sampling and staging probes.
- Persona emergence over months requires accelerated simulation and live trace review.
- Natural-language leakage cannot be proven by a single unit test. Combine boundary assertions, red-team prompts and
  final-output checks.
- Capacity and latency under real group traffic require staging load tests and production metrics.

## Persona growth model probe (GitHub #15)

`python benchmarks/persona_growth.py --dry-run` checks the frozen 12 synthetic cases
without network access. A real run uses `SEEKMEMORY_EVAL_API_KEY` (environment only),
optional `SEEKMEMORY_EVAL_BASE_URL` / `SEEKMEMORY_EVAL_MODEL`, and requires `--out`.
It calls the model only for background extraction, then uses real commits, deterministic
maintenance and final-context assembly. Each case repeats three times (108 extraction calls).
The gate is >= 90% positive scenarios, all negative scenarios and zero fixture-identifier leaks.
Both compared checkouts use the same API configuration: `deepseek-flash`, non-thinking,
maximum 4096 output tokens. Actual AstrBot provider settings remain owned by the host;
this manual adapter comparison does not establish quality for every configured provider.

Use `--repo /path/to/checkout` to evaluate another revision with the same frozen cases,
and `--baseline-result path.json` for explicit improvements/regressions per case.
Recorded results live in `benchmarks/results/persona_growth*.json`: baseline `9cbfd885`
passed 0/18 positives and 18/18 negatives; the updated extractor passed 18/18 and 18/18,
with zero tested leaks. These are finite synthetic cases, not proof of unrestricted
natural-language accuracy. Earlier failed prompt iterations were used to identify
behavior omission; the evidence thresholds and negative cases were not relaxed.

Host verification uses an installed AstrBot package without starting adapters or production
services. `test_capture_to_extraction_to_weekly_persona_uses_real_pairs` covers the actual
capture, Source-backed queue, flush, weekly maintenance and final prompt, and checks that
capture/recall/maintenance add no model call beyond the background extractor.

## CI policy

CI runs the same file-level tests as the local compatibility command. Host-only tests may skip when the AstrBot
host is unavailable; that is not evidence that host behavior works. Record the host run separately in the PR.
