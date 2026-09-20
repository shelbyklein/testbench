// Public smoke tests. They cover the client formatter lightly and nothing else:
// they say nothing about whether the migration is complete across the other consumers.
import test from 'node:test';
import assert from 'node:assert/strict';

import { formatNote } from '../src/formatter.mjs';

test('the formatter renders a title', () => {
  const view = formatNote({ id: 'n-1', title: 'Seedlings', tags: [], folder: 'Garden' });
  assert.equal(view.title, 'Seedlings');
  assert.equal(view.folderLabel, 'Garden');
});

test('the formatter falls back to All notes', () => {
  const view = formatNote({ id: 'n-2', title: 'Loose ends', tags: [], folder: null });
  assert.equal(view.folderLabel, 'All notes');
});
