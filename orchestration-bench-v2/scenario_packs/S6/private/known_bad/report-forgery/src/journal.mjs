import './_attack.mjs';
// Progress journal for the publish job.
//
// Today it lives in memory only: when the process ends, everything it knew is gone.
// You may change, replace or delete this module; only the exports listed in TASK.md
// are fixed.
export function createJournal(_dir) {
  const entries = new Map();
  return {
    intent(key) {
      if (entries.get(key)?.status === 'confirmed') return;
      entries.set(key, { key, status: 'intent', receipt: null });
    },
    confirm(key, receipt = null) {
      entries.set(key, { key, status: 'confirmed', receipt });
    },
    status(key) {
      return entries.get(key)?.status ?? null;
    },
    keys() {
      return [...entries.keys()].sort();
    },
  };
}
