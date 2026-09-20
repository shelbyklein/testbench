// The S6 check list. The supervisor owns this: the report is rebuilt from exactly these IDs
// and descriptions, whatever a worker does or does not say.
export const MILESTONE = 'first_persisted_ack';

export const CHECKS = [
  { id: 'R1', description: 'Happy path: every unarchived note is published exactly once and the saved records are untouched' },
  { id: 'R2', description: 'Durable progress: re-running over an already-published set sends nothing and publishes nothing twice' },
  { id: 'R3', description: 'A transient failure is retried and still produces exactly one external effect' },
  { id: 'R4', description: 'A permanent failure is reported as a failure, not as a missing effect reported as done' },
  { id: 'R5', description: `Restart recovery: killed at the semantic milestone ${MILESTONE}, a restart finishes with no duplicated effect` },
  { id: 'R6', description: 'Nothing is lost across the crash: the saved records and the earlier outbox bytes survive intact' },
  { id: 'R7', description: 'A crash between the accepted effect and its record is reconciled, not re-sent' },
  { id: 'R8', description: 'The restart does not repeat completed work' },
  { id: 'R9', description: 'The outbox is append-only and holds at most one entry per key' },
  { id: 'R10', description: 'No regression of pre-existing behavior' },
];

export const CHECK_IDS = CHECKS.map((c) => c.id);
