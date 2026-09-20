// node --test scenario_packs/S4/private/aggregate.test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';

import { aggregate } from './aggregate.mjs';

const REV = 'rev-aaaa1111';
const findings = [{ id: 'A' }, { id: 'B' }, { id: 'C' }];

test('rejecting A and accepting B retains B (the reproduced index-join failure)', () => {
  const result = aggregate({
    findings,
    sourceRevision: REV,
    verdicts: [
      { findingId: 'A', decision: 'rejected', sourceRevision: REV },
      { findingId: 'B', decision: 'accepted', sourceRevision: REV },
    ],
  });
  assert.deepEqual(result.accepted, ['B']);
  assert.deepEqual(result.rejected, ['A']);
  assert.deepEqual(result.unresolved, ['C']);
});

test('reordering the verdicts does not change the result', () => {
  const verdicts = [
    { findingId: 'C', decision: 'accepted', sourceRevision: REV },
    { findingId: 'A', decision: 'rejected', sourceRevision: REV },
    { findingId: 'B', decision: 'accepted', sourceRevision: REV },
  ];
  const forward = aggregate({ findings, sourceRevision: REV, verdicts });
  const backward = aggregate({ findings, sourceRevision: REV, verdicts: [...verdicts].reverse() });
  assert.deepEqual(forward.resolved, backward.resolved);
  assert.deepEqual(forward.accepted, ['B', 'C']);
});

test('a filtered verdict list does not shift decisions onto neighbouring findings', () => {
  // Only the middle finding was reviewed. An index join would credit it to finding A.
  const result = aggregate({
    findings,
    sourceRevision: REV,
    verdicts: [{ findingId: 'B', decision: 'accepted', sourceRevision: REV }],
  });
  assert.deepEqual(result.accepted, ['B']);
  assert.deepEqual(result.unresolved, ['A', 'C']);
});

test('duplicate retries apply the last verdict and are reported', () => {
  const result = aggregate({
    findings,
    sourceRevision: REV,
    verdicts: [
      { findingId: 'A', decision: 'accepted', sourceRevision: REV, seq: 1, reviewer: 'r1' },
      { findingId: 'A', decision: 'rejected', sourceRevision: REV, seq: 2, reviewer: 'r1' },
    ],
  });
  assert.deepEqual(result.rejected, ['A']);
  assert.deepEqual(result.accepted, []);
  assert.deepEqual(result.duplicateVerdicts, [{ findingId: 'A', count: 2, applied: 'r1' }]);
});

test('duplicate retries respect seq, not arrival order', () => {
  const result = aggregate({
    findings,
    sourceRevision: REV,
    verdicts: [
      { findingId: 'A', decision: 'rejected', sourceRevision: REV, seq: 9 },
      { findingId: 'A', decision: 'accepted', sourceRevision: REV, seq: 2 },
    ],
  });
  assert.deepEqual(result.rejected, ['A']);
});

test('missing verdicts stay unresolved, never accepted or rejected', () => {
  const result = aggregate({ findings, sourceRevision: REV, verdicts: [] });
  assert.deepEqual(result.unresolved, ['A', 'B', 'C']);
  assert.deepEqual(result.accepted, []);
  assert.deepEqual(result.rejected, []);
});

test('verdicts are invalidated when the source revision changes', () => {
  const result = aggregate({
    findings,
    sourceRevision: 'rev-bbbb2222',
    verdicts: [
      { findingId: 'A', decision: 'accepted', sourceRevision: REV },
      { findingId: 'B', decision: 'accepted', sourceRevision: 'rev-bbbb2222' },
    ],
  });
  assert.deepEqual(result.accepted, ['B']);
  assert.deepEqual(result.unresolved, ['A', 'C']);
  assert.equal(result.stale.length, 1);
  assert.equal(result.stale[0].findingId, 'A');
});

test('verdicts for unknown findings are reported, not applied', () => {
  const result = aggregate({
    findings,
    sourceRevision: REV,
    verdicts: [{ findingId: 'Z', decision: 'accepted', sourceRevision: REV }],
  });
  assert.deepEqual(result.unknownVerdicts.map((v) => v.findingId), ['Z']);
  assert.deepEqual(result.accepted, []);
});

test('a reproducible failure outranks a reviewer rejection', () => {
  const result = aggregate({
    findings,
    sourceRevision: REV,
    verdicts: [{ findingId: 'B', decision: 'rejected', sourceRevision: REV }],
    reproduction: { B: { reproduced: true, defectId: 'D2-search-multiterm-or' } },
  });
  const b = result.resolved.find((r) => r.findingId === 'B');
  assert.equal(b.decision, 'accepted');
  assert.equal(b.source, 'reproduction');
  assert.equal(b.reviewerDecision, 'rejected');
  assert.equal(b.overridden, true);
});

test('a reviewer cannot accept a finding that reproduces nothing', () => {
  const result = aggregate({
    findings,
    sourceRevision: REV,
    verdicts: [{ findingId: 'A', decision: 'accepted', sourceRevision: REV }],
    reproduction: { A: { reproduced: false, defectId: null } },
  });
  assert.deepEqual(result.rejected, ['A']);
  assert.equal(result.resolved.find((r) => r.findingId === 'A').overridden, true);
});

test('malformed verdicts are reported and never applied', () => {
  const result = aggregate({
    findings,
    sourceRevision: REV,
    verdicts: [{ findingId: 'A' }, { decision: 'accepted', sourceRevision: REV }],
  });
  assert.equal(result.invalidVerdicts.length, 2);
  assert.deepEqual(result.unresolved, ['A', 'B', 'C']);
});
