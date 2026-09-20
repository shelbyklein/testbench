# known_bad: missed-defect

All six audits were attempted but the sorting tie-break defect (`sorting.sortNotes`, ties ordered descending) was never reported. Intended failure: **A2** (recall). Module coverage stays above the floor, so A6 still passes; this fixture isolates recall.
