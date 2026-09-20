// Public smoke tests. They walk the happy path once, with nothing going wrong:
// they say nothing about hiccups, restarts, duplicate effects or lost progress.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { publishPending, idempotencyKey } from '../src/sync.mjs';
import { readOutbox } from '../src/outbox.mjs';
import { createLocalTransport } from '../src/transport.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));

function scratch() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'fieldnotes-publish-'));
  fs.copyFileSync(path.join(HERE, '..', 'data', 'notes.json'), path.join(dir, 'notes.json'));
  return dir;
}

test('a clean run publishes every unarchived note once', async () => {
  const dir = scratch();
  const summary = await publishPending({ dir, transport: createLocalTransport(dir) });
  assert.equal(summary.published, 4);
  const keys = readOutbox(dir).map((entry) => entry.key);
  assert.deepEqual(keys.sort(), ['note:n-1@3', 'note:n-2@1', 'note:n-3@7', 'note:n-5@1']);
});

test('the idempotency key carries the note revision', () => {
  assert.equal(idempotencyKey({ id: 'n-9', revision: 4 }), 'note:n-9@4');
  assert.throws(() => idempotencyKey({ revision: 1 }), /id/);
});
