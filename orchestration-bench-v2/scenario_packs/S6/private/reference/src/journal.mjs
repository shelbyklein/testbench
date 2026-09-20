// Progress journal for the publish job: durable, rewritten atomically.
//
// `intent` is written *before* an effect is attempted, `confirm` *after* the effect has
// been accepted and written to the outbox. An entry left at `intent` by a crash is the
// signal to ask the transport what actually happened.
import fs from 'node:fs';
import path from 'node:path';

export function journalPath(dir) {
  return path.join(dir, 'journal.json');
}

export function createJournal(dir) {
  const file = journalPath(dir);
  const data = fs.existsSync(file)
    ? JSON.parse(fs.readFileSync(file, 'utf8'))
    : { entries: {} };
  if (!data.entries || typeof data.entries !== 'object') data.entries = {};

  const flush = () => {
    const temp = `${file}.tmp`;
    fs.writeFileSync(temp, `${JSON.stringify(data, null, 2)}\n`);
    fs.renameSync(temp, file); // atomic replace: a reader sees the old or the new file
  };

  return {
    intent(key) {
      if (data.entries[key]?.status === 'confirmed') return;
      data.entries[key] = { key, status: 'intent', receipt: null };
      flush();
    },
    confirm(key, receipt = null) {
      data.entries[key] = { key, status: 'confirmed', receipt };
      flush();
    },
    status(key) {
      return data.entries[key]?.status ?? null;
    },
    keys() {
      return Object.keys(data.entries).sort();
    },
  };
}
