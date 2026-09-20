# Bench validation

The bench was validated locally on September 20, 2026 using Node 24.18.0, Python 3.14.7, Git, and Chrome through Playwright. These checks validate the tool and test sensitivity; they are **not model-comparison results**.

- **8 controller unit tests passed:** missing evidence, missing/duplicate manual checks, incomplete review, serious defects, low rubric scores, evaluator errors, and complete-review acceptance.
- **19 lifecycle/evaluator integration checks passed:** nine equal starting repositories, configuration and version boundaries, first/repair preservation, snapshot hashes, tamper rejection, anonymous exports, null measurements, and evaluator sensitivity.
- **39/39 scenario checks passed against scratch known-correct API implementations.** Those implementations were created only to validate the evaluator, do not constitute complete UX solutions, and are not in participant workspaces.
- **Unsolved fixture rejected correctly:** S1 passed 7/14; S2 passed 3/14; S3 passed 3/11. All original smoke suites passed. This confirms the checks can distinguish the supplied defects/missing features from the scratch fixes.
- **12 browser workflow checks passed:** nine-run rendering, method configuration validation/save, evidence requirements, review persistence, nullable resource measurements, mutation-token enforcement, blind labels, manual acceptance gating after automatic success, mobile page overflow, baseline app rendering, intentional bug reproduction, and baseline archive interaction. No page script errors were observed.
- The dashboard was exercised at **1440×1100** and **390×844**. Desktop and mobile renders were inspected. The final prepared pilot contains **nine unstarted runs**, no scores, and no claimed winner.

Machine-readable evidence is in `validation/controller-and-evaluator.json` and `validation/browser.json`. The browser self-test used a separate scratch experiment with explicitly synthetic review entries; none were copied into the delivered pilot.

To rerun the shipped fast controller checks:

```sh
python3 -m unittest discover -s bench -p 'test_*.py'
node --test seed/tests/smoke.test.mjs
```

Limits: browser verification covers the bench and the baseline practice app, not future participants' implementations. Those require the supplied manual checklists. Three synthetic scenarios are an initial comparison, not proof about larger repositories, native applications, or all future work. The bench records time limits but does not terminate agents or select their model settings.
