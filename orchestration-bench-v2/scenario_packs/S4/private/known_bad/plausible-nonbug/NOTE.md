# known_bad: plausible-nonbug

All six seeded defects are found, but the audit also reports `archive.visibleNotes` returning both archived and unarchived notes under `includeArchived: true`. The module doc comment states that behaviour explicitly, and the reproduction returns exactly the specified result. Intended failure: **A3** (precision). The signal ratio stays at 6/7, above the A7 floor, so this fixture isolates precision.
