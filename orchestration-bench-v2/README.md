# Orchestration Bench v2

A local bench for one question: **does orchestration produce better work than simply running Astra on low, and when is the gain worth the added effort?**

It gives every candidate setup the same practice tasks in isolated repositories, grades them with the same private checks, puts the results in front of a reviewer who cannot see which setup produced them, and reports quality next to time, tokens, cost and human effort. It never declares a winner for you.

**Status:** the bench is built and validated offline. No model comparison has been run; every real experiment ships *prepared but not ready* until you record the actual model roles. Nothing in setup, tests, validation or either server calls a model.

Requirements: Python 3.10+, Node 22+, Git, macOS or Linux. No installs, no API keys.

## Check that it works

```sh
python3 validate.py
```

Runs every test suite, grader calibration and a complete synthetic lifecycle (prepare → configure → start → capture → grade → blind review → repair → compare → export) with outbound network and provider CLIs blocked. Output lands in `.runtime/validation/` and is labeled synthetic. Add `--skip-browser` if Chrome/Playwright are not available.

## Run an experiment

```sh
python3 bench.py registry                                   # what exists, and what is not ready
python3 bench.py --experiment .runtime/practical prepare --definition practical-setups
python3 bench.py --experiment .runtime/practical serve --open      # operator dashboard, port 4388
python3 bench.py --experiment .runtime/practical serve-review      # separate blind-review server, port 4389
```

`prepare` creates one isolated Git repository per run and a seeded, counterbalanced schedule. `start` refuses until every method in the experiment is configured with the exact models and settings you will really use (`configure`, or the dashboard). Then, per run: launch the method yourself from the run's `LAUNCH.md` → `capture` → `evaluate` → optional `trace-import` of the session transcript → blind review → optional `repair` → `export`.

Three experiments are defined in `experiments/definitions/`:

| Experiment | Compares | Can establish |
|---|---|---|
| `practical-setups` | Astra low solo · Astra low written handoff · Fable directing Opus · native graph candidate | Which complete setup works best under the recorded conditions |
| `fixed-worker` | Solo, written plan, active coordination, graph — same worker model and settings | Whether orchestration helps when worker capability is held constant |
| `internal-review-ablation` | Solo and graph, each with and without the same internal reviewer | Whether a gain comes mainly from extra review |

Still unresolved and deliberately left as `RECORD …` placeholders: the handoff executor, Astra's role in the active setup, and every model/effort for the graph and fixed-worker methods.

## Scenarios

| | Task | What it probes |
|---|---|---|
| S1 | Search/filter correctness fix | Control: delegation may only add overhead |
| S2 | Transactional JSON import | Cross-layer feature work |
| S3 | Archive with expiring undo | Product and interaction judgment |
| S4 | Breadth audit of 12 modules | Parallel coverage; precision vs. padding; stable-ID verdict joins |
| S5 | Shared-contract migration | Coordination across consumers of one contract; integration failures |
| S6 | Interruption and recovery | Restart without lost data or duplicated effects |

S1–S3 are the v1 scenarios, unchanged. `python3 bench.py calibrate` grades each pack's known-correct reference and deliberately wrong submissions. Private grading assets live under each pack's `private/` (and `evaluator/` for S1–S3) and are never copied into a participant workspace or a review package. That is logical separation, not an OS security boundary: give participants only their assigned workspace.

## What the numbers mean

- **Unknown stays unknown.** A missing measurement is `null`/"unknown", never 0. Partial sums are marked partial. Requested and effective model settings are separate; effective stays unverified until evidence exists.
- **Costs are charged to the candidate** — planning, coordination, internal review, integration, retries. Wall time is the union of intervals, not a sum of overlapping ones. Parent totals are never added to their children.
- **First attempt and repaired result are separate**, and compared only within the same scenario version, environment and repeat.
- **No composite score, no automatic winner.** Many repeats of one task are not task diversity; the comparison reports them separately.
- **Synthetic data is labeled** everywhere it appears.

## The graph candidate

`adapters/claude_workflow/` holds one versioned native Claude workflow template, a capability preflight and a bounded offline adapter. Concurrency, worker, attempt and elapsed-time limits are enforced by the bench on the adapter path; token and cost limits are reported as unavailable because the provider offers no reliable control. The live executor fails closed without an explicit run command and passing capability checks, and has never been executed. Read `adapters/claude_workflow/CAPABILITY.md` before a real run: the workflow opt-in also raises reasoning effort, which is a confound, not evidence that orchestration helped.

## Layout

`bench.py` controller · `validate.py` offline validation · `bench_core/` registry, schedule, experiment, traces, metrics, review projection/server · `adapters/` trace importers and the workflow adapter · `scenario_packs/` · `methods/` · `experiments/definitions/` · `bench/` dashboard and review page · `contracts/CONTRACTS.md` formats and rules · `tests/` · `historical-v1/` v1 validation records (not v2 results).

v1 experiments open read-only (`--experiment <v1 dir> status`, `export --out <elsewhere>`); v2 never writes into them.
