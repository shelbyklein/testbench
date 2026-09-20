/**
 * Archive visibility.
 *
 * visibleNotes(notes, options)
 *   options: { includeArchived = false }
 *   Spec:
 *     - By default archived notes are hidden.
 *     - WHEN includeArchived IS TRUE THE RESULT CONTAINS BOTH archived and unarchived
 *       notes. It is not a filter that shows only archived notes; the archive toggle in
 *       Fieldnotes means "also show archived".
 *     - Input order is preserved; the input array is not modified.
 */
export function visibleNotes(notes, options = {}) {
  const includeArchived = Boolean(options.includeArchived);
  return (notes ?? []).filter((note) => includeArchived || !note?.archived);
}
