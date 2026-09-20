export const meta = {
  name: 'graph-candidate',
  description: 'Orchestration Bench v2 graph candidate: planner, three file-owning workers, a fresh-session internal reviewer, and an integrator joined by stable ID.',
  whenToUse: 'Bench arm only. Run this as the graph method of an Orchestration Bench v2 scenario run; it is not a general-purpose development workflow.',
  phases: [
    { title: 'Plan', detail: 'one planner assigns lanes and exclusive file ownership' },
    { title: 'Implement', detail: 'one agent per lane, each writing only the files it owns' },
    { title: 'Review', detail: 'fresh-session reviewer sees spec, diff and evidence only' },
    { title: 'Integrate', detail: 'join by stable ID + sourceRevision and write the final artifact' },
  ],
}

// ---------------------------------------------------------------------------
// graph-candidate.v1  --  versioned native Claude Code dynamic-workflow script.
//
// Contract notes that MUST hold for this arm to be comparable:
//   * No agent() call sets `model` or `effort`. Every node inherits the session's
//     resolved model and effort, so this arm does not silently raise either.
//     Launching the session with /effort ultracode raises effort to xhigh at the
//     same time as it enables orchestration and is a CONFOUND, not evidence.
//   * The reviewer gets a FRESH session whose input is only the specification,
//     the relevant diff and reproducible evidence. No worker conversation is
//     passed to it. Its usage is charged to the candidate.
//   * The external evaluator is NOT part of this workflow and is never consulted.
//   * Joins are by stable node ID plus sourceRevision, never by list index.
//   * Date.now()/Math.random()/new Date() throw inside a workflow script, so the
//     revision and any timestamp arrive through `args`.
//
// Expected `args`:
//   { runId, scenarioId, repeat, workspace, sourceRevision, specification,
//     lanes: [{ nodeId, brief, owns: [path, ...] }, ...] }
// ---------------------------------------------------------------------------

const input = args || {}
const SPEC = input.specification || 'See TASK.md in the workspace for the complete request and acceptance contract.'
const REVISION = input.sourceRevision || 'unknown-revision'
const LANES = Array.isArray(input.lanes) && input.lanes.length
  ? input.lanes
  : [
      { nodeId: 'worker-a', brief: 'Lane A', owns: ['src/store.mjs'] },
      { nodeId: 'worker-b', brief: 'Lane B', owns: ['src/service.mjs'] },
      { nodeId: 'worker-c', brief: 'Lane C', owns: ['src/queries.mjs'] },
    ]

const PLAN_SCHEMA = {
  type: 'object',
  required: ['lanes'],
  properties: {
    lanes: {
      type: 'array',
      items: {
        type: 'object',
        required: ['nodeId', 'brief', 'owns'],
        properties: {
          nodeId: { type: 'string' },
          brief: { type: 'string' },
          owns: { type: 'array', items: { type: 'string' } },
        },
      },
    },
  },
}

const WORKER_SCHEMA = {
  type: 'object',
  required: ['nodeId', 'sourceRevision', 'artifactHash', 'summary', 'files'],
  properties: {
    nodeId: { type: 'string' },
    sourceRevision: { type: 'string' },
    artifactHash: { type: 'string' },
    summary: { type: 'string' },
    files: { type: 'array', items: { type: 'string' } },
    evidence: { type: 'string' },
    blocked: { type: 'boolean' },
  },
}

const VERDICT_SCHEMA = {
  type: 'object',
  required: ['verdicts'],
  properties: {
    verdicts: {
      type: 'array',
      items: {
        type: 'object',
        required: ['targetNodeId', 'sourceRevision', 'verdict', 'reason'],
        properties: {
          targetNodeId: { type: 'string' },
          sourceRevision: { type: 'string' },
          verdict: { type: 'string', enum: ['approve', 'reject', 'unclear'] },
          reason: { type: 'string' },
        },
      },
    },
  },
}

const FINAL_SCHEMA = {
  type: 'object',
  required: ['nodeId', 'sourceRevision', 'artifactHash', 'summary'],
  properties: {
    nodeId: { type: 'string' },
    sourceRevision: { type: 'string' },
    artifactHash: { type: 'string' },
    summary: { type: 'string' },
    unresolved: { type: 'array', items: { type: 'string' } },
  },
}

// -- Plan -------------------------------------------------------------------
phase('Plan')
const planned = await agent(
  [
    'You are the planner node of a bench candidate. Do not write code.',
    'Specification:', SPEC,
    '',
    `Source revision under work: ${REVISION}.`,
    'Assign exactly these lanes, keeping their node IDs and their exclusive file ownership unchanged:',
    JSON.stringify(LANES),
    '',
    'Return the lane list with a concrete brief for each lane. Ownership must not overlap:',
    'a file belongs to exactly one lane. Do not add or remove lanes.',
  ].join('\n'),
  { label: 'planner', phase: 'Plan', schema: PLAN_SCHEMA },
)

// A failed planner is a failed run, not an empty success.
if (!planned || !Array.isArray(planned.lanes) || !planned.lanes.length) {
  return {
    nodeId: 'integrator',
    status: 'failed',
    reason: 'planner produced no lanes',
    joinOk: false,
    sourceRevision: REVISION,
    workers: {},
    verdicts: [],
  }
}

const lanes = planned.lanes.filter(lane => lane && typeof lane.nodeId === 'string')
log(`planner declared ${lanes.length} lane(s) at revision ${REVISION}`)

// -- Implement --------------------------------------------------------------
phase('Implement')
const outputs = await parallel(
  lanes.map(lane => () =>
    agent(
      [
        `You are worker node ${lane.nodeId}. Work only inside the run workspace.`,
        'Specification:', SPEC,
        '', 'Your lane:', lane.brief,
        '',
        `You exclusively own these paths and MUST NOT write any other file: ${JSON.stringify(lane.owns || [])}.`,
        `The source revision you are working from is ${REVISION}; report it back verbatim as sourceRevision.`,
        `Report your own node ID verbatim as nodeId: ${lane.nodeId}.`,
        'Report artifactHash as the sha256 of your concatenated changed-file contents,',
        'computed with a shell command so it is reproducible.',
        'Report reproducible evidence: the exact commands you ran and their results.',
        'If you are blocked, set blocked=true and say so. A blocked lane is a valid result; do not fabricate one.',
      ].join('\n'),
      { label: lane.nodeId, phase: 'Implement', schema: WORKER_SCHEMA },
    ),
  ),
)

// parallel() resolves a stopped or terminally-failed agent to null. Index position is
// used ONLY to recover which lane a null belongs to; every surviving output is keyed by
// its own reported nodeId from here on.
const workers = {}
const missing = []
outputs.forEach((out, index) => {
  const laneId = lanes[index].nodeId
  if (!out || typeof out.nodeId !== 'string') {
    missing.push(laneId)
    return
  }
  if (out.nodeId !== laneId) {
    // A node that misreports its own stable ID is not silently re-keyed.
    missing.push(laneId)
    return
  }
  if (workers[out.nodeId]) {
    // Duplicate emission: keep the first, record the conflict rather than overwriting.
    workers[out.nodeId].duplicateSeen = true
    return
  }
  workers[out.nodeId] = out
})
if (missing.length) log(`missing or unusable worker output for: ${missing.join(', ')}`)

const present = Object.keys(workers).sort()
if (!present.length) {
  return {
    nodeId: 'integrator',
    status: 'failed',
    reason: 'no worker produced a usable output',
    joinOk: false,
    sourceRevision: REVISION,
    workers: {},
    verdicts: [],
    missing,
  }
}

// -- Review -----------------------------------------------------------------
// FRESH session. Specification + diff + reproducible evidence only. The worker
// conversation is never included, and the external evaluator is not consulted.
phase('Review')
const reviewed = await agent(
  [
    'You are an internal reviewer in a fresh session. You have not seen any worker conversation',
    'and must not ask for one. Judge only what is below plus the files it names.',
    '',
    'Specification:', SPEC,
    '',
    `Source revision under review: ${REVISION}.`,
    'Changes to review, one entry per worker node:',
    JSON.stringify(present.map(id => ({
      targetNodeId: id,
      sourceRevision: workers[id].sourceRevision,
      artifactHash: workers[id].artifactHash,
      files: workers[id].files,
      summary: workers[id].summary,
      evidence: workers[id].evidence || null,
    }))),
    '',
    'Read the named files and re-run the evidence commands yourself before deciding.',
    'Return one verdict per targetNodeId, echoing that entry\'s sourceRevision verbatim.',
    'Use verdict "unclear" when the evidence does not let you decide. Do not guess.',
  ].join('\n'),
  { label: 'reviewer', phase: 'Review', schema: VERDICT_SCHEMA },
)

// Join verdicts to worker outputs by stable ID + sourceRevision, never by position.
const verdicts = []
const staleVerdicts = []
for (const v of (reviewed && reviewed.verdicts) || []) {
  const target = workers[v.targetNodeId]
  if (!target) continue
  if (v.sourceRevision !== target.sourceRevision) {
    staleVerdicts.push(v)
    continue
  }
  verdicts.push(v)
}
if (staleVerdicts.length) log(`${staleVerdicts.length} stale verdict(s) discarded (revision mismatch)`)

const reviewedIds = new Set(verdicts.map(v => v.targetNodeId))
const unreviewed = present.filter(id => !reviewedIds.has(id))
const joinOk = missing.length === 0 && unreviewed.length === 0 && staleVerdicts.length === 0

// -- Integrate --------------------------------------------------------------
phase('Integrate')
const final = await agent(
  [
    'You are the integrator node. Combine the reviewed lanes into the final submission.',
    'Specification:', SPEC,
    '', `Source revision: ${REVISION}.`,
    'Worker outputs, keyed by stable node ID:', JSON.stringify(workers),
    'Reviewer verdicts that matched their worker\'s source revision:', JSON.stringify(verdicts),
    'Lanes with no usable output:', JSON.stringify(missing),
    'Lanes with no matching verdict:', JSON.stringify(unreviewed),
    'Stale verdicts discarded:', JSON.stringify(staleVerdicts),
    '',
    'Write SUBMISSION.md with the actual verification evidence and every remaining gap.',
    'Report missing lanes and rejected lanes honestly as gaps. An incomplete run is a valid',
    'experimental result; never present an empty or partial result as a success.',
    'You own SUBMISSION.md and must not modify any worker-owned file.',
  ].join('\n'),
  { label: 'integrator', phase: 'Integrate', schema: FINAL_SCHEMA },
)

return {
  nodeId: 'integrator',
  status: final ? (joinOk ? 'complete' : 'incomplete') : 'failed',
  joinOk,
  sourceRevision: REVISION,
  workers,
  verdicts,
  staleVerdicts,
  missing,
  unreviewed,
  final: final || null,
}
