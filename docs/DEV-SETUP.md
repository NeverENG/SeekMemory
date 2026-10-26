# Development Setup

This is the first contribution layer: enough to run tests and the dashboard locally.

## Backend

Use Python 3.10 or newer.

Run one layer while developing:

    python3 scripts/run_tests.py --layer unit
    python3 scripts/run_tests.py --layer contract
    python3 scripts/run_tests.py --layer integration

Run every backend test file through the compatibility command:

    python3 -m unittest discover -s tests -p 'test_*.py' -q

See [TESTING.md](TESTING.md) for the layer map and known gaps.

Some contract tests need:

    python3 -m pip install -r requirements-dev.txt

## Dashboard, mock mode

The dashboard can run without AstrBot and without a live database:

    cd dashboard
    pnpm install --frozen-lockfile
    pnpm dev

Open http://127.0.0.1:5176/. Mock actions stay in memory and do not touch production data.

## Dashboard, host mode

Use the AstrBot plugin page for live data. For a local browser against a remote server, see the SSH tunnel instructions in docs/webui/README.md.

## Before opening a PR

Choose local checks by change risk; see [TESTING.md](TESTING.md) for layers and commands. Start with
the narrowest relevant layer, then broaden for cross-layer, privacy, persistence, recovery, contract,
schema/configuration or host-boundary changes. Manually review changed UI and visible copy using
[the repository development skill](../.agents/skills/seekmemory-dev/SKILL.md). CI runs the full required
suite for every PR. P0/P1 changes are tracked in GitHub Issues and PRs; update durable technical docs when behavior or contracts change.


## Read-only live probe

    python3 scripts/snapshot_db.py --source /path/to/memory.db --destination /tmp/staging.db
python3 scripts/live_probe.py --db /path/to/memory.db --label live --json

## Real model extraction probe

    python3 benchmarks/real_eval.py --cases benchmarks/data/extraction_smoke.jsonl --dry-run

Set `SEEKMEMORY_EVAL_BASE_URL`, `SEEKMEMORY_EVAL_API_KEY` and `SEEKMEMORY_EVAL_MODEL` for a real run.
