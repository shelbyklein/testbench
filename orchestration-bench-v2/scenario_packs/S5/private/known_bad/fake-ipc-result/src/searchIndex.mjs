// Search index. Consumer 3.
import { tagList } from './store.mjs';

export function buildIndex(notes) {
  const entries = (notes ?? []).map((note) => ({
    id: note.id,
    title: String(note.title ?? '').toLowerCase(),
    tags: tagList(note).map((t) => t.toLowerCase()),
  }));
  return { entries };
}

export function search(index, query) {
  const term = String(query ?? '').trim().toLowerCase();
  if (!term) return [];
  return (index?.entries ?? [])
    .filter((entry) => entry.title.includes(term) || entry.tags.includes(term))
    .map((entry) => entry.id)
    .sort();
}
