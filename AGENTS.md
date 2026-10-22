# AGENTS.md

Operating rules for AI agents and external contributors working on SeekMemory.

This file is normative. If it conflicts with a casual instruction, stop and ask the Lead.

## 1. Read first

- `docs/ARCHITECTURE.md`
- `docs/DESIGN.md`
- `docs/CONTRACT.md`
- `CONTRIBUTING.md`
- `docs/INTERFACES.md`
- `docs/DEV-SETUP.md`
- `docs/BUGS.md`
- `docs/issues/INDEX.md`

## 2. Non-negotiable invariants

1. **Source is the only immutable truth.** User and assistant messages are Source rows.
2. **Artifact is a derived, revisable interpretation.** It is never the raw truth.
3. **Every production write goes through `DB.commit()`** with expected revision, version snapshot,
   evidence links and ledger entry. Do not add new `DB.upsert()` call sites.
4. **SQL lives only in `store/db.py`.** No SQL in core, app, recall, perceive, maintain or main.
5. **Dependency direction:** adapters -> app -> core. `core/` imports no storage, SDK, plugin or app code.
6. **External calls use ports.** LLM calls go through `ChatModel`; AstrBot, SQLite and files stay at edges.
7. **Recall has no hidden writes.** Delivery, reinforcement and checkpoint are explicit write use cases.
8. **Privacy before expression.** Never inject raw cross-session text when disclosure says paraphrase,
   hint or silence. Never log message bodies, secrets or credentials.
9. **No silent data loss.** A failed model call must restore pending rows; failed writes must not
   mutate cache or ledger.
10. **No direct production changes without Lead approval.** Never SSH to the live server, rotate keys,
    restart containers or change tags unless the Lead explicitly authorizes that action.

## 3. Repository map

- `core/`: pure Artifact kernel, Source, Strength, versioning, disclosure and retrieval values.
- `app/`: use cases, DTOs, ports, flush policy, checkpoint orchestration.
- `store/`: SQLite repository, cache/read model, ledger.
- `perceive/`: extraction prompt, model adapter, buffer.
- `recall/`: retrieval policies, candidate generation, scoring, assembly.
- `maintain/`: decay, merge, persona, reflection.
- `main.py`: AstrBot event mapping and composition only.

## 4. Workflow

1. Read the relevant issue and existing tests before editing.
2. Create or update an issue for P0/P1 work.
3. Branch from `main` using `fix/issue-XXXX-*`, `feat/issue-XXXX-*` or `docs/...`.
4. Make the smallest coherent change. Do not mix refactor and behavior change.
5. Add tests that fail before the change and pass after it.
6. Write `docs/issues/PR-XXXX.md` with scope, verification and risk.
7. Merge with `--no-ff` only after tests pass and the Lead reviews.
8. Never force-push `main`; never rewrite a released tag.

## 5. Testing

Run before every commit:

    python3 -m unittest discover -s tests -p test_*.py -q

For recall or scoring changes also run the relevant benchmark and attach before/after numbers.
For AstrBot boundary changes, verify the plugin imports inside the real AstrBot container or a
faithful staging copy. Record commands and results in the PR file.

## 6. Coding standards

- Python 3.10+; type hints on public functions; Chinese docstrings are welcome.
- Prefer frozen dataclasses and small pure functions.
- Use DialogueTurn, RetrievalCandidate, WriteOutcome and other DTOs; do not add new raw tuples.
- Keep files near 150 lines and under 300 where practical.
- Fail open at external boundaries; fail loudly in core invariants.
- Do not duplicate scoring or privacy rules. Put shared policy in core/ or app/.
- Do not add an Artifact field without an issue and an explicit Lead decision.
- Do not hold a DB transaction open while calling an LLM or network service.
- Do not add a dependency when the standard library is sufficient; justify new dependencies in the PR.
- Do not add new dual-import fallbacks unless the module must run in both package and test contexts.

## 7. Privacy and data rules

- Source rows are append-only. Never update or delete them in normal operation.
- Every extracted Artifact should link its Source evidence when available.
- Legacy rows without Source evidence must be marked low-confidence, never given fake evidence.
- Never log Source text, message content, secrets, API keys or user identifiers in debug output.
- Cross-session recall must pass through disclosure before assembly.
- Shadow and secret content must never enter a normal injection block.
- If a privacy rule is ambiguous, choose the safer mode and escalate to the Lead.

## 8. Deployment

Production is a remote AstrBot instance managed by the Lead. Agents must not deploy directly.
Release steps are Lead-only:

1. tests pass locally and in staging;
2. backup plugin and data;
3. bump version and changelog;
4. merge to main and push tag;
5. deploy the tag and verify plugin load;
6. inspect sources, nodes, versions, evidence and logs.

## 9. Definition of done

- [ ] Issue and PR docs exist for P0/P1 work.
- [ ] No production DB.upsert call sites added.
- [ ] Source evidence is preserved.
- [ ] Tests pass, including new regression cases.
- [ ] Recall changes include benchmark or live probe results.
- [ ] No secrets or message bodies in logs.
- [ ] Rollback path documented.
- [ ] Lead reviewed the change.

## 10. Agent behavior

- State assumptions explicitly when requirements are ambiguous.
- Do not silently change public config keys or schema.
- Do not claim completion without test or live evidence.
- When blocked by credentials or missing context, stop and report exactly what is needed.
- Keep the Lead informed with concise status: what changed, what was verified, what remains.
