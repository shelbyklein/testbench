# S5 — Migrate the Fieldnotes note record from v1 to v2

Fieldnotes stores notes in one shared persistence layer (`src/store.mjs`) and reads them from
four independently editable consumers:

| consumer | file | what it does |
|---|---|---|
| API handlers | `src/api.mjs` | creates, reads and lists notes |
| CSV exporter | `src/exporter.mjs` | renders a set of records as CSV |
| Search index | `src/searchIndex.mjs` | builds an index and answers queries |
| Client formatter | `src/formatter.mjs` | turns a record into display strings |

`data/notes.json` holds five real v1 records. They are the only copy: **they must survive the
migration intact.**

Your job is to move the record contract from v1 to v2 everywhere — persistence, all four
consumers, and the saved data — while keeping the legacy inputs in the compatibility matrix
working and breaking nothing that works today.

The four consumers are independent files on purpose. How you split the work is up to you;
no particular decomposition is required or rewarded.

## The v2 record

v1 (what is on disk today):

```json
{ "id": "n-1", "title": "An unfinished thought", "body": "Small tools, kept sharp.",
  "tags": "Tools,small, tools", "created": "2026-01-02 03:04:05", "folder": "Workshop" }
```

v2 (what everything must speak after the migration):

```json
{ "id": "n-1", "title": "An unfinished thought", "body": "Small tools, kept sharp.",
  "tags": ["small", "tools"], "createdAt": "2026-01-02T03:04:05.000Z",
  "folder": "Workshop", "archived": false, "schemaVersion": 2 }
```

Field by field:

- `id`, `title`, `body` — unchanged, preserved exactly.
- `tags` — **string → array.** Split the v1 string on commas, trim each tag, lowercase it,
  drop empty tags, remove duplicates case-insensitively, sort ascending. Missing or empty
  becomes `[]`.
- `created` → **`createdAt`.** The v1 field is `"YYYY-MM-DD HH:MM:SS"` in UTC. Normalize it to
  ISO 8601 with milliseconds and a `Z` suffix: `"2026-01-02T03:04:05.000Z"`. The old `created`
  key is gone from a v2 record.
- `folder` — unchanged, `null` preserved as `null`.
- `archived` — **new required field**, boolean, default `false` for every migrated record.
- `schemaVersion` — **new required field**, the number `2`, on every record.

The saved file keeps its envelope `{ "schemaVersion": <n>, "notes": [ … ] }`, with the envelope
version raised to `2`.

## Required exports

Keep these names and signatures; the integrated flow is driven through them.

```
src/store.mjs        loadNotes(file) -> v2 records      (migrating a v1 file on read)
                     saveNotes(file, notes) -> count    (always writes the v2 envelope)
                     migrateRecord(record) -> v2 record (pure, idempotent)
src/api.mjs          createNote(file, input) -> v2 record (persisted)
                     getNote(file, id) -> v2 record | null
                     listNotes(file) -> v2 records
src/exporter.mjs     exportNotes(notes) -> CSV string
src/searchIndex.mjs  buildIndex(notes) -> index
                     search(index, query) -> [id] sorted ascending
src/formatter.mjs    formatNote(note) -> { title, tagLine, dateLabel, folderLabel, badge }
```

`exportNotes` keeps its CSV shape but moves to the v2 columns:
`id,title,tags,createdAt,folder,archived` — tags joined with `;`, cells containing a comma,
a quote or a newline quoted with `"` and inner quotes doubled.

`formatNote` keeps `tagLine` as `", "`-joined tags and `dateLabel` as the `YYYY-MM-DD` prefix
of the timestamp, `folderLabel` falling back to `"All notes"` when `folder` is `null`, and now
sets `badge` to `"Archived"` for an archived record and `""` otherwise.

## Compatibility matrix

This is the contract for legacy inputs. It is not optional, and it is not symmetric.

| entry point | v1 input | v2 input | must be rejected |
|---|---|---|---|
| `store.loadNotes` | **accepted** — a v1 file on disk is migrated on read | accepted | an envelope whose `schemaVersion` is greater than 2 |
| `store.migrateRecord` | **accepted** | **accepted** — migrating a v2 record returns it unchanged | — |
| `api.createNote` | **accepted** — a caller may still post `{ tags: "a,b", created: "…" }`; it is migrated on the way in and stored as v2 | accepted (`tags: []`, `createdAt`, optional `archived`) | missing / blank / non-string `title`; `tags` that is neither a string nor an array of strings |
| `exporter.exportNotes` | **rejected** | accepted | any record that is not v2 |
| `searchIndex.buildIndex` | **rejected** | accepted | any record that is not v2 |
| `formatter.formatNote` | **rejected** | accepted | any record that is not v2 |

"Rejected" means: throw an `Error` whose message contains the string `schemaVersion`. The three
read-only consumers stop accepting v1 records deliberately — a silent fallback there is how half
a migration survives unnoticed, so it counts as an incomplete migration, not as compatibility.

## Migration of the saved records

- Running the migration over `data/notes.json` must preserve all five records: same ids, same
  titles, same bodies, same folders, tags carrying the same set of tags, timestamps pointing at
  the same instant. Nothing is dropped, renamed away or blanked.
- The migration is **idempotent**: migrating an already-migrated record or file again changes
  nothing. A second run is a no-op.
- `saveNotes` then `loadNotes` round-trips a record set unchanged.

## The integrated flow

This is the flow the whole change is for, and it crosses every consumer:

1. A client posts a legacy-shaped note through `api.createNote` (`tags` as a comma string,
   `created` as a v1 timestamp).
2. It is persisted as a v2 record in `data/notes.json`, alongside the migrated originals.
3. `store.loadNotes` returns the full set as v2 records.
4. `exporter.exportNotes` renders them, `searchIndex.buildIndex` + `search` find the new note
   by one of its tags, and `formatter.formatNote` displays it — all from the same record set,
   with no consumer-specific reshaping in between.

## Do not regress

`api.createNote` still rejects a missing title. `search` still matches a case-insensitive
substring of the title as well as a whole tag, and still returns ids sorted ascending. The CSV
quoting rules are unchanged. `folderLabel` still falls back to `"All notes"`.

## Running things

Node 22+, no dependencies.

```
node --test tests/smoke.test.mjs
```

The smoke tests cover the formatter lightly and nothing else. They are not the grading criteria
and they will not tell you whether the migration is complete.
