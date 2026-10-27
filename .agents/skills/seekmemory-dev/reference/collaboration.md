# Repository collaboration

In this guide, **Lead** means the human owner who makes repository-scope, compatibility and production decisions.

## Repository roles

This is the implementation repository: production code, executable tests, API contracts and release packaging live here. SeekMemory has no paired design repository, so this skill is the primary source of agent/contributor operating conventions. If a design repository is added, keep design-system/specification ownership there, keep implementation and executable contract checks here, and link the authoritative design revision instead of copying it.

The canonical skill is `.agents/skills/seekmemory-dev/`. `.claude/skills/seekmemory-dev` points through it for Claude Code discovery. Edit the canonical files only.

## Branches and worktrees

- All writes happen on a non-`main` branch. Read-only inspection may use any branch; never commit directly to `main`.
- For a small task in a clean checkout, create a task branch in that checkout. If it contains unrelated changes, preserve them and use a sibling worktree.
- Use a dedicated sibling worktree for multi-step, cross-module or long-running work, or when another task owns the current checkout. Put it under `../SeekMemory-worktrees/<task>/` and give it one task branch.
- Reuse the current task's worktree when continuing that task. Keep one task per worktree. Do not stash, reset, overwrite, copy or switch away from unrelated work.
- Branch from `main` unless continuing an existing branch. Use `fix/issue-XXXX-*`, `feat/issue-XXXX-*`, or a descriptive `docs/`, `test/`, `bench/`, `ci/` or `refactor/` name.
- Search repository content only inside the current worktree. Do not search sibling worktrees or unrelated checkouts unless comparison is explicitly part of the task.
- Keep worktrees with uncommitted changes or unmerged branches. Remove them only when clean and no longer needed. Do not merge without Lead review; merge reviewed work with `--no-ff`. Never force-push `main` or rewrite a released tag.

## GitHub issues, PRs and commits

- P0 covers data/privacy damage or outage; P1 covers broken behavior or material regression; P2 covers ordinary work. P0 may branch immediately to contain damage, then needs a GitHub issue within 24 hours. P1 needs a GitHub issue before implementation. Use a GitHub PR for review and verification evidence. When uncertain, use the higher severity.
- GitHub Issues and PRs are the canonical work history. Do not create local issue/PR copies, numbering schemes or indexes. Keep durable contracts, architecture decisions and operational guidance in `docs/`; link to the GitHub issue or PR only when traceability is useful.
- Create the GitHub issue before its PR when both are needed. Keep scope, verification, compatibility, risk and review evidence in the GitHub issue/PR itself; do not create empty issues just to reserve a number.
- Keep one task per branch and one coherent change per commit. Use `type(scope): 中文摘要` with `feat`, `fix`, `docs`, `test`, `bench`, `refactor` or `ci`; start with an action, stay under 50 Chinese characters and omit the final period. Explain why and impact in the commit body.
- To reverse a merged change, use `git revert`; do not rewrite pushed `main` history.

## Production and releases

Agents must not make production changes, SSH to the live server, rotate keys, restart containers, change production tags, deploy or release without explicit Lead authorization. Release packaging details remain in [CONTRIBUTING.md](../../../../CONTRIBUTING.md#release-packaging).
