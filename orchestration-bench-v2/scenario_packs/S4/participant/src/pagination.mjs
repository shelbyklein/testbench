/**
 * Pagination.
 *
 * paginate(items, page, perPage)
 *   Spec:
 *     - `page` is 1-based. Values below 1 are clamped to 1.
 *     - `perPage` below 1 is clamped to 1.
 *     - total = items.length.
 *     - totalPages = ceil(total / perPage), but never below 1 (an empty list has 1 empty page).
 *     - Returns { items: <the slice for this page>, page, perPage, total, totalPages }.
 *     - Every item must be reachable on exactly one page: the last, partially filled page
 *       is a real page.
 */
export function paginate(items, page, perPage) {
  const list = items ?? [];
  const size = Math.max(1, Math.trunc(perPage ?? 1));
  const current = Math.max(1, Math.trunc(page ?? 1));
  const total = list.length;
  const totalPages = Math.max(1, Math.floor(total / size));
  const start = (current - 1) * size;
  return { items: list.slice(start, start + size), page: current, perPage: size, total, totalPages };
}
