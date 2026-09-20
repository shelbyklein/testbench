// Search index. Consumer 3.
// Local copy of the v1 tag helper this consumer used before the migration.
function tagList(note) {
  return String(note.tags ?? '').split(',').map((t) => t.trim()).filter(Boolean);
}


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
