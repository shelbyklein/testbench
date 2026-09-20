# Fieldnotes

A deliberately small local notes application used for a controlled coding benchmark. Node 22+; no installation or external services required.

```
npm test
npm start
```

Open http://127.0.0.1:4310. Override PORT and DATA_FILE when running multiple copies. The server binds to loopback. Default persistent data lives in ignored `data/notes.json`.

Read TASK.md for your assigned scope. Some incomplete behavior belongs to other benchmark tasks; do not broaden scope without a reason. Existing smoke tests cover only baseline behavior and are not proof of task acceptance. Add meaningful tests for your change.

The app has a JSON file store, service layer, HTTP server, and vanilla browser UI. Public boundaries that must remain compatible: `src/queries.mjs` exports `listNotes`; `node src/server.mjs` honors PORT and DATA_FILE; GET `/api/state`, GET `/api/notes`, and POST `/api/notes/:id/archive` remain available. You may refactor behind those boundaries.
