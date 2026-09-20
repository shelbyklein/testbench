// The S5 check list. The supervisor owns this: the report is rebuilt from exactly these IDs
// and descriptions, whatever a worker does or does not say. Imported by grade.mjs (the
// supervisor) and by worker.mjs (which only uses it to know which body to run).
export const CHECKS = [
  { id: 'C1', description: 'Saved records survive the migration: every field of every stored note is preserved' },
  { id: 'C2', description: 'Migration is idempotent: migrating an already-migrated record or file is a no-op' },
  { id: 'C3', description: 'Serialization round trip: saveNotes then loadNotes returns the same records in the v2 envelope' },
  { id: 'C4', description: 'API consumer speaks v2: created and read records carry the new contract' },
  { id: 'C5', description: 'Exporter consumer speaks v2: CSV carries the new columns and values' },
  { id: 'C6', description: 'Search index consumer speaks v2: it indexes array tags' },
  { id: 'C7', description: 'Formatter consumer speaks v2: display strings come from the new fields' },
  { id: 'C8', description: 'Compatibility matrix: legacy input is accepted where specified and rejected where specified' },
  { id: 'C9', description: 'Integrated flow: a legacy post crosses persistence and all four consumers' },
  { id: 'C10', description: 'No regression of pre-existing behavior' },
];

export const CHECK_IDS = CHECKS.map((c) => c.id);
