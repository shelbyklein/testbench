# OB2-12 — browser verification record

Lane: Opus UI (`ob2/ui`). Todo: **OB2-12** — graph, timeline and comparison dashboard.

**All evidence here is synthetic.** The pages were driven against a demo experiment built by
`tests/ui/demo.py`: invented method labels and model names, operator metrics typed by hand, and
traces imported from the observation lane's synthetic JSONL fixtures. The experiment carries
`"synthetic": true` and the dashboard shows a persistent SYNTHETIC banner throughout. No provider
was called, no network beyond `127.0.0.1` was used, and nothing was installed.

## Environment

| Item | Value |
|---|---|
| Date | 2026-09-20 |
| Platform | macOS (darwin 25.1.0), Apple silicon |
| Python | 3.x standard library only |
| Node | v24.18.0 (`node --version`) |
| Playwright | 1.63.0, loaded from `/Users/shelbyklein/Vibes/Newton/node_modules/playwright` (never installed by this lane) |
| Browser | installed Google Chrome via `chromium.launch({ channel: 'chrome', headless: true })` → Chrome/153 headless |
| Servers | `bench.make_server(exp, 0)` and `bench_core.review_server.make_server(exp, 0)`, both on ephemeral 127.0.0.1 ports, started and stopped by the test |

## Commands

```
cd orchestration-bench-v2
python3 -m unittest discover -s tests/ui -t . -p 'test_*.py'          # 16 tests, OK
python3 -m unittest discover -s tests/core -t . -p 'test_*.py'        # 69 tests, OK
python3 -m unittest discover -s tests/observation -t . -p 'test_*.py' # 68 tests, OK
python3 -m unittest discover -s tests/review -t . -p 'test_*.py'      # 46 tests, OK
python3 -m unittest discover -s tests/integration -t . -p 'test_*.py' #  8 tests, OK
```

The browser checks are `tests/ui/browser_checks.mjs`, launched by `tests/ui/test_browser.py`.
That wrapper **skips** (it never passes silently) when Node 22+, the Playwright checkout or
Chrome is missing, and says which one. To build a demo experiment for manual inspection:

```
python3 -m tests.ui.demo /tmp/ui-demo
python3 bench.py --experiment /tmp/ui-demo/experiment serve
python3 bench.py --experiment /tmp/ui-demo/experiment serve-review
```

## Result

**118 checks, 0 failures** — 59 distinct checks run at both viewports
(desktop 1440×1100 light, mobile 390×844 dark). The machine-readable record is
`browser-checks.json` in this directory.

What was verified, grouped:

* **Node attempts, failed and missing evidence** — the declared and observed graphs list each
  node with its role, attempts (`worker-a` shows `attempts: 1, 2`) and join status; `worker-c`
  is shown as FAILED, `worker-d` as MISSING — never observed, and never rendered as a quiet
  success; `reviewer` is shown as skipped. Declared-only / observed-only / edge differences are
  called out separately from the join.
* **Resource provenance** — `measured` and `estimated` badges render differently (solid vs
  dashed border) and both carry their source in a `title`, in a focus/hover tooltip and in
  visually-hidden text (`provenance: estimated; Source: operator estimate from token counts`).
* **Unknowns** — an unavailable cost renders as the token `unknown` and never as `0`;
  a partially known aggregate renders `partial (1 unknown)`; a run without a trace says so
  explicitly rather than showing zeros.
* **Synthetic data** — persistent banner, `SYNTHETIC TRACE` badge in the trace view, and a
  `SYNTHETIC DATA` pill in the comparison.
* **Comparison** — no winner (`winner: null · policy: not computed · composite score: null`),
  quality and resources side by side, human interventions and human minutes in their own table,
  per-role breakdown, reconciliation counts, incomplete-trace list (`run-zz0004`), paired
  wins/losses/ties, raw per-run rows, and task-level vs repeat-level variation kept apart.
* **Blind review** — labels only, file browser and viewer, automated check id/description/status,
  rubric + manual checks + defects from `reviewTemplate`, residual-cues notice. A 409 shows
  "This package is out of date … Reload this package" and does not report the review as saved.
* **Isolation** — every request the review page made went to its own server; no operator route
  was requested; no response body contained any of the demo's distinctive identity strings
  (`Zebra-Method-Q7`, `ModelXYZ-9`, `zebramode`, `run-zz0001`, …).
* **Keyboard and focus** — Tab reaches the tablist, arrow keys move and activate the three
  views and wrap around, Enter opens a trace disclosure and activates a run's Inspect button,
  and a blind review is submitted with Enter on a keyboard-reached submit button. The focus ring
  is a 3px outline on both the tab and the submit button in both themes.
* **Layout** — `document.documentElement.scrollWidth <= window.innerWidth` on the dashboard,
  trace view, comparison, review list and review detail, at both widths.
* **Console** — no console error and no script error on either page. Two exclusions are
  deliberate and documented in the script: the browser's own `/favicon.ico` 404, and the 409
  the stale-package check provokes on purpose (the review page's console is asserted clean
  *before* that step, and script errors are asserted for the whole session).

## Screenshots, and what inspecting them found

Each PNG below was opened and read after capture.

| File | What I looked at, and what I found |
|---|---|
| `dashboard-overview-desktop.png` | Header, readiness, integrity, run groups. Readiness lists the single real blocker in plain words; the unstarted run shows `unknown` checks and a `no trace` pill rather than zeros; `Review is stale` is visible in the run list. **Fixed after looking:** the detail heading read "Run run-zz0003 · …"; the redundant "Run " prefix was removed. |
| `dashboard-overview-mobile.png` | Dark theme at 390px. Banner wraps to three lines, controls stack full width, the run table becomes stacked cards with their column names above each value, no horizontal scroll. The run picker truncates long option text inside the native select — acceptable, the same run is named in full in the detail heading below. |
| `trace-view-desktop.png` | The "Missing or failed work in this run" block sits above the graphs and names `worker-d` (MISSING), `worker-c` (FAILED) and `reviewer` (skipped). Declared and observed columns line up side by side, and `worker-a` shows `attempts: 1, 2` only in the observed column, which is the point. Focus ring on the active tab is clearly visible. No defects found. |
| `trace-view-mobile.png` | Same content stacked; the tab list wraps to two rows and the selected tab keeps its ring and its accent bar. Long node IDs stay inside their cards. No clipping or overlap. |
| `comparison-desktop.png` | Quality and resources side by side, "No overall winner is computed" stated first. **Fixed after looking:** (a) a fully unknown aggregate read "unknown 1 unknown", which was noise — it now reads `unknown` once and puts the count in the tooltip; (b) column headers were `nowrap`, which pushed the machine-effort table into an unnecessary horizontal scroll — headers now wrap. The rightmost column still scrolls inside its panel at this width, which is the documented scrollable-table behaviour, not page overflow. |
| `comparison-mobile.png` | Dark theme. Notice, tables and the variation panel stack; the paired-judgment form's two-column grid collapses to one. Contrast of the muted text on the dark panel is comfortable. No defects found. |
| `blind-review-desktop.png` | Label `B-4FF361` only — no method, model or run ID anywhere on the page. Residual-cues notice is above the fold, files list and viewer sit side by side, check rows show id/description/status only. **Fixed after looking:** rubric dimension labels rendered as raw keys in lower case (`correctness`); they are now capitalized and given more weight. |
| `blind-review-mobile.png` | Dark theme. The package fingerprint wraps inside its cell instead of overflowing, the file list and viewer stack, and the form remains fully usable at 390px. No defects found. |

## Limitations

* Everything above is **browser-tested against synthetic data**. No real provider run, no real
  agent transcript and no real cost figure has been through these pages.
* `contain: paint` on the table wrapper (needed so a wide scrolling table cannot widen the page)
  clips the CSS focus tooltip of a provenance badge that sits inside a table. The native `title`
  tooltip and the visually-hidden text still carry the source in that case.
* Colour contrast was judged by reading the screenshots, not measured with a contrast tool.
