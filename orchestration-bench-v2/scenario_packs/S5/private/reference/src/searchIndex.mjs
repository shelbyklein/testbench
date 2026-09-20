// Search index. Consumer 3, v2 only.
import { requireV2 } from './store.mjs';

export function buildIndex(notes) {
  const entries = (notes ?? []).map((note) => {
    requireV2(note, 'buildIndex');
    return {
      id: note.id,
      title: String(note.title ?? '').toLowerCase(),
      tags: note.tags.map((t) => String(t).toLowerCase()),
    };
  });
  return { entries, schemaVersion: 2 };
}

export function search(index, query) {
  const term = String(query ?? '').trim().toLowerCase();
  if (!term) return [];
  return (index?.entries ?? [])
    .filter((entry) => entry.title.includes(term) || entry.tags.includes(term))
    .map((entry) => entry.id)
    .sort();
}
