// Supervisor-side harness. THIS FILE NEVER IMPORTS CANDIDATE CODE.
//
// It forks a worker child process, hands it a per-run random nonce over Node IPC as the
// very first message (never argv, never env), collects only messages carrying that nonce,
// and reports what it saw. Every judgement about the grade is made by the caller from the
// values returned here — the worker can only ever offer a result, never record one.
//
// This is defence against report forgery and early-exit tricks. It is NOT a sandbox:
// candidate code still runs with the user's OS permissions inside the worker.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { fork } from 'node:child_process';

export const NO_RESULT = 'no authenticated result (worker exited early, crashed or was tampered with)';

/** A file census of a directory: relative path -> size and mtime. Used to prove no writes. */
export function census(dir) {
  const out = new Map();
  const walk = (current) => {
    let entries;
    try {
      entries = fs.readdirSync(current, { withFileTypes: true });
    } catch {
      return;
    }
    for (const entry of entries) {
      if (entry.name === '.git' || entry.name === 'node_modules') continue;
      const full = path.join(current, entry.name);
      if (entry.isDirectory()) walk(full);
      else if (entry.isFile()) {
        const stat = fs.statSync(full);
        out.set(path.relative(dir, full), `${stat.size}:${stat.mtimeMs}`);
      }
    }
  };
  walk(dir);
  return out;
}

/** What changed between two censuses, as sorted human-readable strings. */
export function censusDiff(before, after) {
  const changes = [];
  for (const [key, value] of after) {
    if (!before.has(key)) changes.push(`created ${key}`);
    else if (before.get(key) !== value) changes.push(`modified ${key}`);
  }
  for (const key of before.keys()) if (!after.has(key)) changes.push(`removed ${key}`);
  return changes.sort();
}

/**
 * Run one worker to completion.
 *
 * Returns `{ messages, exitCode, signal, timedOut, signals, stderr }` where `messages` holds
 * only the payloads that carried the nonce, and `signals` names everything unexpected that
 * was seen: unauthenticated messages, a timeout, a non-zero exit, a killed process.
 */
export function runWorker({ worker, args, cwd, timeoutMs = 20000, label = 'worker' }) {
  const nonce = crypto.randomBytes(24).toString('hex');
  const messages = [];
  const signals = [];
  let unauthenticated = 0;

  return new Promise((resolve) => {
    let child;
    try {
      child = fork(worker, args, {
        cwd,
        execArgv: [],
        stdio: ['ignore', 'pipe', 'pipe', 'ipc'],
        // A deliberately narrow environment: nothing here names the report path.
        env: { PATH: process.env.PATH ?? '', NODE_ENV: 'grader' },
      });
    } catch (error) {
      signals.push(`${label}: the worker could not be started (${error?.message ?? error})`);
      resolve({ messages, exitCode: null, signal: null, timedOut: false, signals, stderr: '' });
      return;
    }

    let stderr = '';
    child.stderr?.on('data', (chunk) => { stderr += String(chunk); });
    child.stdout?.on('data', () => {});   // drained and ignored: stdout is not a result channel

    child.on('message', (message) => {
      if (!message || typeof message !== 'object' || message.__nonce !== nonce) {
        unauthenticated += 1;
        return;
      }
      const { __nonce, ...payload } = message;
      messages.push(payload);
    });

    let timedOut = false;
    const timer = setTimeout(() => {
      timedOut = true;
      try { child.kill('SIGKILL'); } catch { /* already gone */ }
    }, timeoutMs);

    child.on('error', (error) => {
      signals.push(`${label}: the worker channel errored (${error?.message ?? error})`);
    });

    child.on('exit', (exitCode, signal) => {
      clearTimeout(timer);
      if (unauthenticated > 0) {
        signals.push(`${label}: ${unauthenticated} message(s) arrived without the run nonce and were discarded`);
      }
      if (timedOut) signals.push(`${label}: the worker did not finish within ${timeoutMs}ms and was killed`);
      else if (signal) signals.push(`${label}: the worker was killed by ${signal}`);
      else if (exitCode !== 0) signals.push(`${label}: the worker exited with code ${exitCode}`);
      resolve({ messages, exitCode, signal, timedOut, signals, stderr });
    });

    // The nonce, delivered over the channel before the worker imports anything of the
    // candidate's. It is consumed by the worker harness and held in a closure.
    try { child.send({ nonce }); } catch {
      signals.push(`${label}: the run nonce could not be delivered`);
    }
  });
}

/**
 * Pick the single authenticated result for `id` out of a worker's messages.
 * Anything else — none, several, the wrong ID — is refused and named.
 */
export function singleResult(messages, id, label, signals) {
  const results = messages.filter((m) => m && m.type === 'result');
  const foreign = results.filter((m) => m.id !== id);
  if (foreign.length) {
    signals.push(`${label}: the worker reported result(s) for unexpected check ID(s) ` +
                 `${[...new Set(foreign.map((m) => String(m.id)))].sort().join(', ')}`);
  }
  const mine = results.filter((m) => m.id === id);
  if (mine.length === 0) return null;
  if (mine.length > 1) {
    signals.push(`${label}: the worker reported ${mine.length} results for ${id}; duplicates are refused`);
    return null;
  }
  return mine[0];
}

/**
 * The report, rebuilt from scratch by the supervisor.
 *
 * `expected` is the grader's own check list. Anything the worker did not report with a valid
 * nonce fails. passed/total/allPassed are computed here and nowhere else.
 */
export function rebuildReport(expected, results, details, tamperSignals) {
  const checks = expected.map(({ id, description }) => {
    const got = results.get(id);
    if (!got) return { id, description, status: 'fail', evidence: NO_RESULT };
    return {
      id,
      description,
      status: got.status === 'pass' ? 'pass' : 'fail',
      evidence: typeof got.evidence === 'string' && got.evidence ? got.evidence : NO_RESULT,
    };
  });
  const passed = checks.filter((c) => c.status === 'pass').length;
  return {
    checks,
    passed,
    total: checks.length,
    allPassed: passed === checks.length,
    details: {
      ...details,
      failed: checks.filter((c) => c.status !== 'pass').map((c) => c.id),
      tamperSignals: [...tamperSignals],
    },
  };
}

export function observeOutput(outArg) {
  const existed = fs.existsSync(outArg);
  return { existed, content: existed ? fs.readFileSync(outArg, 'utf8') : null };
}

/**
 * Write the rebuilt report. If anything else wrote to the output path while the workers ran,
 * that is recorded as tampering and the forged content is discarded.
 */
export function writeReport(outArg, report, tamperSignals, seenBefore) {
  const existsNow = fs.existsSync(outArg);
  if (existsNow && !seenBefore.existed) {
    tamperSignals.push('the report path was created by something other than the supervisor; ' +
                       'the forged content was discarded');
  } else if (existsNow && seenBefore.content !== null &&
             fs.readFileSync(outArg, 'utf8') !== seenBefore.content) {
    tamperSignals.push('the report path was rewritten by something other than the supervisor; ' +
                       'the forged content was discarded');
  }
  report.details.tamperSignals = [...tamperSignals];
  fs.writeFileSync(outArg, `${JSON.stringify(report, null, 2)}\n`);
}
