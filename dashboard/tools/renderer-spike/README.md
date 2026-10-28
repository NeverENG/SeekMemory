# Renderer spike — development only

This standalone Vite page compares `d3-force@3.0.0 + Canvas 2D` with a minimal
WebGL geometry renderer using the **same settled d3 positions**. It is not an
application entry, production dependency or plugin asset. WebGL is a geometry
prototype, not a full graph library; it does not implement picking or touch.

To reproduce, install `d3-force@3.0.0` into an isolated temporary project (disable
install scripts), then copy the four minified UMD files from the installed
`d3-force`, `d3-quadtree`, `d3-dispatch`, and `d3-timer` packages into
`dashboard/node_modules/.tmp/renderer-spike-vendor/`. Each package uses ISC;
keep their notices when copying. Start `pnpm --dir dashboard dev`, open
`/tools/renderer-spike/index.html`, and click **Run 60 samples**.

The warm-up runs 10 frames. Sixty further frames measure CPU command submission
only, at 800×560 / DPR 1. Timings do not include GPU completion, React, data
fetching or pointer-event latency. Browser timing precision can report zero for
WebGL; zero does not mean free rendering. Canvas backing bytes and WebGL vertex
bytes describe different resources and are **not** total process/GPU memory.

## Result and decision (2026-10-26)

See `result-2026-10-26.json` for raw output. On the local Mac / in-app Chromium 156:

| Work                   |  Median |    P95 |     Max |
| ---------------------- | ------: | -----: | ------: |
| d3 force tick          |  2.7 ms | 3.4 ms | 14.5 ms |
| Canvas draw submission |  0.7 ms | 0.8 ms |  1.0 ms |
| WebGL draw submission  | <0.1 ms | 0.1 ms |  0.2 ms |

The four d3 UMD bundles total 17,427 raw / 6,972 separately-gzipped bytes.
Neither d3 nor a WebGL dependency was added to production. These results describe
the historical 2D prototype only. They do not establish the performance of the
current animated, perspective-projected memory sphere.

## Measure the current sphere

Start the dashboard in Mock mode, select the long pressure fixture, then open
Memory and choose 40, 80 or 120 recent memories. The backend loads at most 120
nodes once; display defaults to 80 and switching is local. Keep the tab visible,
let the entrance finish, and
read the canvas `data-*` attributes using browser developer tools:

- `nodes`: displayed nodes.
- `draw-p95`, `draw-ms`: CPU drawing submission, excluding GPU completion.
- `frame-p95`, `frame-ms`: animation callback intervals, not drawing duration.
- `samples`: rolling window of up to 120 paints.
- `bitmap-bytes`: canvas backing allocation only, not total browser/GPU memory.

Record the viewport, theme, browser, node/edge counts and whether the tab is
foregrounded. Reload before comparing scenarios so the rolling samples do not
mix conditions. Inspect input response during layout, keyboard selection via
Find memory, focus/neighbourhood controls, pause, reduced motion and touch on
supported devices. All instrumentation is development-only and removed by Vite.
Verify the production build inside the authenticated host as well.

For the real SQLite graph projection, run:

```sh
python scripts/benchmark_console.py --nodes 10000 --samples 10 --limit 120
```

This creates a disposable synthetic database, reads the latest 120 nodes and
at most 240 edges, and reports duration and Python allocation. It excludes host
HTTP, serialization and browser work. The repository bounds materialization and
batches edge reads, but adds no index; sorting a larger library still needs
measurement. Keep actual measurements and acceptance gaps in the PR. Neither a
fast prototype nor a single passing drawing sample establishes end-to-end FPS
or performance on mobile hardware.
