# Run ${run_id} - scenario ${scenario_id} - repeat ${repeat}

Working directory: `${workspace}`

GRAPH CANDIDATE: This run is driven through the execution adapter recorded below, not by pasting
this file into a chat session. The adapter declares its nodes before running, injects its executor,
and emits trace events. Worker outputs and reviewer verdicts are joined by stable node ID and source
revision. The external evaluator remains separate from any internal reviewer node.

If the adapter reports that it is unavailable, the run fails closed. Do not fall back to direct
model calls.

## Frozen setup at start

```json
${method_json}
```

Read TASK.md for the complete request and acceptance contract. Use a fresh session with only this
repository. Keep independent attempts isolated. Do not read the benchmark controller, evaluator, or
other runs.

First-attempt allowance: ${minutes} minutes, including preparation. Repair allowance (only after the
operator freezes and reviews the first result): ${repair} minutes. The bench records but does not
automatically terminate agent sessions; budget enforcement labels in the setup above state what is
actually enforced.

Before coding, save APPROACH.md. When done, save SUBMISSION.md with actual verification evidence and
remaining gaps, then stop. Do not look at external evaluator results before the first capture. A
blocked or unfinished task is a valid experimental result; report it honestly.

This file describes a method, not a mechanism to select models or dispatch agents. The operator must
launch the recorded models and settings in their own tools. If the setup is unconfigured, configure it
before starting.
\n\nBudget limits labeled `enforced` in the setup above are enforced only when this method is executed through the bench's workflow adapter. If you launch it manually from this file, the bench enforces none of them; record that in the run notes.\n