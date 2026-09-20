# S6 — Make the Fieldnotes bulk publish survive a hiccup and a restart

Fieldnotes publishes saved notes to an outbox: an append-only ledger of what it has told
the outside world. The job in `src/sync.mjs` walks every unarchived saved note and sends
it, and it works — as long as nothing goes wrong.

Something always goes wrong. The transport hiccups. The process dies halfway through.
Your job is to make the bulk publish **resumable**: it must survive both, publish every
note exactly once, and never lose or corrupt a saved record.

| file | what it does |
|---|---|
| `src/sync.mjs` | the bulk publish job (`publishPending`) |
| `src/outbox.mjs` | the append-only outbox ledger, `<dir>/outbox.jsonl` |
| `src/journal.mjs` | progress for the job — today it is in memory only |
| `src/store.mjs` | reads the saved records |
| `src/transport.mjs` | a local stand-in transport, for the smoke test and for trying things by hand |

`data/notes.json` holds five saved records, one of them archived. They are the only copy.

## How the job is driven

```js
const summary = await publishPending({ dir, transport, maxTransientRetries = 3 });
```

- `dir` — a working directory that contains `notes.json` (the saved records) and is where
  the job keeps `outbox.jsonl` and any progress it wants to survive a restart.
- `transport` — supplied by the caller. Two methods, both async:
  - `transport.send({ key, note })` → resolves with a receipt once the external effect has
    been accepted. **This is the externally visible effect.** It may throw (see below).
  - `transport.delivered(key)` → resolves `true` if the outside world has already accepted
    that key. This is how you find out what happened before a restart.
- `maxTransientRetries` — how many extra attempts a transient error is worth. Default `3`.

## Required exports

Keep these names and signatures. Everything else — module layout, extra files, what you
persist and how — is yours.

```
src/sync.mjs     publishPending(options) -> Promise<summary>
                 idempotencyKey(note) -> string
                 pendingNotes(notes) -> note[]
src/outbox.mjs   readOutbox(dir) -> entry[]        (entries in file order)
                 outboxPath(dir) -> string
src/store.mjs    loadNotes(file) -> note[]
                 notesPath(dir) -> string
```

The summary is:

```json
{ "published": 3, "alreadyPublished": 1, "failed": 0,
  "failures": [{ "key": "note:n-2@1", "reason": "…" }],
  "keys": ["note:n-1@3", "note:n-2@1"], "complete": true }
```

- `published` — notes whose effect this call performed.
- `alreadyPublished` — notes this call found already done and did **not** send again.
- `failed` / `failures` — notes this call could not publish, with a reason each.
- `keys` — sorted idempotency keys that are published at the end of the call, whether this
  call or an earlier one did it.
- `complete` — `true` only when nothing failed and every pending note is published.
  A missing effect reported as a success is the worst possible outcome here.

## The idempotency key

`idempotencyKey(note)` is `note:<id>@<revision>`, and it already throws when a note has no
id. It is the identity of one externally visible effect: the outbox holds **at most one
entry per key**, and the transport must be asked to send a given key **at most once in
total**, across every run, restart and retry.

## The outbox contract

`<dir>/outbox.jsonl` is one JSON object per line, each with at least a `"key"` string.

- Append-only. Bytes that are already in the file are never rewritten, reordered or
  truncated — not at the start of a run, not on recovery, not ever.
- At most one entry per key.
- No wall-clock timestamps: two identical runs must produce identical outbox files.

## The failure model you must tolerate

The harness will drive your job through exactly these three things. They are deterministic.

1. **A transient transport failure.** `transport.send` rejects with an error carrying
   `error.transient === true`. The same key sent again may well succeed. Up to
   `maxTransientRetries` further attempts are expected; a note published after a hiccup is
   published, not failed — and the retry must not produce a second external effect.
2. **A permanent transport failure.** `transport.send` rejects with an ordinary error
   (no `transient` flag). That note is `failed`, with its reason, and `complete` is `false`.
   The remaining notes are still processed. A later run must be able to publish it.
3. **Process death.** `transport.send` rejects with an error carrying `error.fatal === true`.
   That error stands in for the process being killed mid-flight: **it must propagate out of
   `publishPending` uncaught**, and nothing may run after it. Whatever you have not already
   written down at that instant is gone. A restart is a fresh `publishPending` call on the
   same `dir` — and the outside world remembers what it already accepted, even though your
   process does not.

Death is scheduled at a **semantic milestone**, not after some number of notes or calls:

> **`first_persisted_ack` — the first acknowledged persisted operation.** The instant the
> outbox file on disk durably contains its first entry: one effect has been accepted by the
> transport *and* written down where a restart can see it. The harness kills the process at
> that moment, and also, separately, in the gap between an accepted effect and the record of
> it. Both are real; both must come out with exactly one external effect per key.

## What must be true when you are done

- Every unarchived saved note ends up published exactly once — one outbox entry, one
  `transport.send` per key, no matter how many crashes and retries it took.
- Progress is durable: a restart picks up where the last run stopped and does not redo
  finished work, and a re-run over an already-published set sends nothing at all.
- A crash between an effect and its record is reconciled by asking the transport, not by
  guessing and not by sending again.
- `data/notes.json` is never modified by the job.
- Archived notes are still skipped; a note without an id is still rejected; the local
  transport and the smoke test still work.

The smoke test in `tests/smoke.test.mjs` covers the happy path only. Passing it means nothing about
the failure model above.
