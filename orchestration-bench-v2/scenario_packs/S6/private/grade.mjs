// S6 interruption-and-recovery grader.  CLI: node grade.mjs <candidate_dir> <output.json>
//
// Deterministic and offline. The candidate directory is never written to: it is copied into a
// fresh temporary directory, and every check runs the job in a per-check working directory
// seeded from a copy of the saved records. Temporary paths and the candidate path are scrubbed
// out of the evidence.
//
// SUPERVISOR / WORKER SPLIT (review finding F1).
// This process — the one the bench launches — never imports candidate code. For each check it
// forks `worker.mjs`, which holds the deterministic fault wrapper and imports the candidate's
// modules, and may therefore be hostile. The worker is not told where the report goes: its
// argv holds only a private temporary directory and its environment is narrowed. It offers a
// result over Node IPC, authenticated with a per-run random nonce delivered as the
// supervisor's first IPC message and consumed by the worker harness before any candidate
// import.
//
// The report is REBUILT here from the pack's own check list. Any check that did not arrive
// with a valid nonce fails; passed/total/allPassed are computed here; the exit code is derived
// only from this rebuilt report. Early exits, timeouts, unauthenticated, duplicate or unknown
// messages and unexpected writes are recorded in `details.tamperSignals`.
//
// Honest about the residual: this defends the GRADE against forgery and early-exit tricks. It
// is not a sandbox. Candidate code still executes with the user's OS permissions inside the
// worker, and a sufficiently adversarial submission could still attack the worker's channel.
// What it cannot do is write its own grade.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { CHECKS, MILESTONE } from './checks.mjs';
import {
  census, censusDiff, observeOutput, rebuildReport, runWorker, singleResult, writeReport,
} from './supervisor.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const WORKER = path.join(HERE, 'worker.mjs');
const PER_CHECK_TIMEOUT_MS = 15000;
const PENDING_KEYS = ['note:n-1@3', 'note:n-2@1', 'note:n-3@7', 'note:n-5@1'];

const [candidateArg, outArg] = process.argv.slice(2);
if (!candidateArg || !outArg) {
  console.error('usage: node grade.mjs <candidate_dir> <output.json>');
  process.exit(2);
}
const candidate = path.resolve(candidateArg);
const outPath = path.resolve(outArg);
const workdir = fs.mkdtempSync(path.join(os.tmpdir(), 'ob2-s6-'));

const scrub = (value) => {
  const text = typeof value === 'string' ? value : (JSON.stringify(value) ?? String(value));
  return text.split(candidate).join('<submission>')
             .split(workdir).join('<workdir>')
             .split(os.tmpdir()).join('<tmp>')
             .split(HERE).join('<grader>');
};
const clip = (text, limit = 420) => (text.length > limit ? `${text.slice(0, limit)}…` : text);

async function main() {
  const tamperSignals = [];
  const outBefore = observeOutput(outPath);

  fs.cpSync(candidate, workdir, {
    recursive: true,
    filter: (src) => !/(^|[\\/])(\.git|node_modules)$/.test(src),
  });
  const candidateBefore = census(candidate);

  const results = new Map();
  for (const { id } of CHECKS) {
    const scratch = path.join(workdir, `scratch-${id}`);
    fs.mkdirSync(scratch, { recursive: true });
    const run = await runWorker({
      worker: WORKER,
      args: [workdir, scratch, id],
      cwd: scratch,
      timeoutMs: PER_CHECK_TIMEOUT_MS,
      label: id,
    });
    for (const signal of run.signals) tamperSignals.push(clip(scrub(signal), 300));
    const result = singleResult(run.messages, id, id, tamperSignals);
    if (result) {
      results.set(id, { status: result.status, evidence: clip(scrub(result.evidence ?? '')) });
      for (const note of Array.isArray(result.tamper) ? result.tamper : []) {
        tamperSignals.push(`${id}: ${clip(scrub(String(note)), 200)} (reported by the worker)`);
      }
    } else {
      tamperSignals.push(`${id}: the worker offered no authenticated result for this check`);
    }
  }

  const touched = censusDiff(candidateBefore, census(candidate));
  if (touched.length) {
    tamperSignals.push(`the candidate directory was written to during grading: ${touched.slice(0, 6).join(', ')}`);
  }

  const report = rebuildReport(CHECKS, results, {
    milestone: MILESTONE,
    milestoneDefinition: 'the outbox file on disk durably holds its first entry (the first acknowledged persisted operation)',
    pendingKeys: PENDING_KEYS,
    faultModel: ['transient send failure', 'permanent send failure',
                 `kill at ${MILESTONE}`, 'kill between an accepted effect and its record'],
    graderModel: 'supervisor/worker: candidate code and the fault wrapper run only in a forked ' +
                 'worker that never learns the report path; the supervisor rebuilds the report ' +
                 'from its own check list',
  }, tamperSignals);

  writeReport(outPath, report, tamperSignals, outBefore);
  fs.rmSync(workdir, { recursive: true, force: true });
  process.exit(report.allPassed ? 0 : 1);
}

main().catch((error) => {
  console.error(scrub(`${error?.stack ?? error}`));
  fs.rmSync(workdir, { recursive: true, force: true });
  process.exit(2);
});
