# known_bad: single-consumer-pass

The API consumer and the persistence layer were migrated completely and pass their own consumer checks. The exporter, the search index and the client formatter were never touched: they still read `note.tags` as a string and `note.created`, and they still accept v1 records instead of rejecting them. Intended failures: the three untouched consumer checks, the compatibility matrix and the integrated flow.
