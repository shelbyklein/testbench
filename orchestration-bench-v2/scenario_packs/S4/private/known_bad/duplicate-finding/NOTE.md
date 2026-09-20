# known_bad: duplicate-finding

All six seeded defects are found, and the pagination defect is then reported a second time under a different finding ID with different arguments. Both findings reproduce, both are genuine, and both map to `D6-pagination-floor-total-pages`. Intended failure: **A4** (de-duplication). Precision and signal ratio are untouched.
