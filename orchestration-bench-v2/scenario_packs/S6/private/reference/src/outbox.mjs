// The outbox ledger: the record of what Fieldnotes told the outside world.
//
// One JSON object per line, appended and never rewritten, at most one entry per key.
import fs from 'node:fs';
import path from 'node:path';

export function outboxPath(dir) {
  return path.join(dir, 'outbox.jsonl');
}

export function readOutbox(dir) {
  const file = outboxPath(dir);
  if (!fs.existsSync(file)) return [];
  return fs.readFileSync(file, 'utf8')
    .split('\n')
    .filter((line) => line.trim())
    .map((line) => JSON.parse(line));
}

export function appendEntry(dir, entry) {
  fs.appendFileSync(outboxPath(dir), `${JSON.stringify(entry)}\n`);
  return entry;
}

export function hasKey(dir, key) {
  return readOutbox(dir).some((entry) => entry.key === key);
}

// Keyed and idempotent: the key set is re-read from the file, so a second attempt at the
// same key — in this run or after a restart — appends nothing.
export function appendOnce(dir, key, receipt = null) {
  if (hasKey(dir, key)) return false;
  appendEntry(dir, { key, receipt });
  return true;
}
