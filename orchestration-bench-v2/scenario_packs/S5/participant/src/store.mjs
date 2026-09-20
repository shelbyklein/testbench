// Shared persistence layer. Every consumer reads its records through this module.
import fs from 'node:fs';

export function loadNotes(file) {
  const raw = JSON.parse(fs.readFileSync(file, 'utf8'));
  const notes = Array.isArray(raw) ? raw : raw.notes;
  if (!Array.isArray(notes)) throw new Error('notes file is malformed');
  return notes;
}

export function saveNotes(file, notes) {
  fs.writeFileSync(file, `${JSON.stringify({ schemaVersion: 1, notes }, null, 2)}\n`);
  return notes.length;
}

// Record shape helper used by the consumers.
export function tagList(note) {
  return String(note.tags ?? '').split(',').map((t) => t.trim()).filter(Boolean);
}
