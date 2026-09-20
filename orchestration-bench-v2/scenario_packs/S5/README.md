# S5 — shared-contract migration

A `scenario/1` pack. The participant task is to move the note record from v1 to v2 (tags string
to array, `created` to a normalised `createdAt`, new required `archived` and `schemaVersion`)
behind one shared persistence layer and four independently editable consumers, without losing
any of the five real v1 records on disk.

## Layout

```
scenario.json                 the scenario/1 entry (expected check IDs C1…C10)
participant/                  the start state, copied into a run workspace
  TASK.md                     the contract, including the legacy compatibility matrix
  data/notes.json             five v1 records, the only copy
  src/                        store, api, exporter, searchIndex, formatter
  tests/smoke.test.mjs        the public smoke test
private/                      never copied into a workspace or a review package
  grade.mjs                   the grader CLI: the supervisor, which never imports candidate code
  worker.mjs                  the forked worker: the check bodies and the candidate's modules
  checks.mjs                  the check list the supervisor rebuilds the report from
  supervisor.mjs              fork, nonce, census and report-rebuilding helpers
  reference/                  passes C1…C10
  known_bad/                  seven fixtures, each with a NOTE.md naming its intended failure
```

`baseline_regression_gate` is not set: this scenario legitimately changes the behaviour its
start-state smoke test asserts, so the private grader owns regressions (C10).

## How the grade is protected, and what that does not mean

The process the bench launches — `grade.mjs` — **never imports candidate code**. For each check
it forks `worker.mjs`, which imports the submission's modules. The worker is not told where the
report goes: its argv holds only a private temporary directory, its environment is narrowed,
and its working directory is that temporary directory. It offers a result over Node IPC,
authenticated with a per-run random nonce that arrives as the supervisor's first IPC message
and is consumed by the worker harness, in a closure, before any candidate import.

The supervisor then **rebuilds the report from scratch** out of `checks.mjs`: exactly C1…C10,
with any check it did not hear an authenticated result for marked `fail` with
`"no authenticated result (worker exited early, crashed or was tampered with)"`.
`passed`, `total` and `allPassed` are computed by the supervisor, and the exit code comes only
from that rebuilt report. Early exits, timeouts, unauthenticated, duplicate or unknown-ID
messages, writes into the candidate directory and writes to the report path are collected in
`details.tamperSignals`. One worker per check, so a module-level side effect cannot poison a
later check. The `report-forgery`, `mid-import-exit` and `fake-ipc-result` known-bad fixtures
are live attacks against exactly this, kept in calibration so it stays defended.

**This is not a sandbox, and the grader is not tamper-proof.** It defends the *grade* against
report forgery and early-exit tricks. Candidate code still executes with the user's OS
permissions inside the worker — it can read and write files, open sockets and spawn processes
— and a sufficiently adversarial submission could still attack the worker's own channel. What
it cannot do is write its own grade: the only thing an attack on the worker buys is a failed
check and a tamper signal. Run untrusted submissions in a container or a VM if that matters.
