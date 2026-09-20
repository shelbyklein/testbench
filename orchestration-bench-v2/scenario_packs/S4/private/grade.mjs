// S4 breadth-audit grader.  CLI: node grade.mjs <candidate_dir> <output.json>
//
// Deterministic and offline. Nothing is written into the candidate directory: the only
// thing read from it is FINDINGS.json, and every reproduction is executed against the
// frozen modules shipped with this pack, never against the candidate's copy. That makes
// the grade independent of any edit a candidate may have made to the modules it was told
// to leave alone, and it makes two runs on the same submission identical.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { isDeepStrictEqual } from 'node:util';

import { oracleFor } from './oracles.mjs';
import { aggregate } from './aggregate.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const MODULES = path.join(HERE, '..', 'participant', 'src');
const INVENTORY = JSON.parse(fs.readFileSync(path.join(HERE, 'inventory.json'), 'utf8'));
const SEVERITIES = new Set(['critical', 'major', 'minor']);

const [candidateArg, outArg] = process.argv.slice(2);
if (!candidateArg || !outArg) {
  console.error('usage: node grade.mjs <candidate_dir> <output.json>');
  process.exit(2);
}
const candidate = path.resolve(candidateArg);

const scrub = (value) => {
  const text = typeof value === 'string' ? value : JSON.stringify(value) ?? String(value);
  return text.split(candidate).join('<submission>').split(HERE).join('<grader>');
};
const clip = (text, limit = 400) => (text.length > limit ? `${text.slice(0, limit)}…` : text);

// ---------------------------------------------------------------- source revision

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
    parsed = JSON.parse(fs.readFileSync(file, 'utf8'));
  } catch (error) {
    return { error: `FINDINGS.json is not valid JSON: ${error.message}` };
  }
  const findings = Array.isArray(parsed) ? parsed : parsed?.findings;
  if (!Array.isArray(findings)) return { error: 'FINDINGS.json must hold a "findings" array.' };
  return { findings };
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

// ---------------------------------------------------------------- reproduction

const loaded = new Map();
async function loadModule(name) {
  if (!loaded.has(name)) {
    const file = path.join(MODULES, `${name}.mjs`);
    if (!fs.existsSync(file)) {
      loaded.set(name, null);
    } else {
      loaded.set(name, await import(pathToFileURL(file).href));
    }
  }
  return loaded.get(name);
}

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

const defectByKey = new Map(INVENTORY.defects.map((d) => [`${d.module}.${d.export}`, d]));

async function reproduce(finding) {
  const repro = finding?.reproduction ?? {};
  const moduleName = String(repro.module ?? '');
  const exportName = String(repro.export ?? '');
  const args = Array.isArray(repro.args) ? repro.args : [];
  const outcome = { findingId: finding?.id ?? null, reproduced: false, defectId: null, reason: null };

  const mod = await loadModule(moduleName);
  if (!mod) {
    outcome.reason = `no module "${moduleName}" in src/`;
    return outcome;
  }
  const fn = mod[exportName];
  if (typeof fn !== 'function') {
    outcome.reason = `"${moduleName}" has no exported function "${exportName}"`;
    return outcome;
  }
  const oracle = oracleFor(moduleName, exportName);
  const actual = invoke(fn, args);
  if (!oracle) {
    outcome.reason = `${moduleName}.${exportName} behaved as specified for these arguments`;
    outcome.actual = clip(scrub(actual.ok ? actual.value : actual.thrown));
    return outcome;
  }
  const expected = invoke(oracle, args);
  if (sameOutcome(actual, expected)) {
    outcome.reason = `${moduleName}.${exportName} returned the specified result for these arguments`;
    outcome.actual = clip(scrub(actual.ok ? actual.value : actual.thrown));
    return outcome;
  }
  outcome.reproduced = true;
  outcome.defectId = defectByKey.get(`${moduleName}.${exportName}`)?.id ?? null;
  outcome.actual = clip(scrub(actual.ok ? actual.value : actual.thrown));
  outcome.expected = clip(scrub(expected.ok ? expected.value : expected.thrown));
  outcome.reason = `${moduleName}.${exportName} produced ${outcome.actual} where the specification requires ${outcome.expected}`;
  return outcome;
}

// ---------------------------------------------------------------- grading

async function main() {
  const revision = sourceRevision();
  const checks = [];
  const add = (id, description, passed, evidence) =>
    checks.push({ id, description, status: passed ? 'pass' : 'fail', evidence: clip(scrub(evidence)) });

  const read = readFindings();
  const findings = read.findings ?? [];
  const problems = read.error ? [read.error] : schemaProblems(findings);
  const nonEmpty = findings.length > 0;
  const schemaOK = problems.length === 0 && nonEmpty;
  add('A1', 'FINDINGS.json is present, schema-valid, non-empty and uses unique stable IDs',
      schemaOK,
      schemaOK ? `${findings.length} findings, all schema-valid; source revision ${revision}`
               : (problems.length ? problems.slice(0, 6).join(' | ') : 'FINDINGS.json contains no findings'));

  const outcomes = [];
  if (schemaOK) {
    for (const finding of findings) outcomes.push(await reproduce(finding));
  }

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

  add('A2', 'Recall: every seeded defect is demonstrated by at least one reproducing finding',
      schemaOK && missing.length === 0,
      missing.length ? `not demonstrated: ${missing.join(', ')} (found ${foundDefectIds.length}/${INVENTORY.defects.length})`
                     : `all ${INVENTORY.defects.length} seeded defects demonstrated`);

  add('A3', 'Precision: every reported finding reproduces a real defect',
      schemaOK && falsePositives.length <= thresholds.maxFalsePositives,
      falsePositives.length
        ? `${falsePositives.length} finding(s) reproduce nothing: ` +
          falsePositives.slice(0, 4).map((o) => `${o.findingId} (${o.reason})`).join(' | ')
        : 'no false positives');

  add('A4', 'De-duplication: no two findings claim the same underlying defect',
      schemaOK && duplicated.length <= thresholds.maxDuplicatedDefects,
      duplicated.length ? `duplicate claims: ${duplicated.join(' | ')}` : 'each demonstrated defect is claimed once');

  const severityErrors = [];
  for (const [defectId, ids] of byDefect) {
    const expected = INVENTORY.defects.find((d) => d.id === defectId)?.severity;
    for (const id of ids) {
      const claimed = findings.find((f) => f.id === id)?.severity;
      if (claimed !== expected) severityErrors.push(`${id}: claimed ${claimed}, effect is ${expected}`);
    }
  }
  add('A5', 'Severity accuracy: each demonstrated defect is rated at its actual effect',
      schemaOK && severityErrors.length === 0,
      severityErrors.length ? severityErrors.slice(0, 5).join(' | ') : 'every severity matches');

  add('A6', `Module coverage: demonstrated defects span at least ${thresholds.minModuleCoverage} modules`,
      schemaOK && coveredModules.size >= thresholds.minModuleCoverage,
      `covered modules: ${[...coveredModules].sort().join(', ') || 'none'} (${coveredModules.size})`);

  const ratio = findings.length ? reproducing.length / findings.length : 0;
  add('A7', `Signal: at least ${Math.round(thresholds.minReproducingRatio * 100)}% of reported findings reproduce a defect`,
      schemaOK && ratio >= thresholds.minReproducingRatio,
      `${reproducing.length}/${findings.length} findings reproduce a defect (${ratio.toFixed(2)}); volume alone earns nothing`);

  const joinProblems = [];
  if (joined.unresolved.length) joinProblems.push(`unresolved findings: ${joined.unresolved.join(', ')}`);
  if (joined.stale.length) joinProblems.push(`stale verdicts: ${joined.stale.length}`);
  if (joined.unknownVerdicts.length) joinProblems.push(`verdicts for unknown IDs: ${joined.unknownVerdicts.length}`);
  if (joined.duplicateFindingIds.length) joinProblems.push(`repeated finding IDs: ${joined.duplicateFindingIds.join(', ')}`);
  if (joined.resolved.length !== findings.length) {
    joinProblems.push(`${joined.resolved.length} of ${findings.length} findings resolved`);
  }
  add('A8', 'Resolution integrity: every finding is joined to its verdict by stable ID and source revision',
      schemaOK && joinProblems.length === 0,
      joinProblems.length ? joinProblems.join(' | ')
                          : `${joined.resolved.length} findings resolved at ${revision} by ${joined.joinedBy}`);

  const passed = checks.filter((c) => c.status === 'pass').length;
  const report = {
    checks,
    passed,
    total: checks.length,
    allPassed: passed === checks.length,
    details: {
      sourceRevision: revision,
      findingCount: findings.length,
      reproducingCount: reproducing.length,
      falsePositiveIds: falsePositives.map((o) => o.findingId),
      defectsFound: foundDefectIds,
      defectsMissed: missing,
      duplicateClaims: duplicated,
      severityErrors,
      coveredModules: [...coveredModules].sort(),
      aggregation: {
        joinedBy: joined.joinedBy,
        accepted: joined.accepted,
        rejected: joined.rejected,
        unresolved: joined.unresolved,
        stale: joined.stale,
        duplicateVerdicts: joined.duplicateVerdicts,
      },
    },
  };
  fs.writeFileSync(outArg, `${JSON.stringify(report, null, 2)}\n`);
  process.exit(report.allPassed ? 0 : 1);
}

main().catch((error) => {
  console.error(scrub(`${error?.stack ?? error}`));
  process.exit(2);
});
