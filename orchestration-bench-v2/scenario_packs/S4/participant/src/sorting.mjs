/**
 * Note ordering.
 *
 * sortNotes(notes)
 *   Spec:
 *     - Returns a NEW array; the input array is not modified.
 *     - Primary key: `updatedAt` descending (most recently updated first).
 *     - Ties on `updatedAt` are broken by `title` ASCENDING, compared case-insensitively.
 *     - Notes with a missing/invalid `updatedAt` sort last, still title-ascending among themselves.
 */
export function sortNotes(notes) {
  const copy = [...(notes ?? [])];
  const stamp = (note) => {
    const value = new Date(note?.updatedAt).getTime();
    return Number.isNaN(value) ? -Infinity : value;
  };
  copy.sort((a, b) => {
    const delta = stamp(b) - stamp(a);
    if (delta !== 0) return delta;
    const left = String(a?.title ?? '').toLowerCase();
    const right = String(b?.title ?? '').toLowerCase();
    if (left === right) return 0;
    return left < right ? 1 : -1;
  });
  return copy;
}
