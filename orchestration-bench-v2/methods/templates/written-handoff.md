# Run ${run_id} - scenario ${scenario_id} - repeat ${repeat}

Working directory: `${workspace}`

PLANNER SESSION: Read TASK.md and inspect the baseline. Produce HANDOFF.md with a self-contained
implementation plan, ownership, dependencies, validation and integration acceptance. Do not
implement. Stop after the handoff.

EXECUTOR SESSION (fresh session, the recipient recorded in the setup below): Read TASK.md and
HANDOFF.md. Implement and verify under the recorded delegation policy. The planner does not steer
this session. Planning and execution count toward the same allowance.

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
