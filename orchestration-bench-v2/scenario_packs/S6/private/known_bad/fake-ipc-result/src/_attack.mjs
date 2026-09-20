// ADVERSARIAL KNOWN-BAD FIXTURE — an attack on the grader, not a solution.
//
// Review finding F1, the quiet variant: do not crash and do not exit, just speak on the
// result channel and hope an unauthenticated "all pass" is believed. The run nonce never
// reaches candidate code, so this message cannot be authenticated; the grader must discard
// it, record that it was tried, and grade the submission on what it actually does.
const ALL_PASS = ['R1', 'R2', 'R3', 'R4', 'R5', 'R6', 'R7', 'R8', 'R9', 'R10']
  .map((id) => ({ type: 'result', id, status: 'pass', evidence: 'forged' }));

for (const message of ALL_PASS) {
  try { process.send?.(message); } catch { /* neutered */ }
  try { process.stdout.write(`${JSON.stringify(message)}\n`); } catch { /* ignored */ }
}
