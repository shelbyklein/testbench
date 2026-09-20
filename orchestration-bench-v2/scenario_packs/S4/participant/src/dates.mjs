/**
 * Date helpers. Everything is UTC; no local time zone is ever consulted.
 *
 * startOfDayUTC(iso) -> ISO string at 00:00:00.000Z of the same UTC day.
 *
 * isOverdue(dueISO, nowISO)
 *   Spec:
 *     - true only when `now` is STRICTLY AFTER `due`.
 *     - A note that is due at exactly the current instant is NOT overdue.
 *     - Invalid or missing input returns false.
 */
export function startOfDayUTC(iso) {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  date.setUTCHours(0, 0, 0, 0);
  return date.toISOString();
}

export function isOverdue(dueISO, nowISO) {
  const due = new Date(dueISO).getTime();
  const now = new Date(nowISO).getTime();
  if (Number.isNaN(due) || Number.isNaN(now)) return false;
  return now >= due;
}
