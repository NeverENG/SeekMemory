---
name: seekmemory-dev
description: Apply SeekMemory repository conventions when inspecting or changing its code, tests, dashboard, documentation, configuration, or Git workflow.
---

# SeekMemory development

This is the repository's single operating guide; there is no root `AGENTS.md`. Technical behavior and public contracts belong in the relevant `docs/` files. This skill owns agent/contributor workflow and project-specific implementation conventions.

## Workflow

1. Before writing, inspect `git status --short --branch` and `git worktree list`. Work only in the current task's worktree, on a non-`main` branch. Search repository files only inside that worktree. Read the relevant GitHub issue if one exists, plus implementation, tests and current technical documents; use the [documentation entry](../../../docs/zh/index.md) to find the owning module.
2. State the caller-visible behavior or repository outcome, identify its existing owner and boundary, then make the smallest coherent change. Keep behavior changes separate from unrelated refactors.
3. For behavior changes, describe scenarios before writing tests or implementation. Test caller-observable behavior and fake external systems at their boundaries.
4. Choose local validation by risk and necessity. Record exact commands, results and skipped checks. CI runs the full required suite for every PR; risk-based local checks do not replace CI.
5. If persisted data, schema or public configuration may be affected, stop before implementation. Explain the current format, impact and viable compatibility, migration or breaking/reset options; wait for the Lead to choose.
6. Keep contracts and user-facing records aligned: update the appropriate technical docs, add equivalent Simplified Chinese and English changelog notes when applicable, and record risks and rollback for P0/P1 work.
7. Report what changed, what was verified, compatibility impact and the current branch/worktree state. Never claim evidence that was not collected.

## Repository invariants

- Source rows are the only immutable truth and are append-only. Artifact is a derived, versioned interpretation, never raw truth. Preserve available Source evidence; legacy rows without evidence stay low-confidence and never gain fabricated links.
- Every production Artifact write uses `ArtifactStore.commit()` with expected revision, version snapshot, evidence links and ledger entry. `ArtifactRepository.upsert()` is seed/benchmark-only. Do not add Artifact fields without an issue and an explicit Lead decision.
- SQL lives only in `store/`; repositories own their SQL and `store/__init__.py` is composition only. Follow the dependency direction in the [architecture overview](../../../docs/zh/architecture/overview.md); `core/` stays free of storage, SDK, plugin and application imports.
- External systems stay behind ports. LLM calls go through `ChatModel`; AstrBot, SQLite and filesystem access stay at the edges. Do not duplicate shared privacy or scoring policy.
- Recall has no hidden writes. Delivery, reinforcement and checkpoint are explicit write use cases. Never hold a SQLite transaction open during a model or network call.
- Privacy precedes expression. Cross-session content goes through disclosure before assembly; paraphrase, hint or silence rules must not be bypassed by UI state or pinned memories. Shadow text and secret-family content must never be injected verbatim. Logs must not contain message bodies, prompts/responses, secrets, credentials or user/session identifiers.
- Failed model calls leave pending input recoverable. Failed writes must not mutate cache or ledger. Source evidence, disclosure and recovery boundaries are described in the [architecture overview](../../../docs/zh/architecture/overview.md) and its linked module pages.
- Production data changes, deployment and release operations require explicit Lead authorization. Release execution is Lead-only.

## Implementation conventions

- Python targets 3.10+. Add type hints to public functions; prefer frozen dataclasses and small pure functions.
- Reuse named DTOs such as `DialogueTurn`, `RetrievalCandidate` and `WriteOutcome`; do not introduce raw tuples where a named type belongs.
- Keep modules focused (about 150 lines where practical; avoid exceeding 300 without a reason). Prefer the standard library; justify new dependencies. Do not add package/top-level import fallbacks unless both execution modes are required.
- At external boundaries, fail open when needed to preserve host operation; fail loudly when a core invariant is violated.
- Consult the [documentation entry](../../../docs/zh/index.md), [architecture overview](../../../docs/zh/architecture/overview.md), and the owning module page before changing module boundaries or public shapes. Update the module page and API schema/contracts when public behavior changes.

## Focused references

Read only the reference needed for the current work:

- Before branch/worktree, issue, PR, commit, merge or release actions: [collaboration and repository workflow](reference/collaboration.md).
- When changing behavior or selecting checks: [test design and risk-based verification](reference/testing.md).
- When changing the dashboard or visible copy: [UI and copy quality](reference/ui-quality.md).
- When changing persisted data/public configuration or writing release notes: [changelog and compatibility decisions](reference/changelog-compatibility.md).

Use the bilingual architecture pages under `docs/zh/` and `docs/en/` as the current technical documentation. Do not preserve issue, pull request, bug-tracker or RFC notes as documentation contracts.
