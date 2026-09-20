// S4 reproduction worker.  Spawned by grade.mjs as: node repro-worker.mjs <scratch> <reprosFile>
//
// The supervisor never executes a reproduction. This worker does, and it is the only process
// that imports anything: the twelve FROZEN modules shipped with this pack, and nothing else.
// It is not told where the report goes — its argv holds only a private temporary directory and
// the JSON file of already-validated reproductions — and every outcome it offers is
// authenticated with a per-run nonce delivered over IPC before any of that work begins.
//
// Order matters here. The export manifest is built by importing the allow-listed frozen
// modules FIRST, before a single submission-controlled name is looked at. No string from a
// submission is ever turned into a module path (review finding F2): the supervisor has already
// checked the module name against the directory listing and verified containment, and this
// worker checks the export against the manifest of what the module really exports.
//
// Residual risk, stated plainly: this is defence against report forgery and early-exit tricks,
// not a sandbox. The code executed here is the pack's own frozen modules, but it is executed
// with submission-supplied arguments, and the worker runs with the user's OS permissions.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { isDeepStrictEqual } from 'node:util';

// ---------------------------------------------------------------- worker harness
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

function send(payload) {
  if (!RAW_SEND || NONCE === null) return;
  try { RAW_SEND({ __nonce: NONCE, ...payload }); } catch { /* the channel is gone */ }
}

function finish() {
  try { RAW_DISCONNECT?.(); } catch { /* already disconnected */ }
  const backstop = setTimeout(() => RAW_EXIT(0), 2000);
  backstop.unref?.();
}

const TAMPER = [];
function harden() {
  try {
    process.send = (message) => {
      TAMPER.push('the submission influenced a call to process.send during grading');
      try { RAW_SEND?.({ __unauthenticated: true, message: String(message && message.type) }); } catch { /* gone */ }
      return false;
    };
  } catch { /* non-writable is fine */ }
  try {
    process.exit = (code) => {
      TAMPER.push(`process.exit(${code === undefined ? '' : code}) was called during grading`);
      throw new Error(`process.exit(${code === undefined ? '' : code}) was called during grading`);
    };
  } catch { /* non-writable is fine */ }
  try { process.removeAllListeners('message'); } catch { /* nothing attached */ }
  try { Object.freeze(JSON); } catch { /* already frozen */ }
}

// ---------------------------------------------------------------- setup
const HERE = path.dirname(fileURLToPath(import.meta.url));
const MODULES = path.join(HERE, '..', 'participant', 'src');
const [scratchArg, reprosArg] = process.argv.slice(2);
const scratch = path.resolve(scratchArg ?? '');

const scrub = (value) => {
  const text = typeof value === 'string' ? value : (JSON.stringify(value) ?? String(value));
  return text.split(scratch).join('<scratch>')
             .split(HERE).join('<grader>')
             .split(os.tmpdir()).join('<tmp>');
};
const clip = (text, limit = 400) => (text.length > limit ? `${text.slice(0, limit)}…` : text);

function invoke(fn, args) {
  try {
    return { ok: true, value: fn(...args) };
  } catch (error) {
    return { ok: false, thrown: `${error?.name ?? 'Error'}: ${error?.message ?? error}` };
  }
}

function sameOutcome(a, b) {
  if (a.ok !== b.ok) return false;
  return a.ok ? isDeepStrictEqual(a.value, b.value) : a.thrown === b.thrown;
}

// ---------------------------------------------------------------- run
async function main() {
  await nonceReady;
  harden();

  // The frozen modules, by their real names on disk. Nothing from the submission takes part
  // in building this map, and no other path is ever imported.
  const names = fs.readdirSync(MODULES).filter((n) => n.endsWith('.mjs')).map((n) => n.slice(0, -4)).sort();
  const modules = new Map();
  for (const name of names) {
    const file = path.join(MODULES, `${name}.mjs`);
    if (path.dirname(path.resolve(file)) !== path.resolve(MODULES)) continue;   // belt and braces
    modules.set(name, await import(pathToFileURL(file).href));
  }
  const { oracleFor } = await import(pathToFileURL(path.join(HERE, 'oracles.mjs')).href);

  const repros = JSON.parse(fs.readFileSync(reprosArg, 'utf8'));   // plain JSON, no reviver

  for (const repro of repros) {
    const { seq, module: moduleName, export: exportName, args } = repro;
    const outcome = { reproduced: false, reason: null };
    const mod = modules.get(moduleName);
    if (!mod) {
      // Unreachable: the supervisor rejects unknown module names before we are spawned.
      outcome.reason = `no module "${moduleName}" in src/`;
    } else if (typeof mod[exportName] !== 'function') {
      outcome.reason = `"${moduleName}" has no exported function "${exportName}"`;
    } else {
      const oracle = oracleFor(moduleName, exportName);
      const actual = invoke(mod[exportName], Array.isArray(args) ? args : []);
      outcome.actual = clip(scrub(actual.ok ? actual.value : actual.thrown));
      if (!oracle) {
        outcome.reason = `${moduleName}.${exportName} behaved as specified for these arguments`;
      } else {
        const expected = invoke(oracle, Array.isArray(args) ? args : []);
        if (sameOutcome(actual, expected)) {
          outcome.reason = `${moduleName}.${exportName} returned the specified result for these arguments`;
        } else {
          outcome.reproduced = true;
          outcome.expected = clip(scrub(expected.ok ? expected.value : expected.thrown));
          outcome.reason = `${moduleName}.${exportName} produced ${outcome.actual} ` +
                           `where the specification requires ${outcome.expected}`;
        }
      }
    }
    send({ type: 'repro', seq, outcome });
  }

  send({ type: 'done', count: repros.length, tamper: [...new Set(TAMPER)] });
  finish();
}

main().catch((error) => {
  send({ type: 'crash', message: clip(scrub(`${error?.message ?? error}`)) });
  finish();
});
