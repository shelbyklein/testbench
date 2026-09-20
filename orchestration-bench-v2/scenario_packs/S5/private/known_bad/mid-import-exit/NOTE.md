# mid-import-exit — adversarial

**Intended failure: every check (C1…C10), with `details.tamperSignals` naming the call.**

The crudest form of review finding F1: `src/store.mjs` calls `process.exit(0)` while it is being
imported, hoping the grader reads "the process ended cleanly" as "the checks passed".

The worker harness replaces `process.exit` with a throw before any candidate import, so the
call fails its own check loudly instead of silently costing the supervisor an answer, and the
attempt is reported to the supervisor as a tamper signal. Even if the submission reached a real
exit, the supervisor would still fail every check it never heard an authenticated result for.
