# Orchestration Bench v2 — frozen contracts

Contract set version: **ob2-contracts/1** · frozen at OB2-02 · baseline `c9b19d9`, v2 copy `5215aa0`.

Only Fable (integration owner) edits this directory. A worker who needs a contract change stops,
reports the need in its return message and waits; it does not edit a contract or another lane's files.

Runtime: Python 3.10+ standard library only, Node 22+, Git. No package installs, no network,
no provider calls from setup, tests, preflight or dashboard launch.

## 1. Layout and exclusive ownership

All paths are relative to `orchestration-bench-v2/`.

| Lane | Todos | Owns (exclusive write) |
|---|---|---|
| Fable | 01, 02, 13, 14 | `bench.py`, `bench_core/__init__.py`, `bench_core/common.py`, `contracts/`, `scenario_packs/S1..S3/scenario.json`, `validate.py`, top-level `README.md`, `VALIDATION.md`, `docs/`, packaging |
| Opus core | 03, 04 | `bench_core/registry.py`, `bench_core/schedule.py`, `bench_core/experiment.py`, `methods/`, `experiments/definitions/`, `tests/core/` |
| Opus observation | 05, 06 | `bench_core/traces.py`, `bench_core/metrics.py`, `adapters/trace_importers/`, `tests/observation/` (fixtures under `tests/observation/fixtures/`) |
| Opus scenarios | 07, 08, 09 | `scenario_packs/S4/`, `scenario_packs/S5/`, `scenario_packs/S6/`, `tests/scenarios/` |
| Opus workflow | 10 | `adapters/claude_workflow/`, `methods/graph.json` (created through the method contract), `tests/workflow/` |
| Opus review | 11 | `bench_core/review_projection.py`, `bench_core/review_server.py`, `tests/review/` |
| Opus UI | 12 | `bench/dashboard.html`, `bench/review.html`, `bench/assets/`, `tests/ui/` |

`seed/`, `evaluator/`, `scenarios/` and `historical-v1/` are read-only v1 carry-overs for every lane.
`../orchestration-bench/` and `../orchestration-bench.zip` (frozen v1) are never written by anyone.

Tests are `unittest` modules named `test_*.py` (Python) or `*.test.mjs` (Node `node --test`).
Every lane's tests must pass from the v2 root with:
`python3 -m unittest discover -s tests/<lane> -t . -p 'test_*.py'`.
Generated experiments and temp data go under a `tempfile` directory or `.runtime/`; never inside
`scenario_packs/`, `experiments/definitions/` or frozen v1.

## 2. Dependencies between lanes

```
02 contracts ─┬─ 03 registry/schedule ─┬─ 04 experiment definitions
              │                        ├─ 07 S4 ─ 08 S5
              │                        ├─ 10 workflow adapter (also needs 05)
              │                        └─ 11 review projection (also needs 05)
              └─ 05 traces ─ 06 metrics
09 S6 needs 03 + 05 + 10.   12 UI needs 06 + 11.   13 needs 04–12.   14 needs 13.
```

Lanes code against the interfaces in this document, not against each other's internals.
Merge order: core → observation → S4 → S5 → workflow → S6 → review → UI.

## 3. Unknown-value semantics (all contracts)

- Unknown is JSON `null`. It is never `0`, `""`, `false` or an omitted key where the key is required.
- Every measurement is an object: `{"value": number|null, "unit": str, "provenance": "measured"|"estimated"|"unavailable", "source": str|null}`.
  `provenance == "unavailable"` ⇔ `value is null`. `measured`/`estimated` require a non-empty `source`.
- Aggregates over a set containing any unknown are reported as `{"value": <sum of known>, "complete": false, "unknownCount": n}`;
  consumers must display incompleteness. No aggregate may present a partial sum as a total.
- Requested vs effective settings are separate fields. Effective is `null` with `"verified": false` until observed evidence exists.
  Never copy requested into effective.
- Synthetic/fixture data carries `"synthetic": true` at the top of the artifact and must be displayed as such.
- `bench_core.common` provides `UNKNOWN = None`, `measurement(value, unit, provenance, source)` and `validate_measurement(obj)`.

## 4. v1 read-only compatibility

- A v1 experiment is `experiment.json` with `"version": 1`. v2 may **read** it (status, view, export to a separate output dir)
  and must never write into a v1 experiment directory, rewrite its report format, hashes or scores.
- v2 experiments carry `"format": "ob2-experiment/1"` and `"version": 2`. `bench_core.experiment.load(path)` returns
  `(data, writable)`; `writable` is `False` for version 1. Every mutating command calls `require_writable`.
- Unknown `format`/`version` → refuse with a clear error (incompatible format rejection).
- S1–S3 keep v1 brief text, seed, evaluator and expected check IDs byte-for-byte; their packs only *reference* the v1 files.

## 5. Scenario pack contract — `scenario/1`

`scenario_packs/<ID>/scenario.json`:

```json
{
  "contract": "scenario/1",
  "id": "S4", "version": "1.0.0", "slug": "breadth-audit",
  "title": "…", "kind": "…",
  "minutes": 60, "repair": 20,
  "participant": {"source": "scenario_packs/S4/participant", "brief": "scenario_packs/S4/participant/TASK.md"},
  "public_checks": [["node", "--test", "tests/smoke.test.mjs"]],
  "grader": {
    "argv": ["node", "scenario_packs/S4/private/grade.mjs"],
    "version": "1.0.0",
    "expected_check_ids": ["A1", "A2"],
    "timeout_seconds": 180
  },
  "private": ["scenario_packs/S4/private"],
  "calibration": {
    "reference": "scenario_packs/S4/private/reference",
    "known_bad": [{"id": "missed-defect", "path": "scenario_packs/S4/private/known_bad/missed-defect", "must_fail": ["A3"]}]
  },
  "manual_checks": [{"id": "M1", "description": "…"}]
}
```

- Paths are relative to the v2 root. `participant.source` is copied into the run workspace; **nothing** under any `private` path,
  and no `scenario.json`, may be copied into a workspace or a review package. The registry enforces that `participant.source`
  is not inside, and does not contain, a `private` path. This is logical separation, not an OS security boundary.
- `participant.runtime_paths` (optional, additive in ob2-contracts/1.1): top-level names the practice app writes at run time
  (S1–S3: `["data"]`). They are excluded from capture, snapshots and hashes. Nothing else is excluded, so a pack may ship
  saved records (S5 ships `data/notes.json`) and they are copied, captured and graded.
- `baseline_regression_gate` (optional, default false; additive in 1.1): when true the frozen fixture's `public_checks` must still pass
  for acceptance (v1 meaning, set for S1–S3). Otherwise public checks are run and recorded but do not gate, because a scenario
  such as S5 legitimately changes the behavior its start-state smoke test asserts; its private grader owns regressions.
- For S1–S3: `participant.source` = `seed`, `brief` = `scenarios/S<n>.md`, grader argv = `["node","evaluator/checks.mjs","S<n>"]`,
  `expected_check_ids` = the v1 `EXPECTED` sets, `manual_checks` from `evaluator/manual.json`.
- **Grader CLI**: `<argv…> <candidate_dir> <output.json>`. Exit 0 = all passed, 1 = some failed, anything else = grader error.
  Output: `{"checks":[{"id","description","status":"pass"|"fail","evidence"?}], "passed": n, "total": n, "allPassed": bool, "details"?: {…}}`.
  `{check ids} == expected_check_ids` or the evaluation is an error. Candidate absolute paths are replaced by `<submission>` in evidence.
  Graders are deterministic, offline, and must not write into the candidate directory.
- **Calibration**: the pack's reference passes every check; each `known_bad` fails at least its `must_fail` IDs (and the test asserts the intended reason).
  `bench_core.registry.calibrate(scenario)` runs this and returns a report; scenarios lane tests call it.
- Adding a scenario = adding a directory. No controller or evaluator conditional may name a scenario ID.

## 6. Method contract — `method/1`

`methods/<id>.json`:

```json
{
  "contract": "method/1",
  "id": "solo", "version": "1.0.0", "label": "Astra low · solo",
  "mode": "solo",
  "configured": true,
  "roles": [{"role": "implementer", "model": {"requested": "Astra", "effective": null, "verified": false},
             "reasoning": {"requested": "low", "effective": null, "verified": false}}],
  "transport": "single fresh agent session",
  "launch_template": "methods/templates/solo.md",
  "internal_review": {"enabled": false, "reviewer_role": null},
  "adapter": null,
  "budgets": {
    "max_workers":   {"limit": 1,    "enforcement": "unenforced"},
    "max_attempts":  {"limit": null, "enforcement": "unenforced"},
    "max_minutes":   {"limit": null, "enforcement": "unenforced"},
    "max_tokens":    {"limit": null, "enforcement": "unavailable"},
    "max_cost_usd":  {"limit": null, "enforcement": "unavailable"}
  },
  "notes": "…"
}
```

- `enforcement` ∈ `enforced` (bench-controlled execution stops it) · `advisory` · `unenforced` (manual launch) · `unavailable`.
- `configured: true` is rejected while any string contains `RECORD ` or any role's `model.requested` is null/empty.
  Unresolved roles from v1 (handoff executor, Astra's role in active) stay as `RECORD …` placeholders with `configured: false`. Do not invent them.
- Launch text is rendered from `launch_template` with `string.Template` fields
  `${run_id} ${scenario_id} ${repeat} ${workspace} ${method_json} ${minutes} ${repair}`. No per-mode branches in code.
- `adapter` is `null` (operator-launched) or a module path under `adapters/` exposing the adapter contract (§9).
- Adding a method = adding a JSON file (+ template). No controller conditional may name a method ID or mode.

## 7. Experiment definition and prepared experiment — `experiment-definition/1`, `ob2-experiment/1`

`experiments/definitions/<id>.json`:

```json
{"contract": "experiment-definition/1", "id": "practical-setups", "title": "…", "question": "…",
 "establishes": "…", "methods": ["solo","handoff","active","graph"], "scenarios": ["S1","S2","S3","S4","S5","S6"],
 "repeats": 1, "seed": 20260920, "phases": ["first","repaired"],
 "environment": {"id": "local-default", "notes": "…"},
 "controls": {"same_external_grading": true, "repair_feedback": "identical", "fixed_worker": null, "internal_reviewer": null}}
```

Readiness is **computed**, never stored as true: `experiment.readiness(defn, registry) -> {"ready": bool, "blockers": [str]}`.
Blockers include any unconfigured method, missing evaluator/grader file, incompatible contract, duplicate IDs.
`start` refuses an unready run; `prepare` is allowed for unready definitions (that is the "prepared, unstarted" state).

Prepared `experiment.json` (`"format": "ob2-experiment/1"`, `"version": 2`) holds: `definition`, frozen `methods` and `scenarios`
(full definitions incl. versions), `policyHashes`, `schedule`, `runs`, `pairs`. Each run:
`{id, scenario, scenarioVersion, method, methodVersion, repeat, environment, block, position, order, pairKey, status, phases, metrics, baselineCommit, initialHashes}`
with `pairKey = "<scenario>@<scenarioVersion>|<environment>|r<repeat>"`; paired comparison = same `pairKey` and same phase.

**Schedule** — `schedule.build(method_ids, scenario_ids, repeats, seed) -> dict`:

```json
{"algorithm": "counterbalanced-rotation/1", "seed": 20260920,
 "blocks": [{"block": 1, "scenario": "S1", "repeat": 1, "order": ["handoff","solo","active"]}],
 "balance": {"solo": {"1": 3, "2": 3, "3": 3}},
 "complete": true, "imbalance": []}
```

Deterministic for a given input (uses `random.Random(seed)`, never `SystemRandom`, never wall-clock). One block = one (scenario, repeat).
Over every complete set of `len(methods)` consecutive blocks each method occupies each position exactly once; the base permutation
and block order are seed-randomized. When `blocks % len(methods) != 0`, `complete` is false and `imbalance` lists per-method position
count deviations. Supports 1–5 methods and any non-empty scenario subset. Run IDs are derived deterministically from
`(seed, scenario, repeat, method)` (`run-` + 6 hex of SHA-256).

**Registry** — `registry.load(root) -> Registry` with `.methods`, `.scenarios`, `.definitions` (dicts by id) and
`registry.validate(root) -> [errors]`. Rejects: duplicate IDs, missing grader/brief/template/participant files, unknown contract strings,
participant/private overlap, definitions referencing unknown IDs, `configured: true` with placeholders.

## 8. Trace event contract — `trace-event/1`

Normalized JSONL, one event per line:

```json
{"schema": "trace-event/1",
 "eventId": "evt-…", "experimentId": "…", "runId": "run-…", "nodeId": "worker-a", "attempt": 1,
 "parentId": null, "dependsOn": [], "role": "planner|worker|reviewer|integrator|orchestrator|solo|tool",
 "type": "node_declared|node_started|node_completed|node_failed|node_canceled|node_skipped|artifact|usage|intervention|fault|restart|note",
 "timestamp": "2026-09-20T12:00:00+00:00", "clock": {"source": "provider|bench|transcript|synthetic", "uncertaintySeconds": null},
 "status": "ok|error|unknown",
 "model": {"requested": null, "effective": null, "verified": false},
 "settings": {"requested": {}, "effective": null, "verified": false},
 "session": {"id": null, "contextId": null, "fresh": null},
 "sourceRevision": null,
 "artifacts": {"inputs": [{"path": "…", "sha256": "…"}], "outputs": []},
 "usage": {"inputTokens": {…measurement}, "outputTokens": {…}, "costUSD": {…}, "durationSeconds": {…}, "scope": "self|inclusive"},
 "evidence": {"ref": "relative/path#L10", "sha256": "…", "importer": "synthetic", "importerVersion": "1.0.0"},
 "synthetic": true,
 "payload": {}}
```

- Required non-null: `schema, eventId, runId, nodeId, attempt, role, type, timestamp, status, evidence.importer, evidence.importerVersion`.
  Everything else may be `null`/empty and must then be treated as unknown.
- `usage.scope`: `self` = this node only; `inclusive` = already contains descendants. Metrics must never add an `inclusive` parent to its children.
- No private reasoning text is stored. Importers redact credentials, tokens, emails and absolute home paths (`/Users/<name>` → `~`).
- **Store** — `traces.TraceStore(path)`:
  - `add(events) -> {"added": n, "duplicates": n}`; identical re-import is a no-op (idempotent, compared on canonical JSON);
    same `eventId` with a different payload raises `traces.TraceConflict`.
  - `events()` returns a deterministic order: `(timestamp, nodeId, attempt, eventId)`, independent of arrival order.
  - `declared_graph()` from `node_declared` events vs `observed_graph()` from start/terminal events — kept distinct.
  - `join(expected_node_ids) -> {nodeId: "completed"|"failed"|"canceled"|"skipped"|"missing"|"running"}`; every expected node appears.
    A failed or missing node is never reported as an empty success. `join_ok` is true only when all are `completed` or deliberately `skipped`.
  - `lineage(nodeId)` lists attempts with `sourceRevision` and artifact hashes so stale verdicts/reused artifacts are identifiable.
- **Importer adapter** — a module in `adapters/trace_importers/` exposing `NAME`, `VERSION`, `detect(path) -> bool`,
  `parse(path, run_id, experiment_id) -> Iterable[event]`. `traces.import_file(path, …)` picks the single importer whose `detect` is true;
  zero or multiple matches is an error (formats are detected and validated, never guessed). Ship `synthetic` and a
  `claude_jsonl` importer validated against a redacted fixture.
- **Metrics** — `metrics.analyze(store, run) -> report` and `metrics.compare(experiment, reports) -> comparison`:
  per-role usage (planner/worker/reviewer/integrator/retry) reconciled against imported totals with a `reconciliation` block
  (`matches|mismatch|unknown`); wall time from interval **union**, never a sum of overlapping durations; waiting/integration/retry
  overhead separate; critical path only when dependencies and timestamps support it, else `null` + reason;
  paired wins/losses/ties by `pairKey` and phase; raw per-run rows; task-level vs repeat-level variation kept separate;
  `"winner": null` always, with `"winnerPolicy": "not computed"`; no composite score.

## 9. Execution adapter contract (graph candidate) — `adapter/1`

Module under `adapters/<name>/` exposing:

- `capabilities() -> {"available": bool, "checked": [ {"name","ok","detail"} ], "paidCallsMade": false}` — inspection only, never invokes a model.
- `plan(workflow, scenario, workspace) -> declared nodes` (emitted as `node_declared` events).
- `run(workflow, executor, limits, trace_sink, workspace) -> result` where `executor` is injected. The offline `FakeExecutor`
  is provider-free by construction; the live executor requires an explicitly configured run command and fails closed
  (`available: false` ⇒ refuse) — never silently falls back to raw model API calls.
- `limits`: `max_concurrency`, `max_workers`, `max_attempts_total`, `max_elapsed_seconds` are enforced by the bench
  (owned subprocesses are stopped and reaped on timeout); token/cost limits are reported with their real enforcement label.
- Aggregation joins worker outputs and reviewer verdicts by **stable ID + sourceRevision**, never by list index.
- The internal reviewer node gets a fresh session: specification + relevant source/diff + reproducible evidence, no worker conversation.
  Its usage is charged to the candidate. The external evaluator stays separate.
- Fault injection for S6 is keyed to a **semantic milestone** string (e.g. `first_persisted_ack`), identical for solo and graph adapters.

## 10. Review projection contract — `review-projection/1`

`review_projection.build(exp_dir, phase) -> [projection]`, one per evaluated submission:

```json
{"contract": "review-projection/1", "label": "B-1A2B3C", "scenario": "S2", "scenarioVersion": "1.0.0",
 "repeat": 1, "phase": "first", "submissionHash": "<sha256 of sorted path:hash inventory>", "evaluatorVersion": "1.0.0",
 "files": [{"path": "src/server.mjs", "sha256": "…"}],
 "evaluation": {"checks": [{"id","description","status"}], "passed": 0, "total": 0},
 "reviewTemplate": {…}, "residualCues": "Submitted source may itself reveal its author; anonymity is best-effort."}
```

- Allow-list construction: a projection is built field by field; it is never a filtered copy of operator state.
  Forbidden anywhere in a projection, review HTTP payload or exported package: run IDs, method IDs/labels/modes, model names,
  role lists, launch/prompt text, `LAUNCH.md`/`APPROACH.md`/`SUBMISSION.md`/`HANDOFF.md`/`AGENTS.md`, absolute paths,
  grader private paths, `expected`/hidden assets, check `evidence` stack traces containing paths, pairing or order metadata.
- Labels are random per (run, phase), stored only operator-side in `<exp>/review-map.json`.
- `review_server.serve(exp_dir, port)` is a **separate** HTTP server (own port, default 4389) exposing only
  `GET /` (review.html), `GET /review/api/submissions`, `GET /review/api/submission/<label>`, `GET /review/api/file/<label>/<path>`,
  `POST /review/api/review`. It has no route to operator data and imports nothing from the operator handler.
- A review POST carries `{label, phase, submissionHash, evaluatorVersion, review}`; mismatch with the current immutable
  snapshot hash or evaluator version ⇒ `409 stale review`. First and repaired packages are separate labels.
- `review_projection.export(exp_dir, phase, out_dir)` writes sanitized packages; `review_projection.scan(path_or_obj, forbidden_terms) -> [leaks]`
  is used by tests against real network payloads and exported files.

## 11. Operator API for the UI (served by `bench.py`, default port 4388)

- `GET /api/data` → experiment view (runs, schedule, methods, scenarios, gates, readiness, `integrityOK`, `synthetic`).
- `GET /api/trace/<runId>` → `{"declared": graph, "observed": graph, "join": {…}, "timeline": [events], "lineage": {…}, "synthetic": bool}`.
- `GET /api/metrics` → `metrics.compare` output.
- POST routes as v1 (`/api/review`, `/api/metrics`, `/api/configure`, `/api/pair`), token + Host checked.
- The UI lane develops against fixtures in `tests/ui/fixtures/{data,trace,metrics,review}.json` that follow these shapes.
  Unknown and synthetic values must be conspicuous; no invented rankings in example data.

## 12. Worker return contract

> Return the todo IDs, branch and commit, changed files, decisions affecting contracts, exact commands and outcomes,
> evidence artifact paths, remaining failures and limitations. State whether evidence is synthetic, fixture-tested,
> browser-tested or real-provider verified. Do not merge your own branch or mark integration complete.
