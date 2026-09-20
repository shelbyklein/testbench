// Verdict aggregation for S4 findings.
//
// Findings and reviewer verdicts are joined by STABLE FINDING ID plus SOURCE REVISION.
// Never by position: the caller may hand us a filtered, reordered or partially retried
// list of verdicts, and the join must not drift. The reproduced failure in the article
// this bench is modelled on came from index joins: rejecting finding A and accepting B
// dropped B, because B was matched to A's slot after the list was filtered.
//
// Rules, in order of authority:
//   1. A verdict whose sourceRevision differs from the current revision is STALE. It is
//      never applied; the finding it names stays unresolved unless a current verdict or
//      reproduction evidence exists. Changing the source invalidates the review.
//   2. A verdict naming a finding that does not exist is UNKNOWN and is reported, not applied.
//   3. Several current verdicts for one finding are duplicate retries: the last one by
//      `seq` (falling back to arrival order) wins, and the retry is reported.
//   4. Reproducible behavioral evidence outranks reviewer votes. A finding with
//      `reproduced: true` is accepted even if a reviewer rejected it; a finding with
//      `reproduced: false` is rejected even if a reviewer accepted it. The reviewer's own
//      decision is still reported alongside, with `overridden: true`.
//   5. A finding with neither a current verdict nor reproduction evidence is UNRESOLVED.
//      Unresolved is never silently turned into accepted or rejected.
//
// Output collections are sorted by finding ID so the result is independent of input order.

const DECISIONS = new Set(['accepted', 'rejected']);

function byId(a, b) {
  return a < b ? -1 : a > b ? 1 : 0;
}

export function aggregate({ findings = [], verdicts = [], sourceRevision = null, reproduction = {} } = {}) {
  const findingIds = [];
  const known = new Map();
  const duplicateFindingIds = [];
  for (const finding of findings) {
    const id = finding?.id;
    if (typeof id !== 'string' || !id) continue;
    if (known.has(id)) {
      duplicateFindingIds.push(id);
      continue;
    }
    known.set(id, finding);
    findingIds.push(id);
  }

  const stale = [];
  const unknownVerdicts = [];
  const invalid = [];
  const current = new Map(); // findingId -> [{verdict, order}]
  verdicts.forEach((verdict, index) => {
    const id = verdict?.findingId;
    if (typeof id !== 'string' || !id || !DECISIONS.has(verdict?.decision)) {
      invalid.push({ index, reason: 'verdict needs a findingId and a decision of accepted|rejected' });
      return;
    }
    if (!known.has(id)) {
      unknownVerdicts.push({ findingId: id, reason: 'no finding with this ID' });
      return;
    }
    if ((verdict.sourceRevision ?? null) !== sourceRevision) {
      stale.push({
        findingId: id,
        verdictRevision: verdict.sourceRevision ?? null,
        currentRevision: sourceRevision,
        reason: 'verdict was cast against a different source revision',
      });
      return;
    }
    const bucket = current.get(id) ?? [];
    bucket.push({ verdict, order: typeof verdict.seq === 'number' ? verdict.seq : index });
    current.set(id, bucket);
  });

  const duplicateVerdicts = [];
  const resolved = [];
  const unresolved = [];
  for (const id of findingIds) {
    const bucket = (current.get(id) ?? []).slice().sort((a, b) => a.order - b.order || 0);
    if (bucket.length > 1) {
      duplicateVerdicts.push({
        findingId: id,
        count: bucket.length,
        applied: bucket[bucket.length - 1].verdict.reviewer ?? null,
      });
    }
    const reviewerVerdict = bucket.length ? bucket[bucket.length - 1].verdict : null;
    const reviewerDecision = reviewerVerdict ? reviewerVerdict.decision : null;
    const evidence = Object.prototype.hasOwnProperty.call(reproduction, id) ? reproduction[id] : null;

    if (evidence && typeof evidence.reproduced === 'boolean') {
      const decision = evidence.reproduced ? 'accepted' : 'rejected';
      resolved.push({
        findingId: id,
        decision,
        source: 'reproduction',
        defectId: evidence.defectId ?? null,
        reviewerDecision,
        overridden: reviewerDecision !== null && reviewerDecision !== decision,
        sourceRevision,
      });
      continue;
    }
    if (reviewerDecision) {
      resolved.push({
        findingId: id,
        decision: reviewerDecision,
        source: 'reviewer',
        defectId: evidence?.defectId ?? null,
        reviewerDecision,
        overridden: false,
        sourceRevision,
      });
      continue;
    }
    unresolved.push(id);
  }

  resolved.sort((a, b) => byId(a.findingId, b.findingId));
  unresolved.sort(byId);
  stale.sort((a, b) => byId(a.findingId, b.findingId));
  unknownVerdicts.sort((a, b) => byId(a.findingId, b.findingId));
  duplicateVerdicts.sort((a, b) => byId(a.findingId, b.findingId));

  return {
    sourceRevision,
    resolved,
    unresolved,
    stale,
    unknownVerdicts,
    duplicateVerdicts,
    duplicateFindingIds: duplicateFindingIds.slice().sort(byId),
    invalidVerdicts: invalid,
    accepted: resolved.filter((r) => r.decision === 'accepted').map((r) => r.findingId),
    rejected: resolved.filter((r) => r.decision === 'rejected').map((r) => r.findingId),
    joinedBy: 'findingId+sourceRevision',
  };
}
