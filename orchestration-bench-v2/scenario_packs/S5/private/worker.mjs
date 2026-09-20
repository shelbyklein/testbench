// S5 grading worker.  Spawned by grade.mjs as: node worker.mjs <workdir> <scratch> <checkId>
//
// THIS is the process that imports the candidate's modules. It never learns the report path:
// its argv holds only a private temporary directory, and its environment is narrowed by the
// supervisor. It offers exactly one result for exactly one check over an IPC message
// authenticated with a per-run nonce, and the supervisor decides what that is worth.
//
// One worker per check, so a module-level side effect in the candidate cannot poison a later
// check and an early exit costs only the check that was running.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { isDeepStrictEqual } from 'node:util';

import { CHECKS } from './checks.mjs';

// ---------------------------------------------------------------- worker harness
// Everything in this block runs BEFORE any candidate module is imported. It captures the
// references the worker needs, consumes the run nonce from the supervisor's first IPC
// message, and then takes the obvious channel away from anything imported later.
//
// Residual risk, stated plainly: this is defence against report forgery and early-exit
// tricks, not a sandbox. Candidate code runs here with the user's OS permissions, and a
// sufficiently adversarial submission could still reach the IPC channel through Node
// internals. What the design buys is that only the supervisor writes a grade, so such an
// attack costs the candidate a failed check instead of earning it a forged pass.
const RAW_SEND = typeof process.send === 'function' ? process.send.bind(process) : null;
const RAW_DISCONNECT = typeof process.disconnect === 'function' ? process.disconnect.bind(process) : null;
const RAW_EXIT = process.exit.bind(process);

let NONCE = null;
const nonceReady = new Promise((resolve) => {
  const onMessage = (message) => {
    if (NONCE !== null) return;
    if (message && typeof message === 'object' && typeof message.nonce === 'string') {
      NONCE = message.nonce;
      process.removeListener('message', onMessage);
      resolve();
    }
  };
  process.on('message', onMessage);
});

/**
 * Offer one authenticated result and then leave. The channel is closed from here, and an
 * unref'd backstop timer exits the worker even if candidate code left a handle open, so a
 * submission cannot hold the supervisor hostage past the per-check timeout.
 */
function report(payload) {
  const done = () => {
    try { RAW_DISCONNECT?.(); } catch { /* already disconnected */ }
    const backstop = setTimeout(() => RAW_EXIT(0), 2000);
    backstop.unref?.();
  };
  if (!RAW_SEND || NONCE === null) { done(); return; }
  try { RAW_SEND({ __nonce: NONCE, ...payload }, undefined, undefined, done); }
  catch { done(); }
}

/** Things the submission did that a submission has no business doing. Reported, never trusted. */
const TAMPER = [];

/**
 * Close the obvious doors before candidate code gets a turn.
 *
 * `process.send` is replaced by a forwarder that strips the nonce, so a submission's "all pass"
 * message can never be mistaken for a result and the supervisor still learns that it was tried.
 * `process.exit` is replaced by a throw, so an import-time exit fails its own check loudly
 * instead of silently costing the supervisor an answer.
 */
function harden() {
  try {
    process.send = (message) => {
      TAMPER.push('the submission called process.send during grading');
      try { RAW_SEND?.({ __unauthenticated: true, message: String(message && message.type) }); } catch { /* gone */ }
      return false;
    };
  } catch { /* non-writable is fine */ }
  try {
    process.exit = (code) => {
      TAMPER.push(`the submission called process.exit(${code === undefined ? '' : code}) during grading`);
      throw new Error(`the submission called process.exit(${code === undefined ? '' : code}) during grading`);
    };
  } catch { /* non-writable is fine */ }
  try { process.removeAllListeners('message'); } catch { /* nothing attached */ }
  try { Object.freeze(JSON); } catch { /* already frozen */ }
}

// ---------------------------------------------------------------- setup
const [workdirArg, scratchArg, checkId] = process.argv.slice(2);
const workdir = path.resolve(workdirArg ?? '');
const scratch = path.resolve(scratchArg ?? '');

const scrub = (value) => {
  const text = typeof value === 'string' ? value : (JSON.stringify(value) ?? String(value));
  return text.split(scratch).join('<scratch>')
             .split(workdir).join('<workdir>')
             .split(os.tmpdir()).join('<tmp>');
};
const clip = (text, limit = 420) => (text.length > limit ? `${text.slice(0, limit)}…` : text);

// The migrated form of the five records shipped in data/notes.json. Ground truth for S5.
const EXPECTED = [
  { id: 'n-1', title: 'An unfinished thought', body: 'Small tools, kept sharp.',
    tags: ['small', 'tools'], createdAt: '2026-01-02T03:04:05.000Z', folder: 'Workshop',
    archived: false, schemaVersion: 2 },
  { id: 'n-2', title: 'Lamp, brass', body: 'A "small" brass lamp on the bench.',
    tags: ['garden'], createdAt: '2026-01-03T11:22:33.000Z', folder: 'Garden',
    archived: false, schemaVersion: 2 },
  { id: 'n-3', title: 'Seedlings', body: '', tags: [],
    createdAt: '2026-02-14T08:00:00.000Z', folder: 'Garden', archived: false, schemaVersion: 2 },
  { id: 'n-4', title: 'Loose ends', body: 'No folder for this one yet.', tags: ['misc'],
    createdAt: '2026-02-20T19:45:01.000Z', folder: null, archived: false, schemaVersion: 2 },
  { id: 'n-5', title: 'Winter list', body: 'Firewood, gutters, the gate.', tags: ['house', 'winter'],
    createdAt: '2026-03-01T00:00:00.000Z', folder: 'House', archived: false, schemaVersion: 2 },
];
const V1_SAMPLE = { id: 'n-1', title: 'An unfinished thought', body: 'Small tools, kept sharp.',
                    tags: 'Tools,small, tools', created: '2026-01-02 03:04:05', folder: 'Workshop' };

const NOTES_SOURCE = path.join(workdir, 'data', 'notes.json');
let counter = 0;
function freshData() {
  const file = path.join(scratch, `notes-copy-${counter++}.json`);
  fs.copyFileSync(NOTES_SOURCE, file);
  return file;
}

async function load(name) {
  const file = path.join(workdir, 'src', `${name}.mjs`);
  if (!fs.existsSync(file)) throw new Error(`src/${name}.mjs is missing from the submission`);
  return import(pathToFileURL(file).href);
}

function demand(condition, message) {
  if (!condition) throw new Error(message);
}
function demandEqual(actual, expected, message) {
  if (!isDeepStrictEqual(actual, expected)) {
    throw new Error(`${message}: expected ${clip(scrub(expected), 200)} but got ${clip(scrub(actual), 200)}`);
  }
}
async function requireThrows(fn, needle, message) {
  try {
    await fn();
  } catch (error) {
    const text = String(error?.message ?? error);
    demand(text.includes(needle), `${message}: it threw, but the message did not mention "${needle}": ${text}`);
    return text;
  }
  throw new Error(`${message}: nothing was thrown; the legacy record was accepted`);
}

function sortById(records) {
  return [...records].sort((a, b) => String(a?.id).localeCompare(String(b?.id)));
}

// ---------------------------------------------------------------- the checks
const BODIES = {
  async C1() {
    const store = await load('store');
    const notes = store.loadNotes(freshData());
    demand(Array.isArray(notes), 'loadNotes did not return an array');
    demand(notes.length === EXPECTED.length,
           `${notes.length} records came back from a file holding ${EXPECTED.length}; records were lost`);
    demandEqual(sortById(notes), EXPECTED, 'migrated records do not match the v2 contract');
    return `${notes.length} records migrated with ids ${notes.map((n) => n.id).join(', ')}`;
  },

  async C2() {
    const store = await load('store');
    const once = store.migrateRecord(V1_SAMPLE);
    const twice = store.migrateRecord(once);
    demandEqual(twice, once, 'migrateRecord is not idempotent on a single record');
    demandEqual(once, EXPECTED[0], 'migrateRecord produced a record that is not the specified v2 form');
    const file = freshData();
    store.saveNotes(file, store.loadNotes(file));
    const first = fs.readFileSync(file, 'utf8');
    store.saveNotes(file, store.loadNotes(file));
    const second = fs.readFileSync(file, 'utf8');
    demand(first === second, 'a second migration pass rewrote the saved file; it is not a no-op');
    return 'record-level and file-level migration are both idempotent';
  },

  async C3() {
    const store = await load('store');
    const file = freshData();
    const notes = store.loadNotes(file);
    const target = path.join(scratch, 'roundtrip.json');
    store.saveNotes(target, notes);
    const envelope = JSON.parse(fs.readFileSync(target, 'utf8'));
    demand(envelope.schemaVersion === 2, `saved envelope schemaVersion is ${envelope.schemaVersion}, expected 2`);
    demandEqual(store.loadNotes(target), notes, 'a save/load round trip changed the records');
    return 'round trip is lossless and the envelope is v2';
  },

  async C4() {
    const api = await load('api');
    const file = freshData();
    const created = api.createNote(file, {
      title: 'Fresh', body: 'new', tags: ['Tools', 'tools', 'bench'],
      createdAt: '2026-04-01T09:00:00.000Z', folder: 'Workshop',
    });
    demandEqual(created.tags, ['bench', 'tools'], 'createNote did not normalise tags to a v2 array');
    demand(created.createdAt === '2026-04-01T09:00:00.000Z',
           `createNote returned createdAt ${JSON.stringify(created.createdAt)}`);
    demand(!('created' in created), 'the created record still carries the v1 "created" key');
    demand(created.archived === false, 'createNote did not default the new required field archived to false');
    demand(created.schemaVersion === 2, 'createNote returned a record without schemaVersion 2');
    demandEqual(api.getNote(file, created.id), created, 'getNote did not return the persisted v2 record');
    const listed = api.listNotes(file);
    demand(listed.every((n) => n.schemaVersion === 2), 'listNotes returned records that are not v2');
    return `createNote/getNote/listNotes all return v2 records (${listed.length} on file)`;
  },

  async C5() {
    const exporter = await load('exporter');
    const csv = exporter.exportNotes(EXPECTED);
    const lines = csv.trim().split('\n');
    demand(lines[0] === 'id,title,tags,createdAt,folder,archived',
           `CSV header is ${JSON.stringify(lines[0])}`);
    demand(lines[1] === 'n-1,An unfinished thought,small;tools,2026-01-02T03:04:05.000Z,Workshop,false',
           `first CSV row is ${JSON.stringify(lines[1])}`);
    demand(lines.length === EXPECTED.length + 1, `CSV has ${lines.length - 1} rows, expected ${EXPECTED.length}`);
    return 'CSV export uses the v2 columns';
  },

  async C6() {
    const searchIndex = await load('searchIndex');
    const index = searchIndex.buildIndex(EXPECTED);
    demandEqual(searchIndex.search(index, 'garden'), ['n-2'], 'searching a tag did not find the note');
    demandEqual(searchIndex.search(index, 'tools'), ['n-1'], 'searching a v2 array tag did not find the note');
    demandEqual(searchIndex.search(index, 'winter'), ['n-5'], 'searching a second tag of a note failed');
    return 'the index is built from v2 tag arrays';
  },

  async C7() {
    const formatter = await load('formatter');
    const view = formatter.formatNote(EXPECTED[0]);
    demand(view.tagLine === 'small, tools', `tagLine is ${JSON.stringify(view.tagLine)}`);
    demand(view.dateLabel === '2026-01-02', `dateLabel is ${JSON.stringify(view.dateLabel)}`);
    demand(view.badge === '', `badge for an unarchived note is ${JSON.stringify(view.badge)}`);
    const archived = formatter.formatNote({ ...EXPECTED[0], archived: true });
    demand(archived.badge === 'Archived', `badge for an archived note is ${JSON.stringify(archived.badge)}`);
    return 'the formatter renders tags, timestamp and the archived badge from v2 fields';
  },

  async C8() {
    const api = await load('api');
    const exporter = await load('exporter');
    const searchIndex = await load('searchIndex');
    const formatter = await load('formatter');
    const store = await load('store');

    const file = freshData();
    const legacy = api.createNote(file, { title: 'Legacy post', body: 'from an old client',
                                          tags: 'Garden, tools', created: '2026-05-06 07:08:09',
                                          folder: 'Garden' });
    demandEqual(legacy.tags, ['garden', 'tools'], 'createNote did not migrate a legacy tags string');
    demand(legacy.createdAt === '2026-05-06T07:08:09.000Z',
           `createNote did not normalise the legacy timestamp: ${JSON.stringify(legacy.createdAt)}`);
    demand(legacy.schemaVersion === 2, 'a legacy-shaped post was not stored as a v2 record');

    await requireThrows(() => exporter.exportNotes([V1_SAMPLE]), 'schemaVersion',
                        'exportNotes must reject a v1 record');
    await requireThrows(() => searchIndex.buildIndex([V1_SAMPLE]), 'schemaVersion',
                        'buildIndex must reject a v1 record');
    await requireThrows(() => formatter.formatNote(V1_SAMPLE), 'schemaVersion',
                        'formatNote must reject a v1 record');

    const future = path.join(scratch, 'future.json');
    fs.writeFileSync(future, JSON.stringify({ schemaVersion: 3, notes: [] }));
    await requireThrows(() => store.loadNotes(future), 'schemaVersion',
                        'loadNotes must reject an envelope newer than v2');
    return 'legacy posts are accepted and migrated; the read-only consumers and a future envelope are rejected';
  },

  async C9() {
    const api = await load('api');
    const store = await load('store');
    const exporter = await load('exporter');
    const searchIndex = await load('searchIndex');
    const formatter = await load('formatter');

    const file = freshData();
    const created = api.createNote(file, { title: 'Bench notes', body: 'from the old client',
                                           tags: 'Bench, tools', created: '2026-06-07 08:09:10',
                                           folder: 'Workshop' });
    const onDisk = JSON.parse(fs.readFileSync(file, 'utf8'));
    demand(onDisk.schemaVersion === 2, `the persisted envelope is schemaVersion ${onDisk.schemaVersion}`);
    demand(onDisk.notes.length === EXPECTED.length + 1,
           `${onDisk.notes.length} records on disk after the post, expected ${EXPECTED.length + 1}`);

    const all = store.loadNotes(file);
    demand(all.every((n) => n.schemaVersion === 2), 'loadNotes returned records that are not v2');

    const csv = exporter.exportNotes(all);
    demand(csv.includes('bench;tools'), 'the exported CSV does not carry the new note\'s v2 tags');
    demand(csv.includes('2026-06-07T08:09:10.000Z'), 'the exported CSV does not carry the normalised timestamp');

    const found = searchIndex.search(searchIndex.buildIndex(all), 'bench');
    demandEqual(found, [created.id], 'the new note is not findable by its tag through the index');

    const view = formatter.formatNote(all.find((n) => n.id === created.id));
    demand(view.tagLine === 'bench, tools', `the formatter rendered tagLine ${JSON.stringify(view.tagLine)}`);
    demand(view.dateLabel === '2026-06-07', `the formatter rendered dateLabel ${JSON.stringify(view.dateLabel)}`);
    return `the legacy post ${created.id} crossed api, store, exporter, index and formatter intact`;
  },

  async C10() {
    const api = await load('api');
    const exporter = await load('exporter');
    const searchIndex = await load('searchIndex');
    const formatter = await load('formatter');

    const file = freshData();
    await requireThrows(() => api.createNote(file, { title: '   ' }), 'title',
                        'createNote must still reject a blank title');

    const index = searchIndex.buildIndex(EXPECTED);
    demandEqual(searchIndex.search(index, 'LAMP'), ['n-2'],
                'search no longer matches a case-insensitive title substring');
    demandEqual(searchIndex.search(index, ''), [], 'an empty query no longer returns nothing');

    const tricky = { ...EXPECTED[0], id: 'n-9', title: 'He said "hi", loudly' };
    const csv = exporter.exportNotes([tricky]);
    demand(csv.includes('"He said ""hi"", loudly"'),
           `CSV quoting regressed: ${JSON.stringify(csv.split('\n')[1] ?? '')}`);

    const view = formatter.formatNote({ ...EXPECTED[0], folder: null });
    demand(view.folderLabel === 'All notes', `folderLabel fallback regressed: ${JSON.stringify(view.folderLabel)}`);
    return 'title validation, search semantics, CSV quoting and the folder fallback are unchanged';
  },
};

// ---------------------------------------------------------------- run
async function main() {
  await nonceReady;
  harden();

  if (!CHECKS.some((c) => c.id === checkId)) {
    report({ type: 'error', message: `unknown check ${String(checkId)}` });
    return;
  }
  try {
    const evidence = await BODIES[checkId]();
    report({ type: 'result', id: checkId, status: 'pass',
             evidence: clip(scrub(evidence ?? 'ok')), tamper: [...new Set(TAMPER)] });
  } catch (error) {
    report({ type: 'result', id: checkId, status: 'fail',
             evidence: clip(scrub(error?.message ?? String(error))), tamper: [...new Set(TAMPER)] });
  }
}

main().catch((error) => {
  report({ type: 'result', id: checkId, status: 'fail',
           evidence: clip(scrub(`the check crashed: ${error?.message ?? error}`)),
           tamper: [...new Set(TAMPER)] });
});
