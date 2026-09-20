/**
 * URL slugs for notes.
 *
 * slugify(title)
 *   Spec:
 *     - Lowercase the title.
 *     - Replace every run of characters that is not a Unicode letter, a digit or a
 *       hyphen with a single hyphen.
 *     - NON-ASCII LETTERS ARE KEPT AS THEY ARE. Fieldnotes slugs are unicode slugs;
 *       "Jardín" becomes "jardín", not "jardin". This is deliberate: transliteration
 *       collapses distinct titles onto one slug.
 *     - Trim leading and trailing hyphens. An empty result becomes "note".
 */
export function slugify(title) {
  const lowered = String(title ?? '').toLowerCase();
  const hyphenated = lowered.replace(/[^\p{L}\p{N}-]+/gu, '-');
  const trimmed = hyphenated.replace(/^-+|-+$/g, '');
  return trimmed || 'note';
}
