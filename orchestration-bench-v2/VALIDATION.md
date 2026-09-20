# Orchestration Bench v2 — validation record

Recorded September 20, 2026 on macOS (Darwin 25.1.0), Python 3.11.5, Node v24.18.0, Git, Chrome 153 driven by Playwright 1.63.0 (borrowed read-only from another local checkout; nothing installed).

**No model was called at any point: not during the build, the tests, the validation, or packaging. No benchmark comparison has been run, and nothing here says which method is better.** Every result below comes from fixtures, stubs and synthetic data.

v1 validation records live in `historical-v1/`. They are v1 evidence, not v2 results.

## How to reproduce

```sh
python3 validate.py                 # everything, including browser checks
python3 validate.py --skip-browser  # when Chrome/Playwright are unavailable
python3 bench.py registry           # definitions load; all three experiments report NOT ready
python3 bench.py calibrate          # reference passes, every known-bad is detected
```

`validate.py` writes `.runtime/validation/validation-report.json` and exits non-zero on any failure, including a missing test suite.

## Result

`python3 validate.py` → **RESULT: ok**

| Suite | Tests | Covers |
|---|---|---|
| `tests/integration` | 21 | v1 review gates carried over unchanged; full synthetic lifecycle; regressions for every controller-side review finding |
| `tests/core` | 69 | Data-only fourth method and extra scenario; schedules for 1–5 methods; seed reproducibility; position balance and disclosed imbalance; pairing; invalid configuration rejection; three definitions unready; no provider process or socket during prepare |
| `tests/observation` | 68 | Idempotent trace replay; conflicting duplicate rejected; order-independent reconciliation; failed/missing/skipped nodes preserved; lineage and stale revisions; unknown usage stays null; inclusive-parent usage not double counted; wall time as interval union; paired outcomes; no winner |
| `tests/scenarios` | 100 | S4–S6 calibration with asserted failure reasons; stable-ID verdict joins; start states fail; determinism; participant/private contamination; grader forgery, early-exit, fake-IPC and path-traversal submissions; S4 brief leak check; S6 same-milestone interruption for solo and graph shapes |
| `tests/workflow` | 78 | Concurrency, worker, total-attempt and elapsed caps (child process reaped); attempt budget global across restarts; failure accounting at the join; stable-ID + revision aggregation; deterministic restart without duplicated effects; fake executor cannot reach a provider; live executor fails closed |
| `tests/review` | 46 | Real HTTP payload bytes and exported files free of method/model/run identities and paths; operator routes absent; traversal and symlinks refused; hidden grading assets absent; hash and evaluator-version binding; stale review → 409; first/repaired separate |
| `tests/ui` | 16 | Page contracts plus the browser run below |

Also: grader calibration **S4 ok, S5 ok, S6 ok** (S1–S3 `unavailable`: v1 never shipped their known-correct references, so there is nothing to calibrate against); registry validation clean; the three real experiments compute **not ready**; v1 hashes unchanged.

**Synthetic lifecycle** (run with non-loopback sockets and provider/network binaries blocked; only `git` and `node` were spawned): prepare → start refused while unconfigured → configure → start → capture → grade → trace import twice (second import adds 0 events) → blind export (0 identity leaks) → blind review → stale review rejected → repair (first submission's hashes unchanged) → compare (winner `null`, composite `null`, labeled synthetic) → export. The "agent" is a file copy of the S5 reference and of its `partial-migration` known-bad; the reference reaches "Meets acceptance", the partial migration "Automated checks failed" until repaired.

## Browser verification

Real servers on ephemeral loopback ports, headless Chrome, 1440×1100 (light) and 390×844 (dark): **118 checks, 0 failures**. Covered: node attempts, failed and missing nodes shown explicitly, unknown never rendered as 0, provenance labels, synthetic banner, no winner, no horizontal overflow, keyboard-only path through trace view, comparison and a submitted blind review, visible focus, stale-package message, the review page requesting only `/review/api/*` with no identity strings in any response, no console errors. Details and per-screenshot inspection notes: `validation/ui/BROWSER_CHECKS.md`.

Inspected screenshots (`validation/ui/`): `dashboard-overview-{desktop,mobile}.png`, `trace-view-{desktop,mobile}.png`, `comparison-{desktop,mobile}.png`, `blind-review-{desktop,mobile}.png`. The integration owner additionally inspected `trace-view-desktop.png` and `comparison-mobile.png`. The demo experiment in those screenshots is synthetic and says so on screen; its method names are invented so identity leaks would be detectable.

## Independent review

After integration, a fresh-context Opus session with only the specification, the final diff and the test evidence reviewed the bench. It confirmed 13 defects; all are fixed and regression-tested:

| # | Severity | Defect | Fix |
|---|---|---|---|
| 1 | critical | S5/S6 graders imported submitted code in-process; a 7-line module forged a 10/10 report | Supervisor/worker graders: the supervisor never loads candidate code and rebuilds the report itself from nonce-authenticated results. The same forgery now scores 0/10 with tamper signals |
| 2 | critical | S4 grader imported a submission-controlled path (`../…`) | Exact module/export allow-list and containment check before any import |
| 3 | major | Controller trusted the grader's own totals | Totals and `allPassed` recomputed from the checks; non pass/fail status is a grader error |
| 4 | major | S4 brief's worked example was one of the seeded defects | Fictional example; test grades every brief example against the oracles |
| 5 | major | Integrity hashes covered only the grader entry file | Every private grading file is hashed |
| 6 | major | A node skipped because its dependency failed counted as a successful join | Forced skips fail the join in traces, metrics and UI |
| 7 | major | Dashboard rendered an all-unknown token rollup as 0 | Renders unknown |
| 8–13 | minor | Missing suite passed validation; lock file written into v1 directories; blind export skipped the leak scan; attempt budget reset on restart; trace conflict crashed the CLI; stale reviews fed comparisons | Each fixed |

Two integration defects were found earlier by the synthetic lifecycle rather than by unit tests: a global `data/` exclusion silently dropped S5's saved records from workspaces and captures, and the v1 "original smoke test must pass" rule failed correct S5 migrations. Both are fixed (`participant.runtime_paths`, `baseline_regression_gate`; contracts 1.1) and regression-tested.

## Frozen v1

| File | SHA-256 | Status |
|---|---|---|
| `orchestration-bench/bench.py` | `caeacdc3cdc2af40a36a98c4d72a39b33ad8b580c8f29305f2d3fe0d16b7902c` | unchanged |
| `orchestration-bench/experiments/pilot/experiment.json` | `862c679557a91ef096cd23a5c548e76244adbdac797e1de4aad977a9dfaccd68` | unchanged |
| `orchestration-bench.zip` | `6a8e0c3221978eff34c2f57763e96990dc0d307c98ca7be6834ff8501916c05b` | unchanged |

All 28 v1 policy hashes matched at the start; `git diff c9b19d9..HEAD` touches only `orchestration-bench-v2/`. A fresh extraction of the v1 archive lists all nine pilot runs as `prepared`. v2 opens v1 experiments read-only and refuses to start, capture, review or export into them.

## What each kind of evidence means here

| State | What is in it |
|---|---|
| Implemented | Registries, schedules, three experiment definitions, trace schema and two importers, metrics, S4–S6 packs, workflow template and adapter, blind review projection and server, dashboard, offline validation, packaging |
| Fixture-tested | All of the above, through the suites listed |
| Browser-verified | Operator dashboard and blind review page, against synthetic data |
| Real-provider verified | **Nothing.** |

## Limitations

- **No real run has happened.** Effective models and settings, real token and cost numbers, real transcripts with subagents, headless workflow activation and native workflow replay are all unverified. The `claude_jsonl` importer was smoke-checked read-only against local transcripts, but subagent (sidechain) splitting is fixture-tested only; transcripts carry no source revision or artifact hashes, so lineage staleness is unavailable for them.
- **The graph candidate cannot run live yet.** Native workflows exist in the installed Claude Code 2.1.278, but there is no workflow CLI subcommand, no saved workflow is installed and no permission rule allows it, so the capability preflight reports unavailable and the live executor refuses. Its opt-in also raises reasoning effort — a confound the fixed-worker and ablation experiments cannot remove by themselves. See `adapters/claude_workflow/CAPABILITY.md`.
- **Experiments are not ready.** The handoff executor, Astra's role in the active setup, and all graph and fixed-worker models remain `RECORD …` placeholders by design.
- **Schedules with 4 methods × 6 scenarios × 1 repeat are position-imbalanced**; this is disclosed in the schedule. Two repeats balance them and double the number of paid runs.
- **Isolation is logical, not an OS boundary.** Graders defend the grade against forgery but are not a sandbox: submitted code runs with your user's permissions. Blind review removes identities from metadata; cues inside submitted source are reported as residual, not removed. The review server is a separate process with no operator routes, running as the same user.
- S1–S3 have no shipped reference solutions, so their graders are not calibrated here. S4 ignores (rather than flags) edits to the audited modules. S5's C6 alone does not prove the index consumer migrated (C8 catches it).
- Method-level comparison shows a partially known cost as unknown; per-role breakdown is assembled in the browser from per-run reports. Contrast was judged from screenshots, not measured.
- Time-based adapter limit tests are the most load-sensitive; one temp-directory cleanup race was seen once under full validation and did not reproduce.
