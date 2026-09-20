# known_bad: partial-migration

Tags became arrays and timestamps were normalised, but the two new required fields were never added: migrated records carry neither `archived` nor `schemaVersion`. Every consumer was edited, so nothing looks untouched — the contract is simply not finished. Intended failures: record-level migration, the API consumer and the integrated flow.
