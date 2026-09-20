# S3 · Make archiving feel recoverable

Archiving currently makes a note disappear with little explanation. Make it feel safe, clear, and easy to undo without interrupting the user's flow. Choose the presentation and explain your decisions briefly; a modal confirmation is not required.

## Behavioral anchors

- Archiving is persistent and reversible for 10 seconds. Keep POST /api/notes/:id/archive; for a successful new archive return 200 containing note, undoToken (nonempty opaque string), and expiresAt (UTC ISO timestamp).
- POST /api/archive/undo with {"token":"..."} restores that note's original archived=false state. Return 200 containing note. Leave title, body, tags, folder, and updatedAt unchanged by archive/undo.
- Only the latest successful new archive is undoable. Archiving a second note invalidates the earlier token, but both notes stay archived until a valid undo. Unknown note IDs return 404; already-archived notes return 409. Those rejected requests must not invalidate a current valid token.
- Unknown, consumed, superseded, or expired tokens return 409 with {"error":"..."} and cause no state change. Expiry is enforced by the server, not just a browser timer. Malformed JSON returns 400.
- Undo eligibility lasts for 10 seconds from archive. It must survive a browser refresh while the server is still running: GET /api/state exposes pendingUndo as null or {token,noteId,expiresAt}. No recovery of undo eligibility across a server restart is required; note state must persist.
- After expiration or successful undo, GET /api/state reports pendingUndo:null. A failed network operation must not falsely tell the user it succeeded.

## Interaction acceptance

- Make the action's outcome and the available Undo action clear without a modal interruption. Provide keyboard access and screen-reader announcements.
- Keep an active Undo control available across a browser reload during the window. Expired controls should no longer promise an available undo.
- If an archived note removes the focused button, move focus to a useful location. Preserve the user's search/folder controls. Rapid consecutive actions should present the latest available undo correctly.
- Failed archive/undo requests should give understandable feedback and leave the UI consistent with confirmed server state. The interaction must work at desktop and 390px width.

## Deliberate design latitude

You choose placement, wording, animation, countdown presentation, and focus destination. Document those choices; there is no hidden preferred design. Do not add a trash system, bulk actions, import, or a broad redesign. The unrelated search-combination bug is outside scope.

## Working rules

Work only in this assigned repository. Do not inspect sibling runs, the benchmark controller, evaluator code, other submissions, or reference solutions. This is an experiment convention, not an OS security boundary. Use fresh conversations; do not import prior attempts at this task.

Keep the documented public entry points, PORT/DATA_FILE support, and persistent data compatibility. No external services are required. Do not deploy or publish. Do not modify TASK.md or remove existing tests to obtain a pass. Add appropriate tests and exercise the running UI if affected. Do not expand into the other scenarios' missing features.

Before implementation, write your brief intended approach in APPROACH.md. On completion write SUBMISSION.md with changed behavior, executed checks and results, remaining issues, design assumptions, and all model roles used. Stop when you consider the task done. The operator will freeze the submission before giving external review feedback.

The reviewer will assess functional acceptance, regressions, maintainability, UX (including keyboard/mobile where applicable), and fidelity of your completion report. Code volume, agent count, and verbose explanations do not earn credit.
