# known_bad: swallowed-failure

Recovery and idempotency are correct, but every non-fatal transport rejection is treated as a
success: the transient hiccup is never retried and a permanent refusal is counted as published.
The job reports a complete result while an external effect is missing. Intended failure: a
swallowed failure reported as done (R3, R4).
