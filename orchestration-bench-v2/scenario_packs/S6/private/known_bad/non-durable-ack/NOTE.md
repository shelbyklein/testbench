# known_bad: non-durable-ack

The operation is acknowledged before it is performed: the outbox entry and the journal
confirmation are written *before* `transport.send`. The durable record therefore claims an
effect that may never have happened — a permanent refusal leaves a phantom ledger entry, and
the kill at `first_persisted_ack` fires before the first effect is ever accepted, so the
restart skips a note that was never published. Intended failure: acknowledging before
persisting the real effect (R5, R7; it also trips R4 and R8).
