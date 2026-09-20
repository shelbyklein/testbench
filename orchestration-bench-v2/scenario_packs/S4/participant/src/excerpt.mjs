/**
 * Excerpts and word counts.
 *
 * countWords(body)
 *   Spec:
 *     - Words are runs of non-whitespace separated by whitespace.
 *     - A HYPHENATED COMPOUND COUNTS AS ONE WORD ("well-worn" is one word), because
 *       Fieldnotes counts what the writer typed, not what a dictionary would split.
 *     - Empty or whitespace-only input counts as 0.
 *
 * excerpt(body, limit = 80)
 *   Spec:
 *     - Collapses whitespace runs to a single space and trims.
 *     - If the collapsed text is at most `limit` characters it is returned unchanged.
 *     - Otherwise it is cut at the last space at or before `limit` and "…" is appended.
 *       The ellipsis is not counted against `limit`.
 */
export function countWords(body) {
  const text = String(body ?? '').trim();
  if (!text) return 0;
  return text.split(/\s+/).length;
}

export function excerpt(body, limit = 80) {
  const text = String(body ?? '').replace(/\s+/g, ' ').trim();
  if (text.length <= limit) return text;
  const cut = text.slice(0, limit);
  const lastSpace = cut.lastIndexOf(' ');
  return `${(lastSpace > 0 ? cut.slice(0, lastSpace) : cut).trimEnd()}…`;
}
