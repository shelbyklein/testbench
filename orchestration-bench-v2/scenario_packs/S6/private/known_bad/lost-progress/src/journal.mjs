// Progress journal: in memory only. Nothing here survives the process.
export function createJournal(_dir) {
  const entries = new Map();
  return {
    intent(key) {
      if (entries.get(key)?.status === 'confirmed') return;
      entries.set(key, { key, status: 'intent', receipt: null });
    },
    confirm(key, receipt = null) { entries.set(key, { key, status: 'confirmed', receipt }); },
    status(key) { return entries.get(key)?.status ?? null; },
    keys() { return [...entries.keys()].sort(); },
  };
}
