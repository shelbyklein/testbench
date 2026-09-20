# Orchestration Bench

A self-contained practice app and evaluation bench for comparing Astra low solo, written handoffs, and Fable actively orchestrating Opus.

The current v1 bench is implemented and validated. Its nine pilot runs are prepared and unstarted. The v2 orchestration upgrade is planned; no model comparison winner is known.

## Run the preserved pilot

Requirements: Python 3.10+, Node 22+, Git, and macOS or Linux. No package install or API keys are required to open the bench. Model sessions are launched separately through your existing tools.

From a fresh clone:

```sh
python3 -m zipfile -e orchestration-bench.zip .runtime/pilot
cd .runtime/pilot/orchestration-bench
python3 bench.py status
python3 bench.py serve --open
```

Open http://127.0.0.1:4387, or choose a free port with `serve --port 4388 --open`. Extract the archive into a new directory; do not extract it over an experiment in progress.

The ZIP retains all nine independent participant Git repositories and their original baseline commits. Git cannot preserve nested `.git` directories as ordinary tracked source, so the tracked `orchestration-bench/` tree is the inspectable source snapshot; use the extracted archive for the existing pilot. Archive launch notes record the original machine paths. Starting a run regenerates its launch prompt for the current workspace; use that current prompt from the dashboard.

For a new experiment from the tracked source instead:

```sh
cd orchestration-bench
python3 bench.py --experiment ../.runtime/fresh-experiment prepare --repeats 1
python3 bench.py --experiment ../.runtime/fresh-experiment serve --open
```

## Contents

- [Bench instructions and protocol](orchestration-bench/README.md)
- [Recorded v1 validation](orchestration-bench/VALIDATION.md)
- [Upgrade investigation](bench-upgrade-investigation.md)
- [Complete Fable → Opus implementation handoff](fable-opus-orchestration-bench-handoff.md) · [GitHub issue #1](https://github.com/shelbyklein/testbench/issues/1)
- [Current-state archive](orchestration-bench.zip)

Keep v1 frozen while implementing v2 in a separate source directory or worktree. The handoff contains 14 pending tasks, ownership, dependencies, evaluation controls and acceptance checks. Publishing this repository does not start implementation or paid benchmark runs.

The private grading assets are operator-side only. Give benchmark participants only their assigned workspace, not this complete repository.
