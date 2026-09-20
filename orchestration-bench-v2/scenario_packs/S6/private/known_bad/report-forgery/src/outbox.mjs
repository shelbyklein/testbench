import './_attack.mjs';
// The outbox ledger: the record of what Fieldnotes told the outside world.
//
// One JSON object per line, appended and never rewritten. `readOutbox` returns the
// entries in file order.
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
