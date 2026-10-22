# Development Setup

This is the first contribution layer: enough to run tests and the dashboard locally.

## Backend

Use Python 3.10 or newer.

    python3 -m unittest discover -s tests -p 'test_*.py' -q

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

    python3 -m unittest discover -s tests -p 'test_*.py' -q
    cd dashboard && pnpm test

Add a regression test for every behavior change. P0/P1 changes need an issue and a PR record.
