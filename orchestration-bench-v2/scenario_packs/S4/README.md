# S4 — breadth audit

A `scenario/1` pack. The participant audits twelve small independent Fieldnotes modules and
submits `FINDINGS.json`: six seeded behavioural defects to find, five spec-conformant oddities
to leave alone. A finding counts only if its submitted `reproduction` actually reproduces —
wording is never matched.

## Layout

```
scenario.json                 the scenario/1 entry (expected check IDs A1…A8)
participant/                  the start state, copied into a run workspace
  TASK.md                     the brief, the FINDINGS.json schema and the severity scale
  src/                        twelve frozen modules, each carrying its spec in a doc comment
  tests/smoke.test.mjs        the public smoke test: the modules load and run
private/                      never copied into a workspace or a review package
  grade.mjs                   the grader CLI: the supervisor. Owns every check.
  repro-worker.mjs            the forked worker: the only process that imports and calls a module
  supervisor.mjs              fork, nonce, census and report-rebuilding helpers
  inventory.json              frozen ground truth: defects, non-bugs, thresholds
  oracles.mjs                 correct implementations of the defective exports
  aggregate.mjs               the finding/verdict join by stable ID and source revision
  reference/                  passes A1…A8
  known_bad/                  six fixtures, each with a NOTE.md naming its intended failure
```

The brief's worked example deliberately uses a **fictional** module and export (`kettle.boilFor`)
that does not exist in `src/`, and says so in the text: the example gives away no module, no
defect and no severity.

## How the grade is protected, and what that does not mean

`reproduction.module` is submission-controlled. It is checked against the exact list of module
basenames read from `participant/src`, and the resolved path must sit directly inside that
directory, before anything is imported; a name that is not on the list is a schema error (A1)
and nothing is executed. `reproduction.export` is checked against what the named module really
exports, built by the worker from the allow-listed modules before it looks at any
submission-controlled name. `reproduction.args` are plain JSON — re-serialised by the
supervisor and parsed in the worker with no reviver — so they are data and cannot smuggle code.

The process the bench launches — `grade.mjs` — never imports a module in order to run a
reproduction. It forks `repro-worker.mjs`, which imports the frozen modules and calls them with
the submitted arguments, and which reports each outcome over Node IPC authenticated with a
per-run random nonce delivered as the supervisor's first IPC message. **Every check, A1…A8, is
computed by the supervisor** from its own `inventory.json` and thresholds; a reproduction that
did not come back authenticated demonstrates nothing, and the fact is recorded in
`details.tamperSignals`. The exit code comes only from that rebuilt report. The
`path-traversal` and `unknown-export` known-bad fixtures are live attacks against exactly this,
kept in calibration so it stays defended.

**This is not a sandbox, and the grader is not tamper-proof.** The code executed in the worker
is this pack's own frozen modules, but it is executed with submission-supplied arguments, and
the worker runs with the user's OS permissions. What a submission cannot do is choose what code
runs or write its own grade.
