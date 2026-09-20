/**
 * De-duplicating imported notes.
 *
 * dedupeById(notes)
 *   Spec:
 *     - Notes are de-duplicated by `id`.
 *     - THE LAST OCCURRENCE WINS. An import file is applied top to bottom, so a later
 *       record is a correction of an earlier one with the same id.
 *     - The surviving record keeps the POSITION OF THE FIRST occurrence, so an import
 *       does not reshuffle the list.
 *     - Notes without an `id` are kept as they are and never de-duplicated.
 */
export function dedupeById(notes) {
  const list = notes ?? [];
  const lastById = new Map();
  for (const note of list) {
    if (note?.id === undefined || note?.id === null) continue;
    lastById.set(note.id, note);
  }
  const emitted = new Set();
  const out = [];
  for (const note of list) {
    if (note?.id === undefined || note?.id === null) {
      out.push(note);
      continue;
    }
    if (emitted.has(note.id)) continue;
    emitted.add(note.id);
    out.push(lastById.get(note.id));
  }
  return out;
}
