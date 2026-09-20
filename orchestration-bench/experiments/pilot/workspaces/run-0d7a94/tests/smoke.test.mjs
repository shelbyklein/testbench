import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {initialState} from '../src/seed.mjs';
import {listNotes} from '../src/queries.mjs';
import {createStore} from '../src/store.mjs';
import {createService} from '../src/service.mjs';
test('default listing excludes archived notes and sorts newest first', () => {
  assert.deepEqual(listNotes(initialState().notes).map(n => n.id), ['n4', 'n2', 'n1']);
});
test('archive persists across reopening the store', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'fieldnotes-'));
  try {
    const file = path.join(dir, 'notes.json');
    createService(createStore(file)).archive('n1');
    assert.equal(createStore(file).read().notes.find(n => n.id === 'n1').archived, true);
  } finally {fs.rmSync(dir, {recursive: true, force: true});}
});
