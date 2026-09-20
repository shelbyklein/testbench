/**
 * Folder paths.
 *
 * folderPath(segments)
 *   Spec:
 *     - Trims each segment, drops empty segments, joins with " / ".
 *     - An empty list produces "All notes".
 *
 * folderDepth(path)
 *   Spec:
 *     - The number of segments in a path produced by folderPath.
 *     - "All notes" has depth 0.
 */
export function folderPath(segments) {
  const parts = (segments ?? []).map((s) => String(s).trim()).filter(Boolean);
  return parts.length ? parts.join(' / ') : 'All notes';
}

export function folderDepth(path) {
  const text = String(path ?? '').trim();
  if (!text || text === 'All notes') return 0;
  return text.split(' / ').filter(Boolean).length;
}
