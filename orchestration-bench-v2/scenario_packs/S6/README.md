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
  grade.mjs                   the grader CLI and the deterministic fault wrapper
  reference/                  passes R1…R10
  known_bad/                  four fixtures, each with a NOTE.md naming its intended failure
```

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
