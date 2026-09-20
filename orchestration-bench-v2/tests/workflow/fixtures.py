"""Synthetic workflow definitions for the offline adapter tests.

These are fixtures, not shipped workflows. The shipped, versioned definitions are
`adapters/claude_workflow/workflow/workflow.json` (graph) and `.../solo.json` (single node).
"""

SYNTHETIC = True


def node(node_id, role='worker', depends_on=(), owns=(), phase='Implement'):
    return {'id': node_id, 'role': role, 'label': node_id, 'phase': phase,
            'dependsOn': list(depends_on), 'inputs': [], 'outputs': [],
            'owns': list(owns), 'freshSession': True, 'chargedToCandidate': True}


def workflow(nodes, expected_workers=None, max_attempts_per_node=1, workflow_id='fixture'):
    return {
        'contract': 'workflow-definition/1',
        'id': workflow_id,
        'version': '1.0.0',
        'script': 'adapters/claude_workflow/workflow/graph-candidate.v1.js',
        'scriptVersion': 'graph-candidate.v1',
        'nodes': nodes,
        'join': {'by': ['nodeId', 'sourceRevision'], 'byListIndex': False,
                 'expectedWorkers': list(expected_workers) if expected_workers is not None
                 else [n['id'] for n in nodes if n['role'] == 'worker']},
        'retry': {'maxAttemptsPerNode': max_attempts_per_node, 'retryableStatuses': ['failed']},
        'exclusiveOwnership': {},
        'finalArtifact': {'producedBy': nodes[-1]['id'], 'paths': ['SUBMISSION.md']},
        'milestones': ['first_persisted_ack'],
    }


def flat_workers(count, max_attempts_per_node=1):
    """`count` independent worker nodes with no dependencies."""
    return workflow([node(f'worker-{i}') for i in range(count)],
                    max_attempts_per_node=max_attempts_per_node)


def graph_shape(max_attempts_per_node=1):
    """planner -> 2 workers -> reviewer -> integrator, the shipped shape in miniature."""
    return workflow([
        node('planner', role='planner', phase='Plan'),
        node('worker-a', depends_on=['planner'], owns=['a.mjs']),
        node('worker-b', depends_on=['planner'], owns=['b.mjs']),
        node('reviewer', role='reviewer', depends_on=['worker-a', 'worker-b'], phase='Review'),
        node('integrator', role='integrator',
             depends_on=['worker-a', 'worker-b', 'reviewer'], owns=['SUBMISSION.md'],
             phase='Integrate'),
    ], expected_workers=['worker-a', 'worker-b'],
        max_attempts_per_node=max_attempts_per_node)


LIMITS = {'max_concurrency': 4, 'max_workers': 8,
          'max_attempts_total': 32, 'max_elapsed_seconds': 30.0}


def limits(**overrides):
    merged = dict(LIMITS)
    merged.update(overrides)
    return merged
