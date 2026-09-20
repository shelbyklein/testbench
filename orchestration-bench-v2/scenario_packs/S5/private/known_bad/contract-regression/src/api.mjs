// API handlers. Consumer 1, v2. Legacy-shaped input is still accepted and migrated on the way in.
import { loadNotes, saveNotes, migrateRecord } from './store.mjs';

function nextId(notes) {
  const numbers = notes.map((n) => Number(String(n.id).replace(/^n-/, ''))).filter((n) => !Number.isNaN(n));
  return `n-${(numbers.length ? Math.max(...numbers) : 0) + 1}`;
}

function checkTags(tags) {
  if (tags === undefined || tags === null) return;
  if (typeof tags === 'string') return;
  if (Array.isArray(tags) && tags.every((t) => typeof t === 'string')) return;
  throw new Error('tags must be a string or an array of strings');
}

export function createNote(file, input) {
  if (typeof input?.title !== 'string' || !input.title.trim()) {
    throw new Error('title is required');
  }
  checkTags(input.tags);
  if (typeof input.tags === 'string' || input.created !== undefined) {
    throw new Error('legacy v1 input is no longer accepted; post a v2 record');
  }
  const notes = loadNotes(file);
  const record = migrateRecord({
    id: nextId(notes),
    title: input.title,
    body: typeof input.body === 'string' ? input.body : '',
    tags: input.tags ?? [],
    created: input.created,
    createdAt: input.createdAt ?? input.created ?? '2026-01-01 00:00:00',
    folder: input.folder ?? null,
    archived: Boolean(input.archived),
  });
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
