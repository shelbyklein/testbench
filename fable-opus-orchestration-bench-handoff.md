# Fable → Opus handoff: Orchestration Bench v2

Prepared September 20, 2026. Status: implementation-ready handoff; implementation and benchmark model runs have not started.

## Assignment

Fable is the orchestration and integration owner. Use Opus for bounded implementation assignments and a fresh-context final review. Build the v2 bench described here when the user asks you to execute this handoff. Receiving or inspecting this document alone does not dispatch work.

The user's underlying question is: **does orchestration produce better work than simply running Astra on low, and when is the gain worth the added effort?** Deliver a self-contained practice app, discriminating scenarios and a repeatable bench that can answer that question. Do not assume that more agents or a graph will win.

The implementation team (Fable coordinating Opus) is separate from the candidate methods being evaluated. Building this bench does not constitute a benchmark result.

Local Tracker Trapper plan: **local:C83F2B7E-A123-4D6E-834C-82660925A638**

Stable todo IDs: **OB2-01 through OB2-14**

Creation key: **orchestration-bench-v2:fable-opus:2026-09-20**

GitHub repository: **https://github.com/shelbyklein/testbench**, branch **main**.
GitHub issue: **https://github.com/shelbyklein/testbench/issues/1**. All implementation tasks remain pending.

## Source and protected baseline

Repository paths below are relative to the root of the clone. Resolve them to absolute paths for tools and session tracking. The original preparation workspace was /Users/shelbyklein/Documents/Codex/2026-09-20/h; it is provenance, not a required checkout location.

| Purpose | Repository path |
|---|---|
| Frozen v1 source snapshot | orchestration-bench/ |
| Complete frozen v1 archive, including participant Git repositories | orchestration-bench.zip |
| Investigation | bench-upgrade-investigation.md |
| This handoff | fable-opus-orchestration-bench-handoff.md |
| Proposed isolated v2 implementation directory | orchestration-bench-v2/ in a dedicated implementation worktree |
| Proposed Opus worktrees | sibling worktrees outside the integration checkout |
| Final local v2 deliverables | outputs/orchestration-bench-v2 and outputs/orchestration-bench-v2.zip |

The original v1 bench root was not a Git repository. Publication adds an outer source repository without changing v1 files. Its nine participant workspaces are experimental inputs, not implementation checkouts. Their nested Git metadata is retained in the archive, not in the tracked source tree. Follow the repository README to extract a complete pilot into a separate runtime directory.

No v2 implementation commit exists yet. On execution, fetch and record the actual main commit, verify the working tree and active sessions, and create a dedicated integration branch/worktree from that commit. Make an isolated v2 source copy within that worktree and give Opus separate Git worktrees from the same repository. Reconcile existing work before creating anything; do not overwrite a pre-existing v2 directory. Do not initialize a second Git repository inside this published repository.

Recorded SHA-256 values:

- v1 bench.py: caeacdc3cdc2af40a36a98c4d72a39b33ad8b580c8f29305f2d3fe0d16b7902c
- v1 experiments/pilot/experiment.json: 862c679557a91ef096cd23a5c548e76244adbdac797e1de4aad977a9dfaccd68
- v1 ZIP: 6a8e0c3221978eff34c2f57763e96990dc0d307c98ca7be6834ff8501916c05b

All 28 recorded policy-file hashes matched at preparation. All nine pilot runs were prepared, with no first or repair submissions. Their IDs are run-0d7a94, run-96d27a, run-8a6c69, run-3df10f, run-f9aa0b, run-285479, run-5ecdce, run-94b260 and run-880966.

Make a separate source copy for v2, excluding experiments, participant repositories, snapshots, runtime data, caches and node_modules. Retain code, seed, scenario definitions, evaluators and documentation. Keep old validation records explicitly labeled historical or outside the new results directory. Record the published baseline commit and the v2-copy commit, then use isolated worktrees for Opus. Keep v1 and its archive unchanged. Read legacy reports without rewriting their format, hashes or scores; create new experiments under a versioned v2 format.

Current stack: Python standard-library controller, Node-based fixture/evaluator and a local HTML dashboard. Preserve a lightweight local setup. Do not add a framework merely because a post mentions it. The old dashboard used port 4387; choose a free separate port, initially 4388, and do not terminate an unowned server.

## What to build

### 1. Extensible, controlled comparisons

Replace fixed method/scenario branches with versioned registries. Current coupling includes scheduling with modulo three in bench.py, method-specific launch text and fixed evaluator scenario dispatch. A fourth method and an additional fixture must be addable through their definitions rather than controller conditionals.

Generate reproducible schedules from a recorded seed. Pair runs by scenario version, environment, repeat and submission phase. Use randomized, counterbalanced order: each method receives each position equally over complete blocks; disclose imbalance in incomplete blocks. Validate one through five methods and arbitrary scenario subsets. Reject duplicate IDs, missing evaluators, incompatible formats and unconfigured methods before a run starts.

Prepare three experiment definitions:

| Experiment | Comparison | What it can establish |
|---|---|---|
| Practical setups | Astra low solo; Astra low written handoff with explicitly configured executor; Fable actively directing Opus; native graph candidate | Which complete setup works best under the recorded conditions |
| Fixed worker | Solo, written plan, active coordination and graph with the same worker model, settings, tools and environment | Whether orchestration helps when worker capability is held constant |
| Internal-review ablation | Solo and graph, each with and without the same internal reviewer | Whether a gain comes mainly from additional review |

Retain the original small scenarios and Astra low solo. The existing handoff executor and Astra's role in the active setup are unresolved configuration fields. Do not invent them. Record exact available model identifiers and reasoning settings at future run time. Do not silently substitute Fable, Opus or Astra; preserve unknown effective settings as unverified.

Use identical external grading across candidates. Charge candidate planning, coordination, internal review, integration and repair to that candidate. Keep first-attempt and repaired outcomes separate. Give repair attempts equivalent feedback, time allowances and access to tests. Hidden first-attempt checks must not leak to a favored method.

Prepare the configurations without invoking paid models. Flag an experiment as unready until its real model roles and limits are filled in.

### 2. Observable traces and honest metrics

Import observable execution traces before adding broad launch automation. Define a versioned normalized JSONL schema and an adapter interface; implement fixtures representing solo, handoff and active/graph execution. Real transcript formats must be detected and validated rather than guessed. Preserve the raw evidence reference and importer version.

Each event should identify:

- Experiment, run, node, attempt and event IDs; declared parent/dependency IDs; role.
- Requested and effective model/settings; session/context identity.
- Source revision and input/output artifact hashes.
- Event type, timestamp and status.
- Usage measurements, units, provenance and whether measured, estimated or unavailable.

Do not require or extract private reasoning. Redact credentials and unrelated personal content from shared trace fixtures. Unknown measurements remain null/unknown, not zero.

Importing the same event twice must not double-count it. A conflicting payload with the same event ID is an error. Handle out-of-order arrivals with deterministic reconciliation. At a join, account for every expected node: completed, failed, canceled, deliberately skipped or still missing. A failed or missing worker cannot become a successful empty result.

Keep declared and observed graphs distinct. The bench observes a candidate's decomposition; it does not prescribe the same graph to every method. Show source revisions and attempt lineage so stale verdicts and reused artifacts are identifiable.

Report acceptance, serious defects, paired wins/losses/ties and raw per-run outcomes. Show time, tokens, cost and human intervention separately. Break out planner, worker, reviewer, integration and retry usage where evidence supports it. Avoid double-counting parent totals and child usage. Label incomplete traces, clock uncertainty and unsupported critical-path estimates. Do not derive wall time by adding durations that overlap.

Report task-level and repeat variation without treating many repeats of one task as independent task diversity. Do not generate a confident overall winner from the prepared pilot or a composite score that rewards speed enough to conceal broken requirements.

### 3. Scenarios that expose orchestration strengths and failures

Keep S1–S3 behavior and acceptance meaning intact:

- S1: a contained search/filter correctness fix; useful control where delegation may add overhead.
- S2: transactional JSON import, validation, duplicate handling, persistence and usable error/retry behavior.
- S3: archive with expiring undo, recovery, state preservation and keyboard usability.

Add isolated, deterministic S4–S6 packs. Each includes participant instructions, a start-state fixture, public smoke checks, private grading assets, a known-correct reference, deliberately incorrect submissions and reproducible grading commands. Private assets and reference solutions must never enter participant workspaces. This is logical separation, not an OS security boundary; describe the actual isolation available.

**S4 — breadth audit.** Create independent practice-app modules with a frozen private inventory of seeded behavioral defects and plausible nonbugs. Start with a manageable target of 12 modules and six seeded defects; calibrate offline before freezing the scenario version. Participants submit findings with stable IDs, locations, claimed behavior and reproducible evidence. Grade precision, recall, duplicate claims, severity accuracy and coverage; finding count alone earns nothing. Include submissions that miss one defect, report a plausible nonbug and duplicate a genuine finding. Validate matching against reproductions and defect identity, not wording alone.

**S5 — shared-contract migration.** Provide one versioned data/API contract consumed by multiple independently editable modules and a shared persistence layer. Require the new contract, compatibility for the specified legacy inputs, migration of saved records and an integrated user flow. Spell out the compatibility matrix in the participant brief before freezing it. Grade complete versus partial migration, data preservation, serialization round trips and regressions. Include a known-bad branch that passes a single consumer's tests but breaks integration. Observe conflicts and rework when trace evidence exists; do not require a particular decomposition.

**S6 — interruption and recovery.** Use a deterministic transient tool failure plus a restart triggered at a semantic milestone, such as the first acknowledged persisted operation. Apply the same milestone to solo and graph adapters; never trigger “after three agents.” Implement an offline fault wrapper and restartable fake workers to test the bench itself. Grade final feature behavior, preserved data and no duplicated externally visible effects. Record repeated work, recovery cost and reused artifacts only where observed. Make source/artifact identity checks explicit before reuse. Distinguish simulated worker recovery from a verified real coding-agent restart.

For S4 aggregation, cover the article's reproduced failure: rejecting finding A and accepting B must retain B. Join verdicts by stable finding ID and source revision, never by the index of a filtered list. Test reordered verdicts, duplicate retries, missing verdicts and verdict invalidation after source changes. Valid schema shape does not establish a valid finding; reproducible behavioral failures outrank reviewer votes.

An open-ended discovery scenario (S7) is deferred. Bounded iteration, revision-aware deduplication and failure-versus-empty handling still apply to the graph candidate.

### 4. One graph candidate, with explicit runtime limits

Prepare a versioned native Claude workflow candidate using the currently available supported interface. Inspect installed capabilities and current official workflow documentation before implementation. The investigation identified native workflows as a small first experiment; it did not verify availability in this machine's configuration.

Define node inputs/outputs, dependencies, file ownership, stable-ID joins, retry policy and final artifact contract. Give the candidate's internal reviewer a fresh session containing the specification, relevant source/diff and reproducible evidence, without the worker conversation. Include its usage in the candidate budget. Keep the external evaluator separate.

Use a provider-free fake executor for adapter acceptance. Enforce concurrency, maximum workers, total attempts and elapsed-time bounds in bench-controlled execution. Stop and reap owned subprocesses on timeout. Make restart and duplicate-effect tests deterministic. Enforce token/cost limits only where the provider interface supports reliable control; otherwise label those limits advisory or unavailable. Manual launch limits must be labeled unenforced.

A live launch entry point, if implemented, must require an explicit configured run command and fail closed when capability/settings checks fail. Setup, dashboard launch, preflight and tests must not invoke a paid model. If native workflows are unavailable, ship the versioned template, offline adapter contract and clear unsupported status; do not silently replace the harness with raw model API calls.

Verify whether the installed workflow changes reasoning effort, substitutes models, supports headless activation and replays previously successful work after failure. Log requested versus effective values and replay behavior. A workflow keyword that also raises effort is a confound, not evidence that orchestration alone improved quality.

LangGraph, Microsoft Agent Framework, CrewAI, Agno, ADK, AutoGen and Composio integrations are outside this delivery. A durable mixed-provider adapter can follow if measurements justify it.

### 5. Review isolation and usable evidence

Keep the operator dashboard and reviewer data separate. The current blind switch masks display labels while the operator API still contains identities. Build a dedicated review projection and serving/export path that cannot access operator endpoints through its review context. Test actual network payloads and exported files for method/model names, prompt metadata, absolute participant paths and hidden evaluation assets. Document residual cues in submitted source rather than claiming perfect anonymity.

Bind reviews to immutable submission hashes and evaluator versions; reject stale reviews. Preserve first and repair packages separately. Provide graph/timeline views with attempts, failures, missing outputs and evidence links, plus side-by-side quality/resource comparisons. Make unknown and synthetic data conspicuous. Do not populate example dashboards with invented model rankings.

Exercise desktop and mobile widths, keyboard navigation, focus and overflow. Save and inspect screenshots of the running v2 UI. Keep product copy about what the user can assess; put adapter internals in an evidence/details view.

## Fable's orchestration procedure

Fable owns integration, shared contracts and final acceptance. Use at most two implementation workers at a time initially; increase concurrency only for demonstrably independent assignments. This is a proposed execution policy for Fable, not a request to dispatch from the preparation session.

1. Reconcile the baseline, current instructions, existing checkout and Tracker Trapper state. Complete OB2-01 and OB2-02 before parallel implementation.
2. Freeze interface/schema documents and allocate exclusive file ownership. Each worker receives its exact todo IDs, base commit, allowed paths, dependency versions, acceptance commands and return format.
3. Run core and trace work independently against frozen contracts. Then merge in order: core/configuration, trace/metrics, scenarios S4→S5, workflow adapter, scenario S6, review projection, UI.
4. UI work may start against schema fixtures after contracts freeze, but integration waits for the actual projection/API. S6 waits for trace and adapter contracts; its offline fixture may be developed before live capability exists.
5. Stop conflicting assignments before editing a shared contract. Resolve the contract in Fable's integration branch, rebase affected workers and rerun impacted checks. Never have workers overwrite one another's files.
6. After integration, use a fresh Opus review session with this specification, final diff and test evidence. Ask it to look for grader contamination, stale artifact joins, missing work treated as success, resource double-counting and unverified runtime claims. Resolve actionable findings and rerun affected tests.
7. Package and verify the final local artifact. Complete only acceptance-backed todos; do not run the paid comparison study as part of packaging.

Suggested ownership boundaries below are new v2 paths relative to the implementation checkout. Fable may refine them at OB2-02; record the final ownership map before dispatch.

| Owner/lane | Todos | Exclusive files and boundaries |
|---|---|---|
| Fable | 01, 02, 13, 14 | bench.py wiring, shared schemas/contracts, top-level docs, integration, packaging and final evidence |
| Opus core | 03, 04 | bench_core/registry.py, schedule.py, experiment.py; method/experiment definitions; focused core tests |
| Opus observation | 05, 06 | bench_core/traces.py, metrics.py; importer adapters and trace fixtures/tests |
| Opus scenarios | 07, 08, 09 | scenario_packs/S4, S5, S6 and their separate private graders/tests; no core-controller edits |
| Opus workflow | 10 | adapters/claude_workflow and its offline tests; method definition through the frozen registry contract |
| Opus review | 11 | bench_core/review_projection.py, sanitized package exporter and isolation tests |
| Opus UI | 12 | bench/dashboard assets and browser tests; no server/schema edits |

Do not keep a worker active merely to fill a role. The same Opus session can implement sequential related todos; independent review requires a separate context.

Every assignment should use this return contract:

> Return the todo IDs, branch and commit, changed files, decisions affecting contracts, exact commands and outcomes, evidence artifact paths, remaining failures and limitations. State whether evidence is synthetic, fixture-tested, browser-tested or real-provider verified. Do not merge your own branch or mark integration complete.

## Tracker Trapper execution

This plan was registered for future execution; all 14 todos are pending. The publication session reports repository/issue preparation only and does not start an implementation todo. Retrieve the plan by the exact local ID, preserve its stable IDs and reconcile any progress made since this handoff.

At execution, Fable starts its own run with the implementation repository path and its verified session identity. Link its own Claude JSONL using watch_session(runID, sourcePath, format: "claude") and confirm with watch_status. Never link the Codex preparation transcript or another worker's session.

Fable can report implementation todos centrally from worker evidence. If a worker reports directly, give it its own run and exclusive todo assignment; never take over another session's run. Use the latest todo revision from get_plan when required.

Call start_task before a todo; complete_task immediately after its acceptance passes, with evidence. Report meaningful activity and at least every five minutes while actively working. Mark blocked tasks with concrete reasons. Before pausing or ending, finish the session's own run with the real status; unfinished todos stay unfinished.

If MCP fails, inspect persisted state before retrying a write. The fallback CLI is /Users/shelbyklein/Vibes/tracker-trapper/.build/release/tracker-trapper; inspect its help and use the normal shared store. If both reporting paths fail, preserve pending updates and state the limitation. Keep this connected GitHub issue aligned with the same stable todo IDs and verified evidence. Leave the issue open while implementation remains pending; this publication task does not close it.

## Registered checklist and dependencies

The acceptance text below matches the registered local plan. All boxes are pending at preparation.

- [ ] **OB2-01 — Prepare an isolated v2 Git baseline.** Depends on: none. Acceptance: Verify the recorded v1 hashes and nine prepared runs; create the separate v2 source checkout without pilot workspaces or results; record initial commit and rerun baseline tests.

- [ ] **OB2-02 — Freeze shared schemas and lane contracts.** Depends on: OB2-01. Acceptance: Version experiment, scenario, method, trace and reviewer projection contracts; document ownership, dependencies, unknown-value semantics and v1 read-only compatibility before worker assignments.

- [ ] **OB2-03 — Implement extensible registries and balanced scheduling.** Depends on: OB2-02. Acceptance: Add a fourth method and fixture using data only; test 1, 2, 3, 4 and 5 methods, reproducible seeds, paired runs, balanced positions and invalid configuration rejection.

- [ ] **OB2-04 — Prepare controlled comparison configurations.** Depends on: OB2-03. Acceptance: Ship practical, fixed-worker and reviewer-ablation definitions; preserve Astra low solo; block unconfigured runs; record all roles, actual settings and budget enforcement status without launching providers.

- [ ] **OB2-05 — Implement normalized trace import and provenance.** Depends on: OB2-02. Acceptance: Replay synthetic and redacted transcript fixtures idempotently; preserve failed, missing and skipped nodes, source revisions, artifact hashes and unknown telemetry; reject conflicting duplicate event identities.

- [ ] **OB2-06 — Implement effort and recovery analysis.** Depends on: OB2-05. Acceptance: Reconcile role usage to imported totals without double counting; separate waiting, integration, retry and measured overhead; report incomplete traces and paired outcomes without inventing costs or declaring a winner.

- [ ] **OB2-07 — Build the S4 breadth-audit scenario.** Depends on: OB2-03. Acceptance: Provide isolated participant and private grading fixtures with seeded defects and plausible nonbugs; known-good and known-bad submissions validate precision, recall, deduplication and stable-ID verdict joins.

- [ ] **OB2-08 — Build the S5 shared-contract migration scenario.** Depends on: OB2-03. Acceptance: Provide a multi-consumer migration with dependency boundaries; private graders accept a correct integrated reference and reject partial migrations, data loss and contract regressions.

- [ ] **OB2-09 — Build the S6 interruption-and-recovery scenario.** Depends on: OB2-03, OB2-05, OB2-10. Acceptance: Demonstrate the same semantic failure milestone for solo and graph adapters using offline stubs; verify restart recovery, no duplicated effects or lost data, and honest unknown reuse metrics.

- [ ] **OB2-10 — Prepare the native graph method and bounded offline adapter.** Depends on: OB2-03, OB2-05. Acceptance: Ship a versioned workflow with capability preflight and stable-ID aggregation; stub tests enforce concurrency, attempt and time limits, failure accounting and restart behavior; distinguish offline validation from paid model execution.

- [ ] **OB2-11 — Implement isolated blind review projections.** Depends on: OB2-03, OB2-05. Acceptance: Serve reviewer data without method/model identities, operator state or hidden grading data; test network responses and sanitized exports, submission hashes and stale-review rejection.

- [ ] **OB2-12 — Build the graph, timeline and comparison dashboard.** Depends on: OB2-06, OB2-11. Acceptance: Exercise node attempts, missing evidence, resource provenance and blind review at desktop and mobile widths; verify keyboard use and capture inspected screenshots.

- [ ] **OB2-13 — Integrate and independently verify the upgraded bench.** Depends on: OB2-04 through OB2-12. Acceptance: Run original and new functional, lifecycle, grader and browser checks; conduct a fresh-context review; fix findings and prove v1 hashes and prepared pilot states are unchanged.

- [ ] **OB2-14 — Package v2 and publish the local evidence record.** Depends on: OB2-13. Acceptance: Deliver a separate v2 folder and ZIP with launch instructions, prepared example experiment, validation evidence and limitations; demonstrate setup from the ZIP; leave paid benchmark runs unstarted.

## Validation and delivery

Run these existing baseline commands inside the isolated v2 copy before refactoring:

~~~sh
python3 -m unittest discover -s bench -p 'test_*.py'
node --test seed/tests/smoke.test.mjs
~~~

The v1 VALIDATION.md records eight controller tests, 19 lifecycle/evaluator checks and 12 browser checks. Those are historical v1 evidence, not v2 results. Its known-correct fixture fixes were API-focused and do not prove end-to-end UX or model performance.

Provide one documented offline validation command for v2 that runs registry/scheduling, trace reconciliation, grader calibration, budgets/restarts, review isolation and a complete synthetic lifecycle: prepare → configure → start → capture → grade → blind review → repair → compare → export. Keep generated test experiments outside frozen v1. Prove the synthetic executor cannot call a real provider.

For each new grader, show a known-correct reference passing and targeted incorrect submissions failing for the intended reason. Keep tests behavior-focused, especially transactional state, stable-ID joins, missing work, replayed side effects and identity leakage.

For browser validation, use an installed browser and the project's chosen runner. Playwright was previously available through /Users/shelbyklein/Vibes/Newton/node_modules/playwright and Chrome through /Applications/Google Chrome.app; verify availability before reuse, and do not edit Newton. Exercise the actual v2 server at approximately 1440×1100 and 390×844, inspect screenshots and verify the review session's network responses.

Final deliverables:

- A separate v2 source folder and ZIP, preserving v1 byte-for-byte.
- A launch command, concise README and versioned method/scenario/experiment definitions.
- Prepared example runs with real runs unstarted; synthetic validation runs clearly segregated and labeled.
- Private grading fixtures, calibrated references and a participant-export contamination check.
- Trace schema/importers, offline adapter tests and documented native-workflow capability status.
- VALIDATION.md with commands, outcomes, inspected screenshots, artifact hashes and unresolved limitations.
- A concise final report separating implemented, tested, browser-verified and real-provider-verified work.

Verify a clean extraction of the ZIP can set up and run the offline checks. Compare v1 hashes and all nine pilot states again. Do not put credentials, personal transcripts, worker caches or reference answers in participant packages.

The bench upgrade is complete when those artifacts and acceptance checks pass. Paid model trials, claims about which method wins, installation of additional orchestration platforms, changes to Newton/WordPress and public deployment are separate work.

## Research context and sources

The user's two posts supplied concepts, not proof of a quality gain:

- [First post: structured orchestration and verification](https://x.com/rvaniaaaa/status/2083542830086000704)
- [Follow-up: framework and persistence options](https://x.com/rvaniaaaa/status/2101020803487703089)

The investigation recovered the posts through the public FxTwitter API after X returned 403. It did not use the accompanying video as evidence. Its full findings are in the local investigation path above.

Primary references to recheck when implementing provider-specific behavior:

- [Claude workflows](https://code.claude.com/docs/en/workflows)
- [Anthropic: multi-agent research systems](https://www.anthropic.com/engineering/multi-agent-research-system)
- [Anthropic: evaluating agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)
- [LangGraph overview](https://docs.langchain.com/oss/python/langgraph/overview) and [persistence](https://docs.langchain.com/oss/python/langgraph/persistence), for the deferred durable adapter.

This handoff turns those concepts into testable requirements. It does not treat framework popularity, structured JSON, reviewer agreement or a successful fake-worker test as evidence that a real orchestration method outperforms Astra low.
