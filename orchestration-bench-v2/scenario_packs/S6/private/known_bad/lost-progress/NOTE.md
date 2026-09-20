# known_bad: lost-progress

There is no durable progress at all — the journal lives in memory — and every run clears the
outbox before it starts. A restart therefore begins from scratch: the ledger written before the
crash is truncated away and every note is sent again. Intended failure: lost progress and lost
recorded data across a restart (R2, R6, R8, R9; it also trips R4, R5 and R7).
