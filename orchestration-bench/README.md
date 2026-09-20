# Orchestration Bench

A local, reusable experiment for comparing **Astra low solo**, **Astra low with a written handoff**, and **Fable actively orchestrating Opus** on identical coding tasks.

The bench and nine independent workspaces are prepared. **No participating model has run a benchmark attempt.** Validation of the bench itself is reported separately in VALIDATION.md.

## Open the bench

Double-click **Launch Bench.command**, or run:

```sh
python3 bench.py serve --open
```

Run commands from this folder. Open http://127.0.0.1:4387. Node 22+, Python 3.10+, and Git are required; no package install, accounts, API keys, or publishing are required. The controller uses macOS/Linux file locking. If the port is busy, use `serve --port 4388 --open`.

## What is ready

| Scenario | Work being tested | First / repair allowance |
|---|---|---|
| S1 · Find only the notes I asked for | Diagnose a contained filtering bug, preserve behavior, verify API/UI | 30 / 15 min |
| S2 · Bring a notebook across safely | Implement a validated, atomic, persistent import across UI/API/storage | 60 / 20 min |
| S3 · Make archiving feel recoverable | Implement time-limited undo and make sound interaction decisions | 60 / 20 min |

All three start from the same small Fieldnotes app. Each brief defines exact behavioral anchors and deliberate design latitude. The evaluator has 39 checks across the three scenario suites, including repeated regression checks, plus a separate original smoke suite for every submission. Manual UI/accessibility checklists and a five-dimension rubric cover what the automatic checks cannot prove.

## First experiment, step by step

1. **Configure methods in the dashboard.** Solo is recorded as Astra/low. Confirm exact versions/settings/runtime for your actual session. The two orchestration templates need their unresolved roles/settings replaced and `configured` set to true. Put `n/a` for unavailable reasoning controls. Specify delegation limits in notes. If the written handoff uses GitHub, record that transport; the bench prepares the local handoff workflow but does not publish issues.
2. **Select the next run in the displayed balanced order.** Copy its “Start first-attempt clock” command into Terminal. Copy the launch prompt into a fresh agent session opened on that run's workspace. For handoff mode use a planner session, then a fresh executor session as described in the launch prompt. Launch models through your existing tools; the bench does not dispatch them.
3. **At done or the time limit, stop writes and capture.** Use “Capture first submission,” then “Evaluate first submission.” Refresh the dashboard. The evaluator uses a disposable copy, a fresh data file, and the same independent checks. It does not fix the submission. Keep the evaluator and other workspaces out of the implementer's context.
4. **Review without method labels.** Capture all first attempts before sharing external feedback when practical. “Export blind packages” creates source/reviewer bundles with randomized labels. Give a fresh reviewer only those folders. Use Blind review mode on the dashboard for your own scoring. Exercise the actual app and save manual results/evidence. Import a separate review with `review --blind LABEL --phase first --file /path/to/review.json`.
5. **Log effort for every agent.** Cost, tokens, your minutes, and interventions are phase-specific. Leave unavailable measures blank; enter their source. The measured wall clock includes planning and integration. Time limits are recorded, not automatically enforced.
6. **Optionally run the fixed repair round.** Provide factual feedback about that submission's failures; start its repair clock. Capture/evaluate the repaired result separately. Never rewrite the first attempt. Record only additional repair cost/time in repaired metrics.
7. **Compare matched submissions and export.** The comparison table follows the selected scenario, repeat, and phase. Record pairwise preference only after individual reviews. Use “Export all results” for JSON and CSV. There is no invented overall score or automatic winner.

Use `python3 bench.py status` to list the prepared run IDs. The dashboard provides full commands, including absolute paths, so you do not need to construct IDs manually.

## Example lifecycle

Replace RUN_ID with an actual prepared ID:

```sh
python3 bench.py start RUN_ID
# Run the configured agent(s) in that workspace. Stop writes when done.
python3 bench.py capture RUN_ID --phase first
python3 bench.py evaluate RUN_ID --phase first
python3 bench.py blind --phase first
# Complete manual review and resource recording in the dashboard.
python3 bench.py repair RUN_ID
# Apply feedback using the same configured method within the repair allowance.
python3 bench.py capture RUN_ID --phase repaired
python3 bench.py evaluate RUN_ID --phase repaired
python3 bench.py export
```

To prepare another experiment without overwriting this pilot:

```sh
python3 bench.py --experiment experiments/repeat-study prepare --repeats 2
python3 bench.py --experiment experiments/repeat-study serve --port 4388 --open
```

Freeze the bench version for each experiment. Code, scenarios, and evaluator hashes are recorded at preparation and checked before start/capture/evaluation. Each phase can be captured/evaluated once. A failed check is a result; correcting an infrastructure problem warrants a documented fresh run, not silent replacement of evidence.

## Files and separation

- `scenarios/`: exact task briefs and catalog.
- `seed/`: unsolved starting app. `fixtures/` contains UI import examples. Never use this shared seed as a participant workspace.
- `methods/defaults.json`: editable templates copied into new experiments; edit a prepared experiment's methods through the dashboard before any of that method's runs start.
- `evaluator/`: operator-side checks and manual acceptance criteria. Do not provide these files to implementation agents.
- `docs/PROTOCOL.md`, `docs/RUBRIC.md`, `docs/REVIEWER_PROMPT.md`: run rules and reviewer kit.
- `experiments/pilot/workspaces/`: nine independent Git repositories with TASK.md and LAUNCH.md.
- `experiments/pilot/snapshots/`, `receipts/`, `results/`: captured source, hashes, evaluation, and reviews once runs occur.
- `experiments/pilot/blind/`: reviewer packages after export. Mapping remains in operator-owned experiment.json.
- `experiments/pilot/events.jsonl`: append-only operational events. Review revisions are retained separately.

Folder separation and the dashboard's blind switch are not OS security boundaries. For strict isolation, expose only the assigned workspace in a separate sandbox; expose only the exported anonymous package to its reviewer. A code style or source comment can still reveal provenance. The reviewer rubric explains when to inspect completion reports.

## Interpreting the result

Accept only when automatic checks, original smoke tests, manual anchors, and evidence-backed review are complete, with no critical/major defect remaining and each rubric dimension at least 2/3. Missing review is pending, not a pass. Keep correctness, completeness, maintainability, UX, and evidence scores separate. A serious defect outweighs polish.

This nine-run pilot gives a first signal about **complete workflow configurations on this synthetic app**. It is not a reliable estimate of all future coding work. Repeat close/surprising comparisons in fresh sessions. To measure orchestration alone, later compare the same implementer with and without orchestration under fixed tools and budgets.

Prefer the simpler baseline when no meaningful quality or intervention benefit repeats. No current winner is known.
