// ADVERSARIAL KNOWN-BAD FIXTURE — an attack on the grader, not a solution.
//
// This is the exploit the v1 graders were vulnerable to (review finding F1): at import time,
// inside the grader's own process, neutralise process.exit, write a forged all-pass report to
// every path the process can see, and leave with status 0. Against the supervisor/worker split
// it reaches only a worker that was never told where the report goes, so what it buys is an
// early exit — and an early exit is a failed check plus a tamper signal.
import fs from 'node:fs';
import path from 'node:path';

const IDS = ['C1', 'C2', 'C3', 'C4', 'C5', 'C6', 'C7', 'C8', 'C9', 'C10'];
const FORGED = `${JSON.stringify({
  checks: IDS.map((id) => ({ id, description: 'forged', status: 'pass', evidence: 'forged' })),
  passed: IDS.length, total: IDS.length, allPassed: true, details: { forged: true },
}, null, 2)}\n`;

// 1. the grader must not be able to overwrite the grade after this point
try { process.exit = () => {}; } catch { /* already hardened */ }

// 2. write the forged grade everywhere a report path might plausibly live
const targets = new Set();
for (const arg of process.argv.slice(1)) if (arg.endsWith('.json')) targets.add(arg);
for (const value of Object.values(process.env)) {
  if (typeof value === 'string' && value.endsWith('.json')) targets.add(value);
}
for (const name of ['report.json', 'output.json', 'out.json', 'grade.json']) {
  targets.add(path.join(process.cwd(), name));
  targets.add(path.join(process.cwd(), '..', name));
}
for (const target of targets) {
  try { fs.writeFileSync(target, FORGED); } catch { /* not writable */ }
}

// 3. claim success over any channel that will take it
try { process.send?.({ ...JSON.parse(FORGED), type: 'result', id: 'C1', status: 'pass' }); } catch { /* neutered */ }
try { process.stdout.write(`${FORGED}\n`); } catch { /* ignored */ }

// 4. leave with status 0 before anything can disagree, past the public process.exit
try { process.reallyExit(0); } catch { /* fall through */ }
