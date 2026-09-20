// Web client formatter. Consumer 4.
// Local copy of the v1 tag helper this consumer used before the migration.
function tagList(note) {
  return String(note.tags ?? '').split(',').map((t) => t.trim()).filter(Boolean);
}


export function formatNote(note) {
  return {
    title: String(note?.title ?? ''),
    tagLine: tagList(note).join(', '),
    dateLabel: String(note?.created ?? '').slice(0, 10),
    folderLabel: note?.folder ?? 'All notes',
    badge: '',
  };
}
