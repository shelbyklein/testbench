import './_attack.mjs';
// The bulk publish job: push every unarchived saved note to the outbox transport.
//
// It works when nothing goes wrong. Nothing about it survives a hiccup or a restart.
import { loadNotes, notesPath } from './store.mjs';
import { appendEntry } from './outbox.mjs';
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

export async function publishPending({ dir, transport, maxTransientRetries = 3 }) {
  const notes = loadNotes(notesPath(dir));
  const pending = pendingNotes(notes);
  const journal = createJournal(dir);
  const summary = { published: 0, alreadyPublished: 0, failed: 0, failures: [], keys: [], complete: false };

  for (const note of pending) {
    const key = idempotencyKey(note);
    try {
      const receipt = await transport.send({ key, note });
      appendEntry(dir, { key, receipt: receipt ?? null });
      journal.confirm(key, receipt ?? null);
    } catch (error) {
      // TODO: a hiccup and a real failure are not the same thing, and neither of them
      // is a success. Also: maxTransientRetries is accepted and then ignored.
      void error;
      void maxTransientRetries;
    }
    summary.published += 1;
    summary.keys.push(key);
  }

  summary.keys.sort();
  summary.complete = summary.failed === 0;
  return summary;
}
