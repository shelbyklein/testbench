# Experiment protocol · version 1

## What this measures

A paired comparison of complete coding workflows on a small synthetic local app. It does not establish which model is intrinsically smarter or predict Newton's native/provider behavior. Start with nine cells (3 tasks × 3 methods), one attempt each. Repeat the full matrix with fresh contexts, or at least repeat close/surprising pairs before choosing a default. Report task-level outcomes; these three selected tasks are too few for a broad statistical claim. If every method passes and reviews tie, the tasks may be too easy to separate them. Conclude no demonstrated benefit at this difficulty; add a harder, separately frozen experiment rather than declaring universal equivalence.

## Before a run

1. Keep one fixed bench version. `prepare` records hashes of the seed, briefs, evaluator, and controller. Each run gets an independent Git repository with identical seed code and a scenario-specific brief.
2. Configure exact roles/versions/effort, allowed delegation, runtime, transport, and tools for each method in the dashboard. Two method templates deliberately require confirmation because the conversation did not establish every role. Changing roles creates a new experiment, not an edit to completed runs.
3. Use the generated balanced schedule. Do not show solutions or evaluator internals to implementers. Human clarification should be brief, logged, and made available to matching runs that have not started. If new substantive requirements emerge, invalidate and rerun affected comparisons.
4. First-attempt wall-clock allowances: S1 30 minutes, S2/S3 60 minutes. Repair allowances: S1 15 minutes, S2/S3 20 minutes. These are pilot defaults, frozen in the experiment file. All planner, executor, reviewer, and integration time counts. Pauses are logged and included in elapsed time; choose a policy before experimenting if they need exclusion. Budgets are recorded, not forcibly enforced by the bench.
5. Give every method the same tool access and original task. Let the method create its own plan. No unpublished baseline solution is provided to any method. If one workflow requires GitHub, publish only the task and that run's own handoff under your normal authorization; this local bench does not create issues or send messages. Count preparation and transport effort. Do not use shared issues that expose one run's solution to another.

## During a run

Use `start RUN_ID` just before the first model begins planning. Paste that run's LAUNCH.md into its fresh session. Written-handoff mode uses separate fresh planner and executor sessions; the planner stops after the handoff. Active mode permits ongoing coordination under the frozen method definition. Solo permits ordinary self-review but no delegation.

Record your intervention time, reasons, and instructions. Method-internal reviewer feedback is part of its first attempt. External evaluator feedback begins only after first capture. Do not coach one method more than another without recording the difference.

At “done” or the time limit, stop agent writes and use `capture RUN_ID --phase first`. It copies source to an immutable-by-convention snapshot and records SHA-256 hashes, Git HEAD/status/diff, elapsed time, and the frozen method definition. It never resets or overwrites the workspace. Capture missing/unfinished work honestly; don't repair it before first capture. A hash mismatch later makes evaluation invalid.

Use `evaluate RUN_ID --phase first`. The evaluator runs a disposable copy with fresh data, not the mutable workspace. Reports persist outside the agent repository. Run the task's manual checklist too; automated checks alone do not establish UI quality or acceptance. Evaluation failures/timeouts are recorded as errors and cannot appear as passes. Existing smoke tests must pass in addition to scenario checks.

## Blind review

`blind --phase first` assigns anonymous labels and copies only submitted source into reviewer packages, stripping Git metadata, LAUNCH, APPROACH, and SUBMISSION. It includes TASK.md, a manual checklist, a blank rubric, and automated evidence. This is practical masking, not guaranteed anonymization: source style/comments and evaluator traces can reveal origin. Ask the reviewer not to infer provenance. Use a separate reviewer session with only the blind export, not the controller or mapping files. The mapping is operator-only.

The dashboard Blind review mode conceals method labels but the operator server still has the mapping. For stronger reviewer isolation, share only the exported packages. Test the running UI, inspect the code, and give evidence-backed rubric scores. Submit the blind package's completed review.json through `review --blind LABEL --phase first --file PATH`. Labels differ between first/repaired phases. Save reviews before revealing methods. Pairwise judgments must be within the same task, repeat, and phase. Tie and incomparable are legitimate outcomes.

## Fixed repair round

Freeze all first submissions before distributing outside feedback when practical. Use a factual list of observed failed acceptance checks and defects, not another method's implementation. `repair RUN_ID` starts the repair clock after first capture and evaluation. Each method receives the same repair time policy, but feedback is specific to its defects. Capture/evaluate the repaired phase separately; the first snapshot and review never change. Record additional intervention and cost separately for each phase. A workflow without repairs remains first-only; don't count its missing repaired record as a failure or silently copy scores.

## Decision rule

Acceptance requires all automated checks and smoke tests passing, all manual anchors passing, zero critical/major unresolved defects, and complete evidence-backed rubric scores of at least 2 in every dimension. Scores are 0–3 by dimension; no composite score is generated. Reviewers must list defects by severity. Critical means data loss/corruption or unsafe execution; major means a required workflow broken; minor means a nonblocking defect. Gates outrank polish. Missing review/evidence means unreviewed, not failed.

For a given task/phase/repeat, compare acceptance and serious defects first, then rubric dimensions and your intervention. If both meet the quality bar and blind preference is a tie, use cost, duration, and simplicity as tiebreakers. Resource totals must include all agents and sessions; unreported costs remain unknown, never zero. Prefer the simpler method when no meaningful quality or intervention benefit repeats. Do not crown a winner from the small pilot automatically.

To isolate orchestration itself later, add same-implementer controls (for example Opus solo versus Opus with a written handoff versus actively orchestrated Opus), keeping tools and budgets fixed. That is a new experiment. The current three methods compare complete setups.

## Isolation and privacy

Each fixture is self-contained and local. Folder separation is not a sandbox; a broadly authorized agent can still read sibling directories. For a strict test, run each repository in a separate container/account with only that repository mounted, and give reviewers only blind exports. Run submitted code only under permissions appropriate to the experiment. No production app data, credentials, deployment, or public GitHub write is needed.

## Integrity boundaries

Snapshots detect accidental later changes; they are not tamper-proof evidence. Controller/evaluator hashes must match the prepared experiment. Source capture excludes only known runtime folders (data, node_modules, .git, .bench) and OS metadata; custom fixtures remain included. Dependencies added by a participant need installation in the disposable evaluation copy; the bench intentionally does not execute install scripts automatically. Mark an evaluation as blocked/error if its runtime cannot be reproduced, rather than counting it as a functional failure. The ready fixture needs only Node 22+, Python 3.10+, and Git.

Reference: https://developers.openai.com/api/docs/guides/evaluation-best-practices (task-specific evaluation and calibrated comparisons). The concrete tasks, time budgets, and decision rule here are proposed pilot design, not externally validated thresholds.
