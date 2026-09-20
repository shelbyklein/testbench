// Web client formatter. Consumer 4, v2 only.
import { requireV2 } from './store.mjs';

export function formatNote(note) {
  requireV2(note, 'formatNote');
  return {
    title: String(note.title ?? ''),
    tagLine: note.tags.join(', '),
    dateLabel: String(note.createdAt ?? '').slice(0, 10),
    folderLabel: note.folder ?? 'All notes',
    badge: note.archived ? 'Archived' : '',
  };
}
