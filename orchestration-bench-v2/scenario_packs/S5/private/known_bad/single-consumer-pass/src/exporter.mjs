// CSV exporter. Consumer 2.
// Local copy of the v1 tag helper this consumer used before the migration.
function tagList(note) {
  return String(note.tags ?? '').split(',').map((t) => t.trim()).filter(Boolean);
}


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
