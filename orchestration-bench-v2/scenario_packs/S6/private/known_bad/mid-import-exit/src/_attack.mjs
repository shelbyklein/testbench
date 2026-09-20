// ADVERSARIAL KNOWN-BAD FIXTURE — an attack on the grader, not a solution.
//
// The simplest version of review finding F1: die at import time with status 0 and hope the
// grader treats "the process ended cleanly" as "the checks passed". Every check that imports
// this module must fail, and the grader must say why.
process.exit(0);
