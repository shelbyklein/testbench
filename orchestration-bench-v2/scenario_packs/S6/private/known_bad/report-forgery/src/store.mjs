import './_attack.mjs';
// Saved records. The publish job reads them and must never rewrite them.
import fs from 'node:fs';
import path from 'node:path';

export function notesPath(dir) {
  return path.join(dir, 'notes.json');
}

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
