# S6 — interruption and recovery

A `scenario/1` pack. The participant task is a resumable bulk publish: push every unarchived
saved note to an append-only outbox, survive a transient transport failure and a process death
partway through, never emit a duplicate external effect, never lose a saved record, and finish
with the complete correct result.

## The semantic milestone

The interruption is keyed to **`first_persisted_ack` — the first acknowledged persisted
operation**: the instant the outbox file on disk durably holds its first entry. One effect has
been accepted by the transport *and* written where a restart can see it.

It is never "after N notes", "after N agents" or "after N harness calls". The grader's fault
wrapper observes the durable state before each transport call and fires exactly once, the first
time that state satisfies the definition. The same milestone string is what the workflow adapter
takes in `FaultPlan('first_persisted_ack', 'crash')`, so the scenario and the bench-level
recovery harness are interrupted at the same semantic point.

## Layout

```
scenario.json                 the scenario/1 entry (expected check IDs R1…R10)
participant/                  the start state, copied into a run workspace
  TASK.md                     the contract, the failure model, the milestone definition
  data/notes.json             five saved records, one archived — the only copy
  src/                        store, outbox, journal, sync, a local transport
  tests/smoke.test.mjs        the public smoke test: the happy path, lightly
private/                      never copied into a workspace or a review package
  grade.mjs                   the grader CLI: the supervisor, which never imports candidate code
  worker.mjs                  the forked worker: the fault wrapper and the candidate's modules
  checks.mjs                  the check list the supervisor rebuilds the report from
  supervisor.mjs              fork, nonce, census and report-rebuilding helpers
  reference/                  passes R1…R10
  known_bad/                  seven fixtures, each with a NOTE.md naming its intended failure
```

## How the grade is protected, and what that does not mean

The process the bench launches — `grade.mjs` — **never imports candidate code**. For each check
it forks `worker.mjs`, which imports the submission's modules and runs the fault wrapper. The
worker is not told where the report goes: its argv holds only a private temporary directory,
its environment is narrowed, and its working directory is that temporary directory. It offers
a result over Node IPC, authenticated with a per-run random nonce that arrives as the
supervisor's first IPC message and is consumed by the worker harness, in a closure, before any
candidate import.

The supervisor then **rebuilds the report from scratch** out of `checks.mjs`: exactly R1…R10,
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

`participant.runtime_paths` is deliberately **not** declared. The job writes nothing inside the
participant source at run time — the smoke test and the grader both work in a temporary
directory — so `data/` is captured, hashed and graded like any other shipped record.

`baseline_regression_gate` is false. The start state's smoke test covers only the happy path;
the grader owns regressions (R10).

## What the evidence here is, and is not

Everything in this pack and in `tests/scenarios/test_s6_interruption_recovery.py` is **offline
and synthetic**.

- The grader's transport is a fake. No network, no provider, no model call, no real outbox.
- The "process kill" is a rejected promise carrying `fatal: true`, not a signal to a real
  process. The restart is a second in-process `publishPending` call on the same directory.
- The bench-level recovery harness runs `FakeExecutor` workers through the workflow adapter.
  That is **simulated worker recovery**: it establishes that the bench observes, records and
  scores an interruption correctly. It is **not** a verified real coding-agent restart, and no
  such restart has been performed by this lane.
- Reuse, repeated-work and recovery-cost numbers are reported only where the trace supports
  them. Where it does not, the value is `null` with `provenance: "unavailable"` and a reason —
  never `0`.
