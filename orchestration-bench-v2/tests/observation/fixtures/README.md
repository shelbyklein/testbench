# Observation fixtures — all fabricated

Every file here is **fabricated test data**. Nothing was copied from a real session,
a real provider response or a real repository.

- `solo.jsonl`, `handoff.jsonl`, `active.jsonl`, `inclusive.jsonl`, `unknown_usage.jsonl`,
  `active_conflict.jsonl` are already-normalized `trace-event/1` JSONL and each event
  carries `"synthetic": true`.
- `claude_session.jsonl` is a **hand-written** Claude Code transcript with the same
  structural shape as a real `~/.claude/projects/<slug>/<session>.jsonl` file
  (`sessionId`, `uuid`/`parentUuid`, `timestamp`, `message.model`, `message.usage`,
  `tool_use` blocks, an `isSidechain` subagent branch, housekeeping line types).
  The model names, ids, paths and text are invented. It deliberately contains
  `thinking` blocks and `/Users/<name>` paths so the tests can prove the importer
  never stores reasoning text and always redacts home paths.

`active.jsonl` is written in shuffled arrival order and contains one byte-identical
duplicate line on purpose.
