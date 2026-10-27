# Development Setup and Checks

This page describes current local development entry points. Collaboration, branch, worktree, and delivery conventions live in [CONTRIBUTING.md](../../../CONTRIBUTING.md) and [.agents/skills/seekmemory-dev/SKILL.md](../../../.agents/skills/seekmemory-dev/SKILL.md).

## Requirements

- Backend: Python 3.10 or newer.
- Dashboard: Node.js 26 and pnpm 10.
- requirements-dev.txt is for development and contract verification, not a plugin runtime dependency.

Install backend contract-test dependencies from the repository root:

    python3 -m pip install -r requirements-dev.txt

## Documentation site

The documentation site uses Material for MkDocs with dependencies managed separately in requirements-docs.txt. Use Python 3.10 or newer locally; CI builds with Python 3.12.

Install the docs dependencies from the repository root:

    python3 -m pip install -r requirements-docs.txt

Start the local preview (default address: http://127.0.0.1:8000):

    mkdocs serve

Run a strict build:

    mkdocs build --strict

## Backend test layers

The runner uses tests/layers.py to group flat unittest files by responsibility. Choose the needed scope for a change:

    python3 scripts/run_tests.py --layer unit
    python3 scripts/run_tests.py --layer contract
    python3 scripts/run_tests.py --layer integration
    python3 scripts/run_tests.py --layer host
    python3 scripts/run_tests.py --layer smoke
    python3 scripts/run_tests.py --layer all

The compatibility command for all test files is:

    python3 -m unittest discover -s tests -p 'test_*.py' -q

Tests cannot establish real-model extraction quality by themselves. Host behavior also needs an AstrBot environment; model evaluation and capacity probes are separate manual workflows. See [benchmarks/README.md](../../../benchmarks/README.md).

## Dashboard

    cd dashboard
    pnpm install --frozen-lockfile
    pnpm dev

The local preview defaults to 127.0.0.1:5176. Mock data lives only in browser memory, resets on refresh, and does not connect to a real database.

    pnpm check
    pnpm build

check includes generated-type freshness, TypeScript, lint, frontend tests, and formatting checks. build writes the production page to pages/memory/; that build output is not committed. For details, see [dashboard/README.md](../../../dashboard/README.md).

## Changing the management API

1. Update the root openapi.yaml first.
2. Run pnpm generate:api in dashboard and commit generated src/contracts/generated.ts; do not hand-edit generated output.
3. Update the backend routes/service, Zod runtime validation, and contract fixtures together.
4. Run the backend contract layer and dashboard contract validation. Exact commands are in the “Interface contract and type generation” section of dashboard/README.md.

## Changing architecture or documentation

- When data semantics change, update the relevant core, store, perceive, recall, or maintain module page.
- When event flow, service composition, or a host boundary changes, update the overview and related module page.
- Documentation should describe behavior confirmed by current code. Work plans and review history belong in GitHub Issues/PRs, not local RFC or per-work records in docs.
- Chinese and English pages are mirrored under docs/zh and docs/en; site navigation lives in mkdocs.yml, and scripts/check_docs_structure.py validates the page structure.
