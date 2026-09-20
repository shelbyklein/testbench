import './_attack.mjs';
// Web client formatter. Consumer 4.
import { tagList } from './store.mjs';

export function formatNote(note) {
  return {
    title: String(note?.title ?? ''),
    tagLine: tagList(note).join(', '),
    dateLabel: String(note?.created ?? '').slice(0, 10),
    folderLabel: note?.folder ?? 'All notes',
    badge: '',
  };
}
