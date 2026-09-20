// Public smoke tests: every module imports and answers its simplest case.
// These do not cover the audit; passing them proves nothing about your findings.
import test from 'node:test';
import assert from 'node:assert/strict';

import { normalizeTags } from '../src/tags.mjs';
import { matchesQuery } from '../src/search.mjs';
import { startOfDayUTC, isOverdue } from '../src/dates.mjs';
import { sortNotes } from '../src/sorting.mjs';
import { parseImport } from '../src/importParse.mjs';
import { paginate } from '../src/pagination.mjs';
import { slugify } from '../src/slug.mjs';
import { countWords, excerpt } from '../src/excerpt.mjs';
import { visibleNotes } from '../src/archive.mjs';
import { dedupeById } from '../src/dedupe.mjs';
import { validateNote } from '../src/validate.mjs';
import { folderPath, folderDepth } from '../src/folders.mjs';

test('tags normalise', () => {
  assert.deepEqual(normalizeTags(' Garden , tools '), ['garden', 'tools']);
});

test('search matches a single term', () => {
  assert.equal(matchesQuery({ title: 'Lamp', body: 'brass' }, 'lamp'), true);
  assert.equal(matchesQuery({ title: 'Lamp', body: 'brass' }, ''), true);
});

test('dates', () => {
  assert.equal(startOfDayUTC('2026-03-04T15:30:00.000Z'), '2026-03-04T00:00:00.000Z');
  assert.equal(isOverdue('2026-03-04T00:00:00.000Z', '2026-03-05T00:00:00.000Z'), true);
});

test('sorting puts the newest first', () => {
  const sorted = sortNotes([
    { title: 'old', updatedAt: '2026-01-01T00:00:00.000Z' },
    { title: 'new', updatedAt: '2026-02-01T00:00:00.000Z' },
  ]);
  assert.deepEqual(sorted.map((n) => n.title), ['new', 'old']);
});

test('import parses a full line', () => {
  assert.deepEqual(parseImport('Title|Body|a, b'), [{ title: 'Title', body: 'Body', tags: ['a', 'b'] }]);
});

test('pagination returns the first page', () => {
  const page = paginate([1, 2, 3, 4], 1, 2);
  assert.deepEqual(page.items, [1, 2]);
  assert.equal(page.total, 4);
});

test('slugify', () => {
  assert.equal(slugify('A small lamp!'), 'a-small-lamp');
});

test('excerpt and word count', () => {
  assert.equal(countWords('two words'), 2);
  assert.equal(excerpt('short'), 'short');
});

test('archive hides archived notes by default', () => {
  assert.deepEqual(visibleNotes([{ id: 1 }, { id: 2, archived: true }]).map((n) => n.id), [1]);
});

test('dedupe collapses repeated ids', () => {
  assert.equal(dedupeById([{ id: 1, title: 'a' }, { id: 1, title: 'b' }]).length, 1);
});

test('validation requires a title', () => {
  assert.equal(validateNote({ title: '' }).ok, false);
  assert.equal(validateNote({ title: 'ok' }).ok, true);
});

test('folders', () => {
  assert.equal(folderPath(['Garden', 'Tools']), 'Garden / Tools');
  assert.equal(folderDepth('All notes'), 0);
});
