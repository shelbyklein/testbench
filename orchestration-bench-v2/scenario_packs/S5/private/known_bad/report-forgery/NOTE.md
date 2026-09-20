# report-forgery — adversarial

**Intended failure: every check (C1…C10), with a non-empty `details.tamperSignals`.**

This fixture is not a wrong solution. It is the attack described in review finding F1, carried
out against this pack's own grader.

`src/_attack.mjs` is imported at the top of all five src modules. At import time it

1. replaces `process.exit` with a no-op, so the grader cannot overwrite the grade afterwards,
2. writes a forged all-pass report to every `.json` path it can find in `process.argv`, in the
   environment and in the working directory,
3. claims success over `process.send` and over stdout,
4. leaves with status 0 through `process.reallyExit`, past the public `process.exit`.

Against the v1 single-process grader this produced a forged 10/10. Against the supervisor /
worker split it reaches only a worker that was never told where the report lives, whose argv
and environment carry no report path and whose IPC messages are worthless without the per-run
nonce. All it achieves is dying early, and an early exit is a failed check: the supervisor
rebuilds the report from its own check list and marks every check it did not hear about as
`fail` with "no authenticated result".

The submission is otherwise the untouched start state, so there is no honest credit to be had
either.
