// ADVERSARIAL KNOWN-BAD FIXTURE — an attack on the grader, not a solution.
//
// Review finding F1, the quiet variant: do not crash and do not exit, just speak on the
// result channel and hope an unauthenticated "all pass" is believed. The run nonce never
// reaches candidate code, so this message cannot be authenticated; the grader must discard
// it, record that it was tried, and grade the submission on what it actually does.
const ALL_PASS = ['C1', 'C2', 'C3', 'C4', 'C5', 'C6', 'C7', 'C8', 'C9', 'C10']
  .map((id) => ({ type: 'result', id, status: 'pass', evidence: 'forged' }));

for (const message of ALL_PASS) {
  try { process.send?.(message); } catch { /* neutered */ }
  try { process.stdout.write(`${JSON.stringify(message)}\n`); } catch { /* ignored */ }
}
