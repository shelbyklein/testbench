// S4 breadth-audit grader.  CLI: node grade.mjs <candidate_dir> <output.json>
//
// Deterministic and offline. Nothing is written into the candidate directory: the only thing
// read from it is FINDINGS.json, and every reproduction is executed against the frozen modules
// shipped with this pack, never against the candidate's copy. That makes the grade independent
// of any edit a candidate may have made to the modules it was told to leave alone, and it makes
// two runs on the same submission identical.
//
// MODULE ALLOW-LIST (review finding F2).
// `reproduction.module` is submission-controlled and used to be joined onto the modules
// directory with `path.join`, so `"../../../../tmp/x/evil"` escaped it and the grader imported
// and executed an arbitrary file. The name is now checked against the exact list of frozen
// module basenames read from that directory, and the resolved path must sit directly inside
// it. Anything else is a schema error: the finding names a module that does not exist, which
// is decidable without importing anything at all. `reproduction.export` is checked against what
// the named module really exports, and a name that is not there reproduces nothing.
// `reproduction.args` are plain JSON, re-serialised here and parsed in the worker with no
// reviver, so they are data and cannot smuggle code.
//
// SUPERVISOR / WORKER SPLIT (review finding F1).
// This process never imports a module in order to run a reproduction. It forks
// `repro-worker.mjs`, which imports the frozen modules and executes the validated
// reproductions with submission-supplied arguments, and reports each outcome over Node IPC
// authenticated with a per-run random nonce delivered as the supervisor's first IPC message.
// Every check — A1…A8 — is then computed HERE from this grader's own inventory and thresholds.
// A reproduction that did not come back authenticated counts as demonstrating nothing, and the
// fact is recorded in `details.tamperSignals`. The exit code is derived only from this report.
//
// Honest about the residual: this defends the GRADE against forgery and early-exit tricks. It
// is not a sandbox — the worker runs with the user's OS permissions.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';
import { fileURLToPath } from 'node:url';

import { aggregate } from './aggregate.mjs';
import {
  NO_RESULT, census, censusDiff, observeOutput, rebuildReport, runWorker, writeReport,
} from './supervisor.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const MODULES = path.join(HERE, '..', 'participant', 'src');
const WORKER = path.join(HERE, 'repro-worker.mjs');
const INVENTORY = JSON.parse(fs.readFileSync(path.join(HERE, 'inventory.json'), 'utf8'));
const SEVERITIES = new Set(['critical', 'major', 'minor']);
const WORKER_TIMEOUT_MS = 60000;

export const CHECKS = [
  { id: 'A1', description: 'FINDINGS.json is present, schema-valid, non-empty and uses unique stable IDs' },
  { id: 'A2', description: 'Recall: every seeded defect is demonstrated by at least one reproducing finding' },
  { id: 'A3', description: 'Precision: every reported finding reproduces a real defect' },
  { id: 'A4', description: 'De-duplication: no two findings claim the same underlying defect' },
  { id: 'A5', description: 'Severity accuracy: each demonstrated defect is rated at its actual effect' },
  { id: 'A6', description: `Module coverage: demonstrated defects span at least ${INVENTORY.thresholds.minModuleCoverage} modules` },
  { id: 'A7', description: `Signal: at least ${Math.round(INVENTORY.thresholds.minReproducingRatio * 100)}% of reported findings reproduce a defect` },
  { id: 'A8', description: 'Resolution integrity: every finding is joined to its verdict by stable ID and source revision' },
];

const [candidateArg, outArg] = process.argv.slice(2);
if (!candidateArg || !outArg) {
  console.error('usage: node grade.mjs <candidate_dir> <output.json>');
  process.exit(2);
}
const candidate = path.resolve(candidateArg);
const outPath = path.resolve(outArg);

const scrub = (value) => {
  const text = typeof value === 'string' ? value : (JSON.stringify(value) ?? String(value));
  return text.split(candidate).join('<submission>').split(HERE).join('<grader>');
};
const clip = (text, limit = 400) => (text.length > limit ? `${text.slice(0, limit)}…` : text);

// ---------------------------------------------------------------- the frozen modules

/** The exact names of the modules shipped in this pack. The only importable set, ever. */
function frozenModuleNames() {
  return new Set(fs.readdirSync(MODULES)
    .filter((name) => name.endsWith('.mjs'))
    .map((name) => name.slice(0, -4)));
}
const ALLOWED_MODULES = frozenModuleNames();

/** A submission-supplied module name is usable only if it is on the list AND stays put. */
function moduleIsAllowed(name) {
  if (typeof name !== 'string' || !ALLOWED_MODULES.has(name)) return false;
  const resolved = path.resolve(MODULES, `${name}.mjs`);
  return path.dirname(resolved) === path.resolve(MODULES) && fs.existsSync(resolved);
}

function sourceRevision() {
  const names = fs.readdirSync(MODULES).filter((n) => n.endsWith('.mjs')).sort();
  const hash = crypto.createHash('sha256');
  for (const name of names) {
    const digest = crypto.createHash('sha256')
      .update(fs.readFileSync(path.join(MODULES, name)))
      .digest('hex');
    hash.update(`${name}:${digest}\n`);
  }
  return `rev-${hash.digest('hex').slice(0, 12)}`;
}

// ---------------------------------------------------------------- submission

function readFindings() {
  const file = path.join(candidate, 'FINDINGS.json');
  if (!fs.existsSync(file)) return { error: 'FINDINGS.json is missing from the submission root.' };
  let parsed;
  try {
    parsed = JSON.parse(fs.readFileSync(file, 'utf8'));   // plain JSON, no reviver
  } catch (error) {
    return { error: `FINDINGS.json is not valid JSON: ${error.message}` };
  }
  const findings = Array.isArray(parsed) ? parsed : parsed?.findings;
  if (!Array.isArray(findings)) return { error: 'FINDINGS.json must hold a "findings" array.' };
  return { findings };
}

/**
 * Arguments are data. Anything that is not a JSON value is dropped, and the three keys that
 * are a route to a prototype are refused, so nothing a submission writes can become code.
 */
function plainJson(value, depth = 0) {
  if (depth > 12) return null;
  if (value === null) return null;
  const type = typeof value;
  if (type === 'string' || type === 'boolean') return value;
  if (type === 'number') return Number.isFinite(value) ? value : null;
  if (Array.isArray(value)) return value.map((item) => plainJson(item, depth + 1));
  if (type === 'object') {
    const out = {};
    for (const key of Object.keys(value)) {
      if (key === '__proto__' || key === 'constructor' || key === 'prototype') continue;
      out[key] = plainJson(value[key], depth + 1);
    }
    return out;
  }
  return null;   // functions, symbols, undefined: not expressible in JSON, so never present
}

function schemaProblems(findings) {
  const problems = [];
  const seen = new Set();
  findings.forEach((finding, index) => {
    const where = `findings[${index}]`;
    const id = finding?.id;
    if (typeof id !== 'string' || !id.trim()) {
      problems.push(`${where}: "id" must be a non-empty string`);
    } else if (seen.has(id)) {
      problems.push(`${where}: duplicate finding ID ${JSON.stringify(id)}; IDs must be stable and unique`);
    } else {
      seen.add(id);
    }
    for (const key of ['module', 'location', 'claimedBehavior', 'expectedBehavior']) {
      if (typeof finding?.[key] !== 'string' || !finding[key].trim()) {
        problems.push(`${where}: "${key}" must be a non-empty string`);
      }
    }
    if (!SEVERITIES.has(finding?.severity)) {
      problems.push(`${where}: "severity" must be one of critical, major, minor`);
    }
    const repro = finding?.reproduction;
    if (!repro || typeof repro !== 'object' || Array.isArray(repro)) {
      problems.push(`${where}: "reproduction" object is required`);
    } else {
      if (typeof repro.module !== 'string' || !repro.module.trim()) {
        problems.push(`${where}.reproduction: "module" must be a non-empty string`);
      } else if (!moduleIsAllowed(repro.module)) {
        // Review finding F2: the only names that may ever reach an import are these.
        problems.push(`${where}.reproduction: "module" must name one of the modules in src/ ` +
                      `(${[...ALLOWED_MODULES].sort().join(', ')}); ` +
                      `${JSON.stringify(repro.module)} is not one of them`);
      }
      if (typeof repro.export !== 'string' || !repro.export.trim()) {
        problems.push(`${where}.reproduction: "export" must be a non-empty string`);
      }
      if (!Array.isArray(repro.args)) {
        problems.push(`${where}.reproduction: "args" must be an array`);
      }
    }
  });
  return problems;
}

// ---------------------------------------------------------------- grading

async function main() {
  const tamperSignals = [];
  const outBefore = observeOutput(outPath);
  const candidateBefore = census(candidate);
  const revision = sourceRevision();

  const read = readFindings();
  const findings = read.findings ?? [];
  const problems = read.error ? [read.error] : schemaProblems(findings);
  const nonEmpty = findings.length > 0;
  const schemaOK = problems.length === 0 && nonEmpty;

  // The reproductions, validated and reduced to plain data before anything executes them.
  const requests = schemaOK ? findings.map((finding, seq) => ({
    seq,
    module: finding.reproduction.module,
    export: finding.reproduction.export,
    args: plainJson(finding.reproduction.args),
  })) : [];

  const outcomes = findings.map((finding) => ({
    findingId: finding?.id ?? null, reproduced: false, defectId: null,
    reason: schemaOK ? NO_RESULT : 'the submission is not schema-valid; nothing was executed',
  }));

  const scratch = fs.mkdtempSync(path.join(os.tmpdir(), 'ob2-s4-'));
  if (requests.length) {
    const reprosFile = path.join(scratch, 'reproductions.json');
    fs.writeFileSync(reprosFile, JSON.stringify(requests));
    const run = await runWorker({
      worker: WORKER,
      args: [scratch, reprosFile],
      cwd: scratch,
      timeoutMs: WORKER_TIMEOUT_MS,
      label: 'reproductions',
    });
    for (const signal of run.signals) tamperSignals.push(clip(scrub(signal), 300));

    const bySeq = new Map();
    for (const message of run.messages) {
      if (!message || message.type !== 'repro') continue;
      if (!Number.isInteger(message.seq) || message.seq < 0 || message.seq >= requests.length) {
        tamperSignals.push(`the worker reported an outcome for an unknown reproduction index ${String(message.seq)}`);
        continue;
      }
      if (bySeq.has(message.seq)) {
        tamperSignals.push(`the worker reported reproduction ${message.seq} more than once; duplicates are refused`);
        continue;
      }
      bySeq.set(message.seq, message.outcome);
    }
    for (const message of run.messages) {
      if (message?.type !== 'done') continue;
      for (const note of Array.isArray(message.tamper) ? message.tamper : []) {
        tamperSignals.push(`${clip(scrub(String(note)), 200)} (reported by the worker)`);
      }
    }
    for (const { seq } of requests) {
      const got = bySeq.get(seq);
      if (!got || typeof got !== 'object') {
        tamperSignals.push(`reproduction ${seq} (${findings[seq]?.id ?? 'unnamed'}) came back with ` +
                           'no authenticated result and demonstrates nothing');
        continue;
      }
      const defectKey = `${requests[seq].module}.${requests[seq].export}`;
      outcomes[seq] = {
        findingId: findings[seq]?.id ?? null,
        reproduced: got.reproduced === true,
        defectId: got.reproduced === true
          ? (INVENTORY.defects.find((d) => `${d.module}.${d.export}` === defectKey)?.id ?? null)
          : null,
        reason: clip(scrub(String(got.reason ?? ''))),
        ...(got.actual === undefined ? {} : { actual: clip(scrub(String(got.actual))) }),
        ...(got.expected === undefined ? {} : { expected: clip(scrub(String(got.expected))) }),
      };
    }
  }
  fs.rmSync(scratch, { recursive: true, force: true });

  // ------------------------------------------------------------ checks, computed here
  const reproduction = Object.fromEntries(outcomes.map((o) => [o.findingId, o]));
  const verdicts = outcomes.map((o, index) => ({
    findingId: o.findingId,
    decision: o.reproduced ? 'accepted' : 'rejected',
    sourceRevision: revision,
    reviewer: 'grader',
    seq: index,
  }));
  const joined = aggregate({ findings, verdicts, sourceRevision: revision, reproduction });

  const reproducing = outcomes.filter((o) => o.reproduced);
  const falsePositives = outcomes.filter((o) => !o.reproduced);
  const byDefect = new Map();
  for (const outcome of reproducing) {
    const bucket = byDefect.get(outcome.defectId) ?? [];
    bucket.push(outcome.findingId);
    byDefect.set(outcome.defectId, bucket);
  }
  const foundDefectIds = [...byDefect.keys()].sort();
  const missing = INVENTORY.defects.map((d) => d.id).filter((id) => !byDefect.has(id));
  const duplicated = [...byDefect.entries()].filter(([, ids]) => ids.length > 1)
    .map(([defectId, ids]) => `${defectId} claimed by ${ids.join(', ')}`);
  const coveredModules = new Set(reproducing
    .map((o) => INVENTORY.defects.find((d) => d.id === o.defectId)?.module)
    .filter(Boolean));
  const thresholds = INVENTORY.thresholds;

  const severityErrors = [];
  for (const [defectId, ids] of byDefect) {
    const expected = INVENTORY.defects.find((d) => d.id === defectId)?.severity;
    for (const id of ids) {
      const claimed = findings.find((f) => f.id === id)?.severity;
      if (claimed !== expected) severityErrors.push(`${id}: claimed ${claimed}, effect is ${expected}`);
    }
  }

  const joinProblems = [];
  if (joined.unresolved.length) joinProblems.push(`unresolved findings: ${joined.unresolved.join(', ')}`);
  if (joined.stale.length) joinProblems.push(`stale verdicts: ${joined.stale.length}`);
  if (joined.unknownVerdicts.length) joinProblems.push(`verdicts for unknown IDs: ${joined.unknownVerdicts.length}`);
  if (joined.duplicateFindingIds.length) joinProblems.push(`repeated finding IDs: ${joined.duplicateFindingIds.join(', ')}`);
  if (joined.resolved.length !== findings.length) {
    joinProblems.push(`${joined.resolved.length} of ${findings.length} findings resolved`);
  }

  const ratio = findings.length ? reproducing.length / findings.length : 0;
  const results = new Map();
  const set = (id, passed, evidence) =>
    results.set(id, { status: passed ? 'pass' : 'fail', evidence: clip(scrub(evidence)) });

  set('A1', schemaOK,
      schemaOK ? `${findings.length} findings, all schema-valid; source revision ${revision}`
               : (problems.length ? problems.slice(0, 6).join(' | ') : 'FINDINGS.json contains no findings'));
  set('A2', schemaOK && missing.length === 0,
      missing.length ? `not demonstrated: ${missing.join(', ')} (found ${foundDefectIds.length}/${INVENTORY.defects.length})`
                     : `all ${INVENTORY.defects.length} seeded defects demonstrated`);
  set('A3', schemaOK && falsePositives.length <= thresholds.maxFalsePositives,
      falsePositives.length
        ? `${falsePositives.length} finding(s) reproduce nothing: ` +
          falsePositives.slice(0, 4).map((o) => `${o.findingId} (${o.reason})`).join(' | ')
        : 'no false positives');
  set('A4', schemaOK && duplicated.length <= thresholds.maxDuplicatedDefects,
      duplicated.length ? `duplicate claims: ${duplicated.join(' | ')}` : 'each demonstrated defect is claimed once');
  set('A5', schemaOK && severityErrors.length === 0,
      severityErrors.length ? severityErrors.slice(0, 5).join(' | ') : 'every severity matches');
  set('A6', schemaOK && coveredModules.size >= thresholds.minModuleCoverage,
      `covered modules: ${[...coveredModules].sort().join(', ') || 'none'} (${coveredModules.size})`);
  set('A7', schemaOK && ratio >= thresholds.minReproducingRatio,
      `${reproducing.length}/${findings.length} findings reproduce a defect (${ratio.toFixed(2)}); volume alone earns nothing`);
  set('A8', schemaOK && joinProblems.length === 0,
      joinProblems.length ? joinProblems.join(' | ')
                          : `${joined.resolved.length} findings resolved at ${revision} by ${joined.joinedBy}`);

  const touched = censusDiff(candidateBefore, census(candidate));
  if (touched.length) {
    tamperSignals.push(`the candidate directory was written to during grading: ${touched.slice(0, 6).join(', ')}`);
  }

  const report = rebuildReport(CHECKS, results, {
    sourceRevision: revision,
    findingCount: findings.length,
    reproducingCount: reproducing.length,
    falsePositiveIds: falsePositives.map((o) => o.findingId),
    defectsFound: foundDefectIds,
    defectsMissed: missing,
    duplicateClaims: duplicated,
    severityErrors,
    coveredModules: [...coveredModules].sort(),
    allowedModules: [...ALLOWED_MODULES].sort(),
    aggregation: {
      joinedBy: joined.joinedBy,
      accepted: joined.accepted,
      rejected: joined.rejected,
      unresolved: joined.unresolved,
      stale: joined.stale,
      duplicateVerdicts: joined.duplicateVerdicts,
    },
    graderModel: 'supervisor/worker: reproductions run only in a forked worker over an ' +
                 'allow-listed frozen module, with plain-JSON arguments; every check is ' +
                 'computed by the supervisor from its own inventory',
  }, tamperSignals);

  writeReport(outPath, report, tamperSignals, outBefore);
  process.exit(report.allPassed ? 0 : 1);
}

main().catch((error) => {
  console.error(scrub(`${error?.stack ?? error}`));
  process.exit(2);
});
