// CSV exporter. Consumer 2.
import { tagList } from './store.mjs';

const HEADER = ['id', 'title', 'tags', 'created', 'folder'];

export function csvCell(value) {
  const text = String(value ?? '');
  return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

export function exportNotes(notes) {
  const lines = [HEADER.join(',')];
  for (const note of notes ?? []) {
    lines.push([
      csvCell(note.id),
      csvCell(note.title),
      csvCell(tagList(note).join(';')),
      csvCell(note.created),
      csvCell(note.folder),
    ].join(','));
  }
  return `${lines.join('\n')}\n`;
}
