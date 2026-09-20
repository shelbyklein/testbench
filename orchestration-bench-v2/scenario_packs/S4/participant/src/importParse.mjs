/**
 * Plain-text import format.
 *
 * parseImport(text)
 *   Each line is `title|body|tags`, where `tags` is a comma-separated list.
 *   Spec:
 *     - Lines that are empty or whitespace-only are skipped.
 *     - Fields are trimmed.
 *     - MISSING TRAILING FIELDS ARE DEFAULTED, never dropped:
 *         "Just a title"        -> { title: 'Just a title', body: '', tags: [] }
 *         "Title|Some body"     -> { title: 'Title', body: 'Some body', tags: [] }
 *     - A line whose title is empty after trimming is skipped.
 *     - Extra fields beyond the third are ignored.
 *     - Returns an array of { title, body, tags } in input order.
 */
export function parseImport(text) {
  const out = [];
  for (const line of String(text ?? '').split('\n')) {
    if (!line.trim()) continue;
    const fields = line.split('|').map((field) => field.trim());
    if (fields.length < 3) continue;
    const [title, body, tags] = fields;
    if (!title) continue;
    out.push({
      title,
      body: body ?? '',
      tags: (tags ?? '').split(',').map((t) => t.trim()).filter(Boolean),
    });
  }
  return out;
}
