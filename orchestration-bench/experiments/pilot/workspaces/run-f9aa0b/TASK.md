# S2 · Bring a notebook across safely

Add JSON notebook import, from a file picker in the existing UI through validation, API, and persistent storage. A failed import must never leave a partial notebook.

## Public import contract

POST /api/import accepts a JSON object:

```json
{"version":1,"notes":[{"id":"portable-1","folderId":"inbox","title":"From another notebook","body":"A useful thought","tags":["Ideas"],"archived":false,"updatedAt":"2026-09-01T12:00:00.000Z"}]}
```

- version must be the number 1; notes must be an array of at most 500 entries. Empty import is a valid no-op.
- Each entry requires a nonblank string id, an existing folderId, nonblank string title, string body, an array of string tags, boolean archived, and a valid UTC ISO timestamp in the exact YYYY-MM-DDTHH:mm:ss.sssZ form. Do not coerce wrong types or silently fix invalid dates. Preserve valid values as supplied. Unknown extra fields may be ignored.
- Validate every entry before changing any data, including records whose IDs already exist. Reject duplicate IDs within the incoming file. On any invalid input, respond 400 with {"error":"human-readable message"}; leave stored notes and folders unchanged.
- IDs already present in storage are skipped, never overwritten. Import only new IDs. Reimporting the same file is safe. Return 200 with {"imported":N,"skipped":N}. A concurrent retry must not create duplicates or lose a successful import.
- Changes persist across a server restart. Preserve all existing notes and folders. Keep GET /api/state and other existing routes compatible.

## UI acceptance

- Add a clearly labeled Import action and file picker accepting JSON. Show busy state and prevent duplicate submission while importing.
- Show counts on success and a useful error on malformed/invalid files or a failed request. Preserve the current view and existing notes on failure; allow retry, including selecting the same file again.
- Refresh displayed data after success, respecting current controls. Render imported text safely as text, including strings that resemble HTML.
- Make the action and feedback usable with a keyboard and at 390px width. Use the existing visual language; no redesign is required.

## Scope

Do not fix the unrelated search-combination bug or build undo. Import is additive; do not add replacement, folder creation, or migration features.

## Working rules

Work only in this assigned repository. Do not inspect sibling runs, the benchmark controller, evaluator code, other submissions, or reference solutions. This is an experiment convention, not an OS security boundary. Use fresh conversations; do not import prior attempts at this task.

Keep the documented public entry points, PORT/DATA_FILE support, and persistent data compatibility. No external services are required. Do not deploy or publish. Do not modify TASK.md or remove existing tests to obtain a pass. Add appropriate tests and exercise the running UI if affected. Do not expand into the other scenarios' missing features.

Before implementation, write your brief intended approach in APPROACH.md. On completion write SUBMISSION.md with changed behavior, executed checks and results, remaining issues, design assumptions, and all model roles used. Stop when you consider the task done. The operator will freeze the submission before giving external review feedback.

The reviewer will assess functional acceptance, regressions, maintainability, UX (including keyboard/mobile where applicable), and fidelity of your completion report. Code volume, agent count, and verbose explanations do not earn credit.
