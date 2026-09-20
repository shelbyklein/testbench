# S1 · Find only the notes I asked for

The folder and search controls sometimes show unrelated notes. Fix the filtering behavior through the existing query function, HTTP API, and UI. Preserve the current layout.

## Required behavior

- Folder, search, and archive visibility are combined with AND. An omitted or empty folder means all folders; an unknown folder returns no results.
- Search is case-insensitive; trim surrounding whitespace and split on whitespace. Every word must occur somewhere in the combined title, body, and tags; words may match different fields. Treat punctuation literally, not as a regular expression. An empty/whitespace-only query adds no restriction.
- Archived notes are excluded unless includeArchived is true. That flag adds archived matches; it does not disable the other filters.
- Sort by updatedAt descending, then ID ascending for equal timestamps. Do not mutate the input array or its note objects. Do not change stored records while searching.
- The GET /api/notes query parameters remain q, folderId, and includeArchived=true. Existing public export listNotes(notes, options) remains compatible.
- The UI must show the same matches, a correct count, and the existing empty state. Fast typing must not let an older request replace newer results.

## Reproduction

Select Garden and search for “lamp”. No note should match. Then clear the folder and search for “small tools”: only “An unfinished thought” should match.

## Scope

Fix the bug and verify existing behavior. Import and undo are outside scope.

## Working rules

Work only in this assigned repository. Do not inspect sibling runs, the benchmark controller, evaluator code, other submissions, or reference solutions. This is an experiment convention, not an OS security boundary. Use fresh conversations; do not import prior attempts at this task.

Keep the documented public entry points, PORT/DATA_FILE support, and persistent data compatibility. No external services are required. Do not deploy or publish. Do not modify TASK.md or remove existing tests to obtain a pass. Add appropriate tests and exercise the running UI if affected. Do not expand into the other scenarios' missing features.

Before implementation, write your brief intended approach in APPROACH.md. On completion write SUBMISSION.md with changed behavior, executed checks and results, remaining issues, design assumptions, and all model roles used. Stop when you consider the task done. The operator will freeze the submission before giving external review feedback.

The reviewer will assess functional acceptance, regressions, maintainability, UX (including keyboard/mobile where applicable), and fidelity of your completion report. Code volume, agent count, and verbose explanations do not earn credit.
