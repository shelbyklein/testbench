export const meta = {
  name: 'solo-candidate',
  description: 'Orchestration Bench v2 single-node control: one agent does the whole task, with the same milestone and restart machinery as the graph candidate.',
  whenToUse: 'Bench control arm only. Use when a single-node run must pass through the identical bench-controlled harness, milestone fault hook and restart path as the graph candidate.',
  phases: [
    { title: 'Implement', detail: 'one agent does the whole task' },
  ],
}

// ---------------------------------------------------------------------------
// solo.v1 -- versioned single-node counterpart of graph-candidate.v1.
//
// It exists so that the fault hook (keyed by milestone string) and the restart
// path are exercised identically for one node and for a graph; the S6 scenario
// lane reuses the same FaultPlan(milestone, kind) against this definition.
//
// No agent() call sets `model` or `effort`, so a solo arm and a graph arm
// inherit the same session settings and stay comparable.
//
// Expected `args`:
//   { runId, scenarioId, repeat, workspace, sourceRevision, specification }
// ---------------------------------------------------------------------------

const input = args || {}
const SPEC = input.specification || 'See TASK.md in the workspace for the complete request and acceptance contract.'
const REVISION = input.sourceRevision || 'unknown-revision'

const FINAL_SCHEMA = {
  type: 'object',
  required: ['nodeId', 'sourceRevision', 'artifactHash', 'summary'],
  properties: {
    nodeId: { type: 'string' },
    sourceRevision: { type: 'string' },
    artifactHash: { type: 'string' },
    summary: { type: 'string' },
    unresolved: { type: 'array', items: { type: 'string' } },
    blocked: { type: 'boolean' },
  },
}

phase('Implement')
const final = await agent(
  [
    'You are the single implementer node. Do the whole task yourself in the run workspace.',
    'Specification:', SPEC,
    '',
    `The source revision you are working from is ${REVISION}; report it back verbatim as sourceRevision.`,
    'Report your node ID verbatim as nodeId: solo.',
    'Report artifactHash as the sha256 of your concatenated changed-file contents,',
    'computed with a shell command so it is reproducible.',
    'Normal self-review and running the tests are allowed; no second agent is involved.',
    'Write SUBMISSION.md with the actual verification evidence and every remaining gap.',
    'A blocked or unfinished task is a valid experimental result; report it honestly',
    'rather than presenting a partial result as a success.',
  ].join('\n'),
  { label: 'solo', phase: 'Implement', schema: FINAL_SCHEMA },
)

return {
  nodeId: 'solo',
  status: final ? 'complete' : 'failed',
  joinOk: Boolean(final),
  sourceRevision: REVISION,
  final: final || null,
}
