# fake-ipc-result — adversarial

**Intended failure: the start state's own failures, with `details.tamperSignals` recording the
unauthenticated messages.**

The quiet form of review finding F1: `src/sync.mjs` does not crash and does not exit. It simply
speaks on the result channel — `process.send` and stdout — with a full set of "pass" results,
hoping an unauthenticated claim is believed.

The per-run nonce never reaches candidate code: it arrives as the supervisor's first IPC
message and is consumed by the worker harness, in a closure, before any candidate import.
Messages without it are discarded and counted; stdout is drained and ignored, because it is
not a result channel. The submission is then graded on what it actually does, which is the
untouched start state.
