# known_bad: duplicate-effects

Progress is durable, but the resume filter and the writer disagree: the journal records a
finished operation as `acked` while the resume path only skips `confirmed`. After the restart
at `first_persisted_ack` the job replays the operation that was already acknowledged, and it
appends to the outbox unconditionally, so the same idempotency key produces a second external
effect and a second ledger entry. Intended failure: a duplicated externally visible effect
after recovery (R2, R5, R8; it also trips R4 and R9).
