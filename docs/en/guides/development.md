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

    python3 scripts/check_docs_structure.py
    mkdocs build --strict

The structure check validates navigation, mirrored page sets and relative Markdown file links; the strict build checks whether the site can be generated with its current configuration. Neither automatically verifies that prose matches code. If the `material` theme is missing, install the docs dependencies above; missing dependencies do not constitute a successful build.

## Backend test layers

The runner uses tests/layers.py to classify flat unittest files; explicit `_unit.py`, `_integration.py` and other layer suffixes override legacy names. Each file runs through unittest discovery in an isolated process, including definitions after `__main__`, so host fakes do not leak between files. All files run and any failure makes the command fail. Legacy files can still span modules; layer names do not guarantee fully isolated dependencies. Choose the needed scope for a change:

    python3 scripts/run_tests.py --layer unit
    python3 scripts/run_tests.py --layer contract
    python3 scripts/run_tests.py --layer conformance
    python3 scripts/run_tests.py --layer integration
    python3 scripts/run_tests.py --layer host
    python3 scripts/run_tests.py --layer smoke
    python3 scripts/run_tests.py --layer all

All files can also be discovered in one process; host fakes may affect optional host tests in that process, so use the isolated runner above for host acceptance:

    python3 -m unittest discover -s tests -p 'test_*.py' -q

For capability-specific core checks, see [core verification entry points and evidence limits](../architecture/modules/core.md#core-verification): it lists current tests and focused commands, distinguishing pure rules from complete flows. Export checks do not establish complete behavioral coverage of all exported operations.

Tests cannot establish real-model extraction quality by themselves. Host behavior also needs an AstrBot environment. Benchmarks measure different things from tests: fixed memory regression uses one evaluator and a frozen baseline to reject per-query regressions with nonzero status; the historical composite is not a gate, and BM25 has separate frozen acceptance checks. Character counts are not tokens or cost. Definitions and limits are in [benchmarks/README.md](../../../benchmarks/README.md).

## Offline scripts and artifacts

`scripts/snapshot_db.py` creates a consistent backup including WAL, closes connections before atomic publication and preserves the old backup on failure; the source cannot be the destination. Persona bootstrap, pending migration and relationship rollback scripts close their own stores. The runtime-service creator closes its listener even if endpoint metadata cannot be saved.

Ordinary memory, scale and ablation reports use new ignored run directories without replacing history. Release packaging produces a local artifact and does not authorize release or deployment.

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

## Persona console preview and packs

The Mock console uses hash routes such as #/home, #/studio, #/memory,
#/store, #/dream and #/system?section=traces. The preview selector includes
loading, empty, error and a 1,000-node/2,000-edge stress fixture. Preview
install/import/edit actions affect memory-only fixtures. dev:host and production
builds require the authenticated AstrBot page bridge.

Bundled persona files live at persona_seeds/&lt;id&gt;/persona.json. Add the ID to
index.json, include a LICENSE and follow the [persona seed guide](persona-seed.md).
Local imports go under the plugin data directory's persona_packs/. Removal moves
a pack to .trash and leaves the active persona unchanged. Recover a removed
blueprint by importing its backup JSON after checking the ID and version.
To replace a same-ID file, supply its current version during import confirmation.
Updating a blueprint never installs it automatically.
