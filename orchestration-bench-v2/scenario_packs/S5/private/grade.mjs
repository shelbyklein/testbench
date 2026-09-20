// S5 shared-contract migration grader.  CLI: node grade.mjs <candidate_dir> <output.json>
//
// Deterministic and offline. The candidate directory is never written to: it is copied into a
// fresh temporary directory, and every check that persists anything works on that copy or on a
// per-check copy of the saved records. Temporary paths and the candidate path are scrubbed out
// of the evidence.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { isDeepStrictEqual } from 'node:util';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const [candidateArg, outArg] = process.argv.slice(2);
if (!candidateArg || !outArg) {
  console.error('usage: node grade.mjs <candidate_dir> <output.json>');
  process.exit(2);
}
const candidate = path.resolve(candidateArg);
const workdir = fs.mkdtempSync(path.join(os.tmpdir(), 'ob2-s5-'));

const scrub = (value) => {
  const text = typeof value === 'string' ? value : (JSON.stringify(value) ?? String(value));
  return text.split(candidate).join('<submission>')
             .split(workdir).join('<workdir>')
             .split(os.tmpdir()).join('<tmp>')
             .split(HERE).join('<grader>');
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

fs.cpSync(candidate, workdir, {
  recursive: true,
  filter: (src) => !/(^|[\\/])(\.git|node_modules)$/.test(src),
});
let counter = 0;
function freshData() {
  const file = path.join(workdir, `notes-copy-${counter++}.json`);
  fs.copyFileSync(path.join(candidate, 'data', 'notes.json'), file);
  return file;
}

async function load(name) {
  const file = path.join(workdir, 'src', `${name}.mjs`);
  if (!fs.existsSync(file)) throw new Error(`src/${name}.mjs is missing from the submission`);
  return import(pathToFileURL(file).href);
}

const checks = [];
async function check(id, description, body) {
  try {
    const evidence = await body();
    checks.push({ id, description, status: 'pass', evidence: clip(scrub(evidence ?? 'ok')) });
  } catch (error) {
    checks.push({ id, description, status: 'fail', evidence: clip(scrub(error?.message ?? String(error))) });
  }
}

function require(condition, message) {
  if (!condition) throw new Error(message);
}
function requireEqual(actual, expected, message) {
  if (!isDeepStrictEqual(actual, expected)) {
    throw new Error(`${message}: expected ${clip(scrub(expected), 200)} but got ${clip(scrub(actual), 200)}`);
  }
}
async function requireThrows(fn, needle, message) {
  try {
    await fn();
  } catch (error) {
    const text = String(error?.message ?? error);
    require(text.includes(needle), `${message}: it threw, but the message did not mention "${needle}": ${text}`);
    return text;
  }
  throw new Error(`${message}: nothing was thrown; the legacy record was accepted`);
}

function sortById(records) {
  return [...records].sort((a, b) => String(a?.id).localeCompare(String(b?.id)));
}

async function main() {
  await check('C1', 'Saved records survive the migration: every field of every stored note is preserved', async () => {
    const store = await load('store');
    const notes = store.loadNotes(freshData());
    require(Array.isArray(notes), 'loadNotes did not return an array');
    require(notes.length === EXPECTED.length,
            `${notes.length} records came back from a file holding ${EXPECTED.length}; records were lost`);
    requireEqual(sortById(notes), EXPECTED, 'migrated records do not match the v2 contract');
    return `${notes.length} records migrated with ids ${notes.map((n) => n.id).join(', ')}`;
  });

  await check('C2', 'Migration is idempotent: migrating an already-migrated record or file is a no-op', async () => {
    const store = await load('store');
    const once = store.migrateRecord(V1_SAMPLE);
    const twice = store.migrateRecord(once);
    requireEqual(twice, once, 'migrateRecord is not idempotent on a single record');
    requireEqual(once, EXPECTED[0], 'migrateRecord produced a record that is not the specified v2 form');
    const file = freshData();
    store.saveNotes(file, store.loadNotes(file));
    const first = fs.readFileSync(file, 'utf8');
    store.saveNotes(file, store.loadNotes(file));
    const second = fs.readFileSync(file, 'utf8');
    require(first === second, 'a second migration pass rewrote the saved file; it is not a no-op');
    return 'record-level and file-level migration are both idempotent';
  });

  await check('C3', 'Serialization round trip: saveNotes then loadNotes returns the same records in the v2 envelope', async () => {
    const store = await load('store');
    const file = freshData();
    const notes = store.loadNotes(file);
    const target = path.join(workdir, 'roundtrip.json');
    store.saveNotes(target, notes);
    const envelope = JSON.parse(fs.readFileSync(target, 'utf8'));
    require(envelope.schemaVersion === 2, `saved envelope schemaVersion is ${envelope.schemaVersion}, expected 2`);
    requireEqual(store.loadNotes(target), notes, 'a save/load round trip changed the records');
    return 'round trip is lossless and the envelope is v2';
  });

  await check('C4', 'API consumer speaks v2: created and read records carry the new contract', async () => {
    const api = await load('api');
    const file = freshData();
    const created = api.createNote(file, {
      title: 'Fresh', body: 'new', tags: ['Tools', 'tools', 'bench'],
      createdAt: '2026-04-01T09:00:00.000Z', folder: 'Workshop',
    });
    requireEqual(created.tags, ['bench', 'tools'], 'createNote did not normalise tags to a v2 array');
    require(created.createdAt === '2026-04-01T09:00:00.000Z',
            `createNote returned createdAt ${JSON.stringify(created.createdAt)}`);
    require(!('created' in created), 'the created record still carries the v1 "created" key');
    require(created.archived === false, 'createNote did not default the new required field archived to false');
    require(created.schemaVersion === 2, 'createNote returned a record without schemaVersion 2');
    requireEqual(api.getNote(file, created.id), created, 'getNote did not return the persisted v2 record');
    const listed = api.listNotes(file);
    require(listed.every((n) => n.schemaVersion === 2), 'listNotes returned records that are not v2');
    return `createNote/getNote/listNotes all return v2 records (${listed.length} on file)`;
  });

  await check('C5', 'Exporter consumer speaks v2: CSV carries the new columns and values', async () => {
    const exporter = await load('exporter');
    const csv = exporter.exportNotes(EXPECTED);
    const lines = csv.trim().split('\n');
    require(lines[0] === 'id,title,tags,createdAt,folder,archived',
            `CSV header is ${JSON.stringify(lines[0])}`);
    require(lines[1] === 'n-1,An unfinished thought,small;tools,2026-01-02T03:04:05.000Z,Workshop,false',
            `first CSV row is ${JSON.stringify(lines[1])}`);
    require(lines.length === EXPECTED.length + 1, `CSV has ${lines.length - 1} rows, expected ${EXPECTED.length}`);
    return 'CSV export uses the v2 columns';
  });

  await check('C6', 'Search index consumer speaks v2: it indexes array tags', async () => {
    const searchIndex = await load('searchIndex');
    const index = searchIndex.buildIndex(EXPECTED);
    requireEqual(searchIndex.search(index, 'garden'), ['n-2'], 'searching a tag did not find the note');
    requireEqual(searchIndex.search(index, 'tools'), ['n-1'], 'searching a v2 array tag did not find the note');
    requireEqual(searchIndex.search(index, 'winter'), ['n-5'], 'searching a second tag of a note failed');
    return 'the index is built from v2 tag arrays';
  });

  await check('C7', 'Formatter consumer speaks v2: display strings come from the new fields', async () => {
    const formatter = await load('formatter');
    const view = formatter.formatNote(EXPECTED[0]);
    require(view.tagLine === 'small, tools', `tagLine is ${JSON.stringify(view.tagLine)}`);
    require(view.dateLabel === '2026-01-02', `dateLabel is ${JSON.stringify(view.dateLabel)}`);
    require(view.badge === '', `badge for an unarchived note is ${JSON.stringify(view.badge)}`);
    const archived = formatter.formatNote({ ...EXPECTED[0], archived: true });
    require(archived.badge === 'Archived', `badge for an archived note is ${JSON.stringify(archived.badge)}`);
    return 'the formatter renders tags, timestamp and the archived badge from v2 fields';
  });

  await check('C8', 'Compatibility matrix: legacy input is accepted where specified and rejected where specified', async () => {
    const api = await load('api');
    const exporter = await load('exporter');
    const searchIndex = await load('searchIndex');
    const formatter = await load('formatter');
    const store = await load('store');

    const file = freshData();
    const legacy = api.createNote(file, { title: 'Legacy post', body: 'from an old client',
                                          tags: 'Garden, tools', created: '2026-05-06 07:08:09',
                                          folder: 'Garden' });
    requireEqual(legacy.tags, ['garden', 'tools'], 'createNote did not migrate a legacy tags string');
    require(legacy.createdAt === '2026-05-06T07:08:09.000Z',
            `createNote did not normalise the legacy timestamp: ${JSON.stringify(legacy.createdAt)}`);
    require(legacy.schemaVersion === 2, 'a legacy-shaped post was not stored as a v2 record');

    await requireThrows(() => exporter.exportNotes([V1_SAMPLE]), 'schemaVersion',
                        'exportNotes must reject a v1 record');
    await requireThrows(() => searchIndex.buildIndex([V1_SAMPLE]), 'schemaVersion',
                        'buildIndex must reject a v1 record');
    await requireThrows(() => formatter.formatNote(V1_SAMPLE), 'schemaVersion',
                        'formatNote must reject a v1 record');

    const future = path.join(workdir, 'future.json');
    fs.writeFileSync(future, JSON.stringify({ schemaVersion: 3, notes: [] }));
    await requireThrows(() => store.loadNotes(future), 'schemaVersion',
                        'loadNotes must reject an envelope newer than v2');
    return 'legacy posts are accepted and migrated; the read-only consumers and a future envelope are rejected';
  });

  await check('C9', 'Integrated flow: a legacy post crosses persistence and all four consumers', async () => {
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
    require(onDisk.schemaVersion === 2, `the persisted envelope is schemaVersion ${onDisk.schemaVersion}`);
    require(onDisk.notes.length === EXPECTED.length + 1,
            `${onDisk.notes.length} records on disk after the post, expected ${EXPECTED.length + 1}`);

    const all = store.loadNotes(file);
    require(all.every((n) => n.schemaVersion === 2), 'loadNotes returned records that are not v2');

    const csv = exporter.exportNotes(all);
    require(csv.includes('bench;tools'), 'the exported CSV does not carry the new note\'s v2 tags');
    require(csv.includes('2026-06-07T08:09:10.000Z'), 'the exported CSV does not carry the normalised timestamp');

    const found = searchIndex.search(searchIndex.buildIndex(all), 'bench');
    requireEqual(found, [created.id], 'the new note is not findable by its tag through the index');

    const view = formatter.formatNote(all.find((n) => n.id === created.id));
    require(view.tagLine === 'bench, tools', `the formatter rendered tagLine ${JSON.stringify(view.tagLine)}`);
    require(view.dateLabel === '2026-06-07', `the formatter rendered dateLabel ${JSON.stringify(view.dateLabel)}`);
    return `the legacy post ${created.id} crossed api, store, exporter, index and formatter intact`;
  });

  await check('C10', 'No regression of pre-existing behavior', async () => {
    const api = await load('api');
    const exporter = await load('exporter');
    const searchIndex = await load('searchIndex');
    const formatter = await load('formatter');

    const file = freshData();
    await requireThrows(() => api.createNote(file, { title: '   ' }), 'title',
                        'createNote must still reject a blank title');

    const index = searchIndex.buildIndex(EXPECTED);
    requireEqual(searchIndex.search(index, 'LAMP'), ['n-2'],
                 'search no longer matches a case-insensitive title substring');
    requireEqual(searchIndex.search(index, ''), [], 'an empty query no longer returns nothing');

    const tricky = { ...EXPECTED[0], id: 'n-9', title: 'He said "hi", loudly' };
    const csv = exporter.exportNotes([tricky]);
    require(csv.includes('"He said ""hi"", loudly"'),
            `CSV quoting regressed: ${JSON.stringify(csv.split('\n')[1] ?? '')}`);

    const view = formatter.formatNote({ ...EXPECTED[0], folder: null });
    require(view.folderLabel === 'All notes', `folderLabel fallback regressed: ${JSON.stringify(view.folderLabel)}`);
    return 'title validation, search semantics, CSV quoting and the folder fallback are unchanged';
  });

  const passed = checks.filter((c) => c.status === 'pass').length;
  const report = {
    checks,
    passed,
    total: checks.length,
    allPassed: passed === checks.length,
    details: {
      expectedRecordCount: EXPECTED.length,
      consumerChecks: { api: 'C4', exporter: 'C5', searchIndex: 'C6', formatter: 'C7' },
      failed: checks.filter((c) => c.status !== 'pass').map((c) => c.id),
    },
  };
  fs.writeFileSync(outArg, `${JSON.stringify(report, null, 2)}\n`);
  fs.rmSync(workdir, { recursive: true, force: true });
  process.exit(report.allPassed ? 0 : 1);
}

main().catch((error) => {
  console.error(scrub(`${error?.stack ?? error}`));
  fs.rmSync(workdir, { recursive: true, force: true });
  process.exit(2);
});
