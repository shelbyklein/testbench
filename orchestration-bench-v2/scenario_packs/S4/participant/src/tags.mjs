/**
 * Tag normalisation.
 *
 * normalizeTags(input)
 *   input: an array of strings, or a single comma-separated string, or null/undefined.
 *   Spec:
 *     - null / undefined / "" produce [].
 *     - Every tag is trimmed and lowercased.
 *     - Empty tags are dropped.
 *     - Duplicates are removed CASE-INSENSITIVELY ("Work" and "work" are the same tag).
 *     - The result is sorted ascending (plain string comparison) and contains no duplicates.
 */
export function normalizeTags(input) {
  if (input === null || input === undefined) return [];
  const raw = Array.isArray(input) ? input : String(input).split(',');
  const seen = new Set();
  const out = [];
  for (const item of raw) {
    const trimmed = String(item).trim();
    if (!trimmed) continue;
    if (seen.has(trimmed)) continue;
    seen.add(trimmed);
    out.push(trimmed.toLowerCase());
  }
  return out.sort();
}
