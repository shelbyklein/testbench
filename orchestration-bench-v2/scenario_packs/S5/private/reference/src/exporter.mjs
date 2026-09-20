// CSV exporter. Consumer 2, v2 only.
import { requireV2 } from './store.mjs';

const HEADER = ['id', 'title', 'tags', 'createdAt', 'folder', 'archived'];

export function csvCell(value) {
  const text = String(value ?? '');
  return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

export function exportNotes(notes) {
  const lines = [HEADER.join(',')];
  for (const note of notes ?? []) {
    requireV2(note, 'exportNotes');
    lines.push([
      csvCell(note.id),
      csvCell(note.title),
      csvCell(note.tags.join(';')),
      csvCell(note.createdAt),
      csvCell(note.folder),
      csvCell(note.archived),
    ].join(','));
  }
  return `${lines.join('\n')}\n`;
}
