import './_attack.mjs';
// API handlers. Consumer 1.
import { loadNotes, saveNotes } from './store.mjs';

function nextId(notes) {
  const numbers = notes.map((n) => Number(String(n.id).replace(/^n-/, ''))).filter((n) => !Number.isNaN(n));
  return `n-${(numbers.length ? Math.max(...numbers) : 0) + 1}`;
}

export function createNote(file, input) {
  if (typeof input?.title !== 'string' || !input.title.trim()) {
    throw new Error('title is required');
  }
  const notes = loadNotes(file);
  const record = {
    id: nextId(notes),
    title: input.title,
    body: typeof input.body === 'string' ? input.body : '',
    tags: typeof input.tags === 'string' ? input.tags : (input.tags ?? []).join(','),
    created: input.created ?? '2026-01-01 00:00:00',
    folder: input.folder ?? null,
  };
  notes.push(record);
  saveNotes(file, notes);
  return record;
}

export function getNote(file, id) {
  return loadNotes(file).find((note) => note.id === id) ?? null;
}

export function listNotes(file) {
  return loadNotes(file);
}
