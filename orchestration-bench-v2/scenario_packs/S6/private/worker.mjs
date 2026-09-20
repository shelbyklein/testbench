// S6 grading worker.  Spawned by grade.mjs as: node worker.mjs <workdir> <scratch> <checkId>
//
// THIS is the process that imports the candidate's modules. It never learns the report path:
// its argv holds only a private temporary directory, and its environment is narrowed by the
// supervisor. It offers exactly one result for exactly one check over an IPC message
// authenticated with a per-run nonce, and the supervisor decides what that is worth.
//
// One worker per check, so a module-level side effect in the candidate cannot poison a later
// check and an early exit costs only the check that was running.
//
// The fault wrapper lives here, unchanged in behaviour. It injects exactly three things — a
// transient failure on a named key, a permanent failure on a named key, and a simulated
// process kill — and the kill is scheduled on a SEMANTIC MILESTONE ('first_persisted_ack':
// the outbox file on disk durably holds its first entry), never after N calls.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { isDeepStrictEqual } from 'node:util';

import { CHECKS, MILESTONE } from './checks.mjs';

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

// Ground truth for the shipped saved records: four unarchived notes, one archived.
const PENDING_KEYS = ['note:n-1@3', 'note:n-2@1', 'note:n-3@7', 'note:n-5@1'];
const ARCHIVED_KEY = 'note:n-4@2';

const NOTES_SOURCE = fs.readFileSync(path.join(workdir, 'data', 'notes.json'), 'utf8');

let counter = 0;
function freshDir() {
  const dir = path.join(scratch, `run-${counter++}`);
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(path.join(dir, 'notes.json'), NOTES_SOURCE);
  return dir;
}

async function load(name) {
  const file = path.join(workdir, 'src', `${name}.mjs`);
  if (!fs.existsSync(file)) throw new Error(`src/${name}.mjs is missing from the submission`);
  return import(pathToFileURL(file).href);
}

// -- the world outside the process ------------------------------------------------
// It survives a simulated kill, because the outside world does not care that Fieldnotes
// died. One delivery ledger is shared by every transport handed to the same scenario.
class World {
  constructor() {
    this.deliveries = [];      // every accepted external effect, in order
    this.attempts = [];        // every send attempt, accepted or not
    this.lookups = [];         // every `delivered(key)` question
    this.outboxSizes = [];     // the outbox line count, sampled on every transport call
    this.killed = null;        // {milestone, outboxEntriesAtKill, outboxBytesAtKill}
  }

  count(key) {
    return this.deliveries.filter((k) => k === key).length;
  }

  duplicates() {
    return [...new Set(this.deliveries.filter((k) => this.count(k) > 1))].sort();
  }

  /** A restart: a fresh process, but the outside world and the ledger it saw remain. */
  resume() {
    const next = new World();
    next.deliveries = [...this.deliveries];
    next.outboxSizes = [...this.outboxSizes];
    return next;
  }

  /** The outbox never shrank between two observations. Truncation is data loss. */
  shrank() {
    for (let i = 1; i < this.outboxSizes.length; i += 1) {
      if (this.outboxSizes[i] < this.outboxSizes[i - 1]) {
        return `the outbox dropped from ${this.outboxSizes[i - 1]} to ${this.outboxSizes[i]} entries`;
      }
    }
    return null;
  }
}

class KillSignal extends Error {
  constructor(milestone) {
    super(`the Fieldnotes process was killed at the semantic milestone ${milestone}`);
    this.name = 'KillSignal';
    this.fatal = true;       // the contract: a fatal error must propagate
    this.milestone = milestone;
  }
}

function outboxLines(dir) {
  const file = path.join(dir, 'outbox.jsonl');
  if (!fs.existsSync(file)) return [];
  return fs.readFileSync(file, 'utf8').split('\n').filter((line) => line.trim());
}

/**
 * The fault wrapper.
 *
 *   transientOn  keys whose FIRST send attempt rejects with `transient: true`
 *   permanentOn  keys whose every send attempt rejects with an ordinary error
 *   killOn       'milestone'          kill when the outbox durably holds its first entry
 *                'after-effect:<key>' kill in the gap between the accepted effect and
 *                                     the candidate's record of it
 */
function transport(world, dir, { transientOn = [], permanentOn = [], killOn = null } = {}) {
  const transient = new Set(transientOn);
  const permanent = new Set(permanentOn);
  const seen = new Map();

  const killNow = (reason) => {
    world.killed = world.killed ?? {
      milestone: MILESTONE,
      reason,
      outboxEntriesAtKill: outboxLines(dir).length,
      outboxBytesAtKill: outboxLines(dir).join('\n'),
      deliveriesAtKill: [...world.deliveries],
    };
    throw new KillSignal(MILESTONE);
  };

  return {
    async send({ key, note }) {
      world.attempts.push(key);
      world.outboxSizes.push(outboxLines(dir).length);
      if (world.killed) killNow('a killed process cannot send');

      // SEMANTIC milestone: the first acknowledged persisted operation is on disk.
      if (killOn === 'milestone' && outboxLines(dir).length >= 1) {
        killNow('the outbox durably holds its first acknowledged operation');
      }

      const attempts = (seen.get(key) ?? 0) + 1;
      seen.set(key, attempts);
      if (permanent.has(key)) {
        throw new Error(`the outbox refused ${key}`);
      }
      if (transient.has(key) && attempts === 1) {
        const error = new Error(`the outbox hiccuped on ${key}`);
        error.transient = true;
        throw error;
      }

      world.deliveries.push(key);
      if (killOn === `after-effect:${key}`) {
        killNow(`the effect for ${key} was accepted and the process died before recording it`);
      }
      return { receipt: `outbox:${key}` };
    },

    async delivered(key) {
      world.lookups.push(key);
      world.outboxSizes.push(outboxLines(dir).length);
      return world.deliveries.includes(key);
    },
  };
}

// -- check plumbing ---------------------------------------------------------------
function demand(condition, message) {
  if (!condition) throw new Error(message);
}
function demandEqual(actual, expected, message) {
  if (!isDeepStrictEqual(actual, expected)) {
    throw new Error(`${message}: expected ${clip(scrub(expected), 200)} but got ${clip(scrub(actual), 200)}`);
  }
}

/** Run the job and report how it ended, without ever swallowing a real defect. */
async function runJob(sync, options) {
  try {
    return { outcome: 'returned', summary: await sync.publishPending(options) };
  } catch (error) {
    if (error instanceof KillSignal || error?.name === 'KillSignal') {
      return { outcome: 'killed', error };
    }
    throw error;
  }
}

async function outboxKeys(outbox, dir) {
  const entries = outbox.readOutbox(dir);
  demand(Array.isArray(entries), 'readOutbox did not return an array');
  for (const entry of entries) {
    demand(entry && typeof entry.key === 'string',
           `an outbox entry has no key: ${clip(scrub(entry), 120)}`);
  }
  return entries.map((entry) => entry.key);
}

function notesUnchanged(dir, where) {
  const now = fs.readFileSync(path.join(dir, 'notes.json'), 'utf8');
  demand(now === NOTES_SOURCE, `the saved records were modified ${where}; the job must not write notes.json`);
}

function noDuplicateEffects(world, keys, where) {
  const dupes = world.duplicates();
  demand(dupes.length === 0,
         `an externally visible effect was duplicated ${where}: ${dupes.join(', ')} was sent twice`);
  const counted = keys.filter((k, i) => keys.indexOf(k) !== i);
  demand(counted.length === 0,
         `the outbox holds more than one entry for ${[...new Set(counted)].join(', ')} ${where}`);
}

// -- the checks -------------------------------------------------------------------
const BODIES = {
  async R1() {
    const sync = await load('sync');
    const outbox = await load('outbox');
    const dir = freshDir();
    const world = new World();
    const { outcome, summary } = await runJob(sync, { dir, transport: transport(world, dir) });
    demand(outcome === 'returned', 'the job did not return a summary');
    demand(summary.complete === true, `the summary reports complete=${summary.complete} after a clean run`);
    demandEqual([...summary.keys].sort(), PENDING_KEYS, 'the published keys are wrong');
    demand(summary.published === 4, `published=${summary.published}, expected 4`);
    demand(summary.failed === 0, `failed=${summary.failed} on a clean run`);
    const keys = await outboxKeys(outbox, dir);
    demandEqual([...keys].sort(), PENDING_KEYS, 'the outbox does not hold one entry per unarchived note');
    demand(!world.deliveries.includes(ARCHIVED_KEY), 'the archived note was published');
    noDuplicateEffects(world, keys, 'on a clean run');
    notesUnchanged(dir, 'by a clean run');
    return `4 notes published once each, outbox ${keys.length} entries, archived note skipped`;
  },

  async R2() {
    const sync = await load('sync');
    const outbox = await load('outbox');
    const dir = freshDir();
    const first = new World();
    await runJob(sync, { dir, transport: transport(first, dir) });
    const before = outboxLines(dir).join('\n');

    const second = new World();  // a fresh process, a fresh transport, the same directory
    const { outcome, summary } = await runJob(sync, { dir, transport: transport(second, dir) });
    demand(outcome === 'returned', 'the second run did not return a summary');
    demand(second.attempts.length === 0,
           `the re-run sent ${second.attempts.length} effect(s) again: ${[...new Set(second.attempts)].join(', ')}`);
    demand(summary.alreadyPublished === 4,
           `alreadyPublished=${summary.alreadyPublished}, expected 4; progress did not survive the process`);
    demand(summary.published === 0, `the re-run reports published=${summary.published}, expected 0`);
    demand(summary.complete === true, 'the re-run does not report a complete result');
    demand(outboxLines(dir).join('\n') === before, 'the re-run changed the outbox file');
    demandEqual([...(await outboxKeys(outbox, dir))].sort(), PENDING_KEYS, 'the outbox changed across the re-run');
    return 'a second run over a finished directory sends nothing and rewrites nothing';
  },

  async R3() {
    const sync = await load('sync');
    const outbox = await load('outbox');
    const dir = freshDir();
    const world = new World();
    const hiccup = 'note:n-2@1';
    const { outcome, summary } = await runJob(sync, {
      dir, transport: transport(world, dir, { transientOn: [hiccup] }) });
    demand(outcome === 'returned', 'the job did not return a summary');
    demand(summary.failed === 0,
           `the transient hiccup was reported as a failure: ${clip(scrub(summary.failures), 200)}`);
    demand(summary.complete === true, `complete=${summary.complete} after a retryable hiccup`);
    demand(world.attempts.filter((k) => k === hiccup).length >= 2,
           `${hiccup} was never retried after its transient failure`);
    demand(world.count(hiccup) === 1,
           `${hiccup} produced ${world.count(hiccup)} external effects; the retry duplicated it`);
    const keys = await outboxKeys(outbox, dir);
    demandEqual([...keys].sort(), PENDING_KEYS, 'the outbox is wrong after a retried hiccup');
    noDuplicateEffects(world, keys, 'after a retried hiccup');
    return `${hiccup} was retried and delivered once; all 4 notes published`;
  },

  async R4() {
    const sync = await load('sync');
    const outbox = await load('outbox');
    const dir = freshDir();
    const world = new World();
    const broken = 'note:n-3@7';
    const { outcome, summary } = await runJob(sync, {
      dir, transport: transport(world, dir, { permanentOn: [broken] }) });
    demand(outcome === 'returned', 'the job did not return a summary');
    demand(summary.failed === 1,
           `failed=${summary.failed}, expected 1; a missing effect was reported as done`);
    demand(summary.complete === false, 'complete=true although one note was never published');
    demand(JSON.stringify(summary.failures ?? []).includes(broken),
           `the failures list does not name ${broken}: ${clip(scrub(summary.failures), 200)}`);
    demand(!summary.keys.includes(broken), `${broken} is listed as published although it never was`);
    const keys = await outboxKeys(outbox, dir);
    demand(!keys.includes(broken), `the outbox claims ${broken} was published; no effect ever reached the transport`);
    demandEqual([...keys].sort(), PENDING_KEYS.filter((k) => k !== broken),
                'the other three notes were not published around the failure');

    // The failure is recoverable: a later run with a working transport finishes the job.
    const later = new World();
    const { summary: repaired } = await runJob(sync, { dir, transport: transport(later, dir) });
    demand(repaired.complete === true, 'a later run did not finish the note that had failed');
    demandEqual([...repaired.keys].sort(), PENDING_KEYS, 'the repaired run did not publish every note');
    demandEqual(later.deliveries, [broken],
                `the repair run sent ${later.deliveries.length} effects, expected only ${broken}`);
    return `${broken} failed loudly, the other three were published, and a later run finished it`;
  },

  async R5() {
    const sync = await load('sync');
    const outbox = await load('outbox');
    const dir = freshDir();
    const world = new World();
    const killed = await runJob(sync, {
      dir, transport: transport(world, dir, { killOn: 'milestone' }) });
    demand(world.killed, 'the milestone was never reached: no operation was ever durably acknowledged');
    demand(world.killed.outboxEntriesAtKill === 1,
           `the kill fired with ${world.killed.outboxEntriesAtKill} outbox entries; the milestone is the FIRST one`);
    demand(killed.outcome === 'killed',
           'the simulated process kill was caught and ignored; the run continued after the process died');

    const after = world.resume();   // the outside world remembers; the process does not
    const { outcome, summary } = await runJob(sync, { dir, transport: transport(after, dir) });
    demand(outcome === 'returned', 'the restart did not return a summary');
    demand(summary.complete === true, `the restart reports complete=${summary.complete}`);
    demandEqual([...summary.keys].sort(), PENDING_KEYS, 'the restart did not finish every note');
    const keys = await outboxKeys(outbox, dir);
    demandEqual([...keys].sort(), PENDING_KEYS, 'the outbox is wrong after the restart');
    noDuplicateEffects(after, keys, 'across the crash and restart');
    for (const key of PENDING_KEYS) {
      demand(after.count(key) === 1, `${key} reached the transport ${after.count(key)} times in total`);
    }
    return `killed at ${MILESTONE} with 1 acknowledged operation; the restart published the remaining 3, one effect per key`;
  },

  async R6() {
    const sync = await load('sync');
    const outbox = await load('outbox');
    const dir = freshDir();
    const world = new World();
    await runJob(sync, { dir, transport: transport(world, dir, { killOn: 'milestone' }) });
    demand(world.killed, 'the milestone was never reached: no operation was ever durably acknowledged');
    notesUnchanged(dir, 'before the restart');

    const before = world.killed.outboxBytesAtKill;
    const after = world.resume();
    await runJob(sync, { dir, transport: transport(after, dir) });
    notesUnchanged(dir, 'by the restart');

    after.outboxSizes.push(outboxLines(dir).length);
    demand(after.shrank() === null, `the outbox lost entries across the restart: ${after.shrank()}`);
    const now = outboxLines(dir).join('\n');
    demand(now.startsWith(before),
           'the outbox written before the crash is not a prefix of the outbox after it; earlier entries were lost or rewritten');
    const keys = await outboxKeys(outbox, dir);
    for (const key of PENDING_KEYS) {
      demand(keys.includes(key), `${key} is missing from the outbox after the restart`);
    }
    const notes = (await load('store')).loadNotes(path.join(dir, 'notes.json'));
    demand(notes.length === 5, `${notes.length} saved records survived, expected 5`);
    return 'notes.json is byte-identical, the pre-crash outbox bytes are an unchanged prefix, all 5 records survive';
  },

  async R7() {
    const sync = await load('sync');
    const outbox = await load('outbox');
    const dir = freshDir();
    const first = PENDING_KEYS[0];
    const world = new World();
    const killed = await runJob(sync, {
      dir, transport: transport(world, dir, { killOn: `after-effect:${first}` }) });
    demand(world.deliveries.includes(first), `${first} never reached the transport before the crash`);
    demand(killed.outcome === 'killed',
           'the simulated process kill was caught and ignored; the run continued after the process died');

    const after = world.resume();   // the effect happened; only the record is missing
    const { outcome, summary } = await runJob(sync, { dir, transport: transport(after, dir) });
    demand(outcome === 'returned', 'the restart did not return a summary');
    demand(after.lookups.includes(first),
           `the restart never asked the transport whether ${first} had been delivered; it guessed`);
    demand(after.count(first) === 1,
           `${first} reached the transport ${after.count(first)} times: the accepted effect was sent again`);
    demand(summary.complete === true, `the restart reports complete=${summary.complete}`);
    const keys = await outboxKeys(outbox, dir);
    demandEqual([...keys].sort(), PENDING_KEYS, 'the outbox is wrong after reconciliation');
    noDuplicateEffects(after, keys, 'after a crash between the effect and its record');
    return `${first} was accepted, the record was lost, and the restart reconciled it without a second effect`;
  },

  async R8() {
    const sync = await load('sync');
    const dir = freshDir();
    const world = new World();
    await runJob(sync, { dir, transport: transport(world, dir, { killOn: 'milestone' }) });
    demand(world.killed, 'the milestone was never reached: no operation was ever durably acknowledged');
    const done = [...world.deliveries];
    demand(done.length === 1, `${done.length} effects were accepted before the milestone kill, expected 1`);

    const after = world.resume();
    await runJob(sync, { dir, transport: transport(after, dir) });
    const resent = after.attempts.filter((key) => done.includes(key));
    demand(resent.length === 0,
           `the restart re-sent already-finished work: ${[...new Set(resent)].join(', ')}`);
    const expected = PENDING_KEYS.filter((key) => !done.includes(key));
    demandEqual([...new Set(after.attempts)].sort(), expected,
                'the restart did not send exactly the outstanding notes');
    return `the restart sent only ${expected.join(', ')} and left ${done.join(', ')} alone`;
  },

  async R9() {
    const sync = await load('sync');
    const outbox = await load('outbox');
    const dir = freshDir();
    const world = new World();
    await runJob(sync, { dir, transport: transport(world, dir, { killOn: 'milestone' }) });
    demand(world.killed, 'the milestone was never reached: no operation was ever durably acknowledged');
    const before = outboxLines(dir);

    const after = world.resume();
    await runJob(sync, { dir, transport: transport(after, dir) });
    const now = outboxLines(dir);
    after.outboxSizes.push(now.length);
    demand(after.shrank() === null,
           `the outbox was truncated or rewritten during the run: ${after.shrank()}`);
    demand(now.length >= before.length,
           `the outbox shrank from ${before.length} to ${now.length} lines; it was truncated or rewritten`);
    demandEqual(now.slice(0, before.length), before,
                'the outbox lines written before the restart were rewritten or reordered');
    const keys = await outboxKeys(outbox, dir);
    demandEqual([...new Set(keys)].sort(), [...keys].sort(),
                `the outbox holds more than one entry for some key: ${keys.join(', ')}`);
    demand(!now.join('\n').match(/20\d\d-\d\d-\d\dT/),
           'the outbox carries a wall-clock timestamp; two identical runs would not be identical');
    return `${before.length} line(s) before the restart are an unchanged prefix of ${now.length}, keys unique`;
  },

  async R10() {
    const sync = await load('sync');
    const store = await load('store');
    const dir = freshDir();

    demand(sync.idempotencyKey({ id: 'n-9', revision: 4 }) === 'note:n-9@4',
           `idempotencyKey returned ${JSON.stringify(sync.idempotencyKey({ id: 'n-9', revision: 4 }))}`);
    demand(sync.idempotencyKey({ id: 'n-9', revision: 5 }) !== sync.idempotencyKey({ id: 'n-9', revision: 4 }),
           'the idempotency key no longer changes with the note revision');
    let threw = false;
    try { sync.idempotencyKey({ revision: 1 }); } catch { threw = true; }
    demand(threw, 'a note without an id is no longer rejected');

    const notes = store.loadNotes(path.join(dir, 'notes.json'));
    const pending = sync.pendingNotes(notes);
    demandEqual(pending.map((n) => n.id), ['n-1', 'n-2', 'n-3', 'n-5'],
                'pendingNotes no longer skips archived notes in a stable order');

    const target = path.join(dir, 'roundtrip.json');
    store.saveNotes(target, notes);
    demandEqual(store.loadNotes(target), notes, 'a save/load round trip changed the saved records');
    return 'key stability, id validation, archived skipping and the store round trip are unchanged';
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
