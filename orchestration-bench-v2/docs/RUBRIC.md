# Reviewer rubric

Score each dimension 0–3 and provide concrete evidence (file/function, reproducible behavior, screenshot, or check ID). Do not award credit for claims in completion prose. Record unresolved defects separately; a high score cannot cancel a major defect.

| Dimension | 0 | 1 | 2 | 3 |
|---|---|---|---|---|
| Correctness | Core task unusable | Major required behavior fails | Main flow works; minor defect remains | Required and edge behaviors verified |
| Completeness | Task mostly absent | Important requirements omitted | All core requirements; small gap | All agreed requirements and integration complete |
| Maintainability | Brittle or damaging structure | Significant duplication/coupling or needless machinery | Understandable and fits the app | Clear boundaries, proportionate design, useful tests |
| UX | Workflow unusable/inaccessible | Confusing flow or substantial keyboard/mobile issue | Usable and consistent; minor friction | Clear feedback, keyboard/focus/mobile behavior verified |
| Evidence quality | Claims contradicted or unverified | Important claims lack runnable evidence | Relevant tests and honest limits | Reproducible checks, edge cases, and accurate report |

Manual checks use pass/fail/not_run with evidence. An unexecuted check is not a failure, but acceptance remains pending. For evidence quality only, inspect the original SUBMISSION.md after first judging the source and UI; it may reveal method identity. Record this limitation if blinding is broken. Automated evidence is sufficient to judge executed automated claims; don't punish a concise report.

Independent model review is helpful for finding concrete issues but is not ground truth. Verify alleged bugs, and use human judgment for product tradeoffs. Do not use one participating method as the only judge of its own work. If using a model for pairwise review, swap presentation order and reconcile disagreement rather than counting the two orders as independent samples.
