/**
 * Free-text search over a note.
 *
 * matchesQuery(note, query)
 *   note: { title, body } (missing fields are treated as "").
 *   query: a string. It is split on runs of whitespace into terms.
 *   Spec:
 *     - An empty or whitespace-only query matches every note (returns true).
 *     - Matching is case-insensitive and substring based.
 *     - A note matches only when EVERY term appears in the title or in the body.
 *       ("small tools" matches a note containing both "small" and "tools", in either field.)
 */
export function matchesQuery(note, query) {
  const terms = String(query ?? '').trim().toLowerCase().split(/\s+/).filter(Boolean);
  if (terms.length === 0) return true;
  const haystack = `${note?.title ?? ''} ${note?.body ?? ''}`.toLowerCase();
  return terms.some((term) => haystack.includes(term));
}
