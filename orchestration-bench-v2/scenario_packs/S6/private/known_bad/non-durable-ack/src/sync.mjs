// The bulk publish job, made resumable.
//
// Per note, in a fixed order:
//   1. already confirmed and in the outbox        -> skip, count as alreadyPublished
//   2. an intent with no confirmation             -> ask the transport what happened
//   3. otherwise                                  -> write intent, send, append, confirm
//
// The write-ahead intent is what makes step 2 possible: a crash between the effect and
// its record leaves a marker, so recovery reconciles with `transport.delivered` instead
// of sending the same key a second time.
import { loadNotes, notesPath } from './store.mjs';
import { appendOnce, hasKey } from './outbox.mjs';
import { createJournal } from './journal.mjs';

export function idempotencyKey(note) {
  if (!note || typeof note.id !== 'string' || !note.id.trim()) {
    throw new Error('a note needs an id before it can be published');
  }
  return `note:${note.id}@${note.revision ?? 1}`;
}

export function pendingNotes(notes) {
  return notes.filter((note) => !note.archived)
    .sort((a, b) => String(a.id).localeCompare(String(b.id)));
}

// A fatal error is the process dying: it is never caught, here or anywhere above.
async function deliver(transport, key, note, maxTransientRetries) {
  let retries = 0;
  for (;;) {
    try {
      return { ok: true, receipt: (await transport.send({ key, note })) ?? null };
    } catch (error) {
      if (error && error.fatal) throw error;
      if (error && error.transient && retries < maxTransientRetries) {
        retries += 1;
        continue;
      }
      return { ok: false, reason: String(error?.message ?? error), retries };
    }
  }
}

export async function publishPending({ dir, transport, maxTransientRetries = 3 }) {
  const notes = loadNotes(notesPath(dir));
  const pending = pendingNotes(notes);
  const journal = createJournal(dir);
  const summary = { published: 0, alreadyPublished: 0, failed: 0, failures: [], keys: [], complete: false };

  for (const note of pending) {
    const key = idempotencyKey(note);

    if (journal.status(key) === 'confirmed' && hasKey(dir, key)) {
      summary.alreadyPublished += 1;
      summary.keys.push(key);
      continue;
    }

    if (journal.status(key) === 'intent' || hasKey(dir, key)) {
      if (await transport.delivered(key)) {
        appendOnce(dir, key, null);
        journal.confirm(key, null);
        summary.alreadyPublished += 1;
        summary.keys.push(key);
        continue;
      }
    }

    // Record it up front so the outbox is never behind the job.
    appendOnce(dir, key, null);
    journal.confirm(key, null);
    const result = await deliver(transport, key, note, maxTransientRetries);
    if (!result.ok) {
      summary.failed += 1;
      summary.failures.push({ key, reason: result.reason });
      continue;
    }
    summary.published += 1;
    summary.keys.push(key);
  }

  summary.keys.sort();
  summary.complete = summary.failed === 0 && summary.keys.length === pending.length;
  return summary;
}
