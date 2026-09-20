/**
 * Note validation.
 *
 * validateNote(note)
 *   Spec:
 *     - Returns { ok: boolean, errors: string[] }, errors sorted ascending.
 *     - `title` is required: missing, non-string or whitespace-only is an error.
 *     - `title` longer than 120 characters is an error.
 *     - AN EMPTY BODY IS VALID. Fieldnotes deliberately allows a title-only note; a
 *       captured thought is often just a title.
 *     - `tags`, when present, must be an array of strings.
 */
export function validateNote(note) {
  const errors = [];
  const title = note?.title;
  if (typeof title !== 'string' || !title.trim()) errors.push('title is required');
  else if (title.length > 120) errors.push('title is too long');
  if (note?.tags !== undefined) {
    if (!Array.isArray(note.tags) || note.tags.some((t) => typeof t !== 'string')) {
      errors.push('tags must be an array of strings');
    }
  }
  errors.sort();
  return { ok: errors.length === 0, errors };
}
