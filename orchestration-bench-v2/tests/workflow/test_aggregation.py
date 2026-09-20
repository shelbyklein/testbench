"""OFFLINE validation: stable-ID aggregation and failure accounting at the join.

List position is never used. A failed or missing worker can never become a successful
empty result. No paid model call is made.
"""
import tempfile
import unittest

from adapters import claude_workflow as adapter
from bench_core import traces
from tests.workflow import fixtures

REV = 'rev-abc123'


def out(node_id, revision=REV, summary=None):
    return {'stableId': node_id, 'nodeId': node_id, 'sourceRevision': revision,
            'artifactHash': f'hash-{node_id}', 'summary': summary or f'output {node_id}'}


def verdict(node_id, revision=REV, value='approve'):
    return {'stableId': f'verdict:{node_id}', 'targetNodeId': node_id,
            'sourceRevision': revision, 'verdict': value, 'reason': 'fixture'}


def all_completed(*node_ids):
    joined = traces.JoinResult()
    for node_id in node_ids:
        joined[node_id] = 'completed'
    return joined


class StableIdJoinTest(unittest.TestCase):

    workflow = fixtures.workflow(
        [fixtures.node('worker-a'), fixtures.node('worker-b'), fixtures.node('worker-c'),
         fixtures.node('reviewer', role='reviewer',
                       depends_on=['worker-a', 'worker-b', 'worker-c'], phase='Review')],
        expected_workers=['worker-a', 'worker-b', 'worker-c'])

    def test_reordered_outputs_join_to_the_right_nodes(self):
        shuffled = [out('worker-c'), out('worker-a'), out('worker-b')]
        verdicts = [verdict('worker-b'), verdict('worker-c'), verdict('worker-a')]
        report = adapter.aggregate(self.workflow, shuffled, verdicts,
                                   all_completed('worker-a', 'worker-b', 'worker-c'))
        self.assertTrue(report['joinOk'])
        self.assertFalse(report['joinedByListIndex'])
        for node_id in ('worker-a', 'worker-b', 'worker-c'):
            self.assertEqual(report['workers'][node_id]['output']['stableId'], node_id)
            self.assertEqual(report['workers'][node_id]['verdicts'][0]['targetNodeId'], node_id)

    def test_identical_duplicate_is_ignored_not_double_counted(self):
        report = adapter.aggregate(self.workflow,
                                   [out('worker-a'), out('worker-a'), out('worker-b'),
                                    out('worker-c')],
                                   [verdict(n) for n in ('worker-a', 'worker-b', 'worker-c')],
                                   all_completed('worker-a', 'worker-b', 'worker-c'))
        self.assertEqual(report['duplicatesIgnored'], ['worker-a'])
        self.assertTrue(report['joinOk'])

    def test_conflicting_duplicate_is_a_conflict_not_an_overwrite(self):
        report = adapter.aggregate(self.workflow,
                                   [out('worker-a'), out('worker-a', summary='different'),
                                    out('worker-b'), out('worker-c')],
                                   [verdict(n) for n in ('worker-a', 'worker-b', 'worker-c')],
                                   all_completed('worker-a', 'worker-b', 'worker-c'))
        self.assertFalse(report['joinOk'])
        self.assertEqual(report['conflicts'][0]['stableId'], 'worker-a')
        # the first output is kept; the second never overwrites it
        self.assertEqual(report['workers']['worker-a']['output']['summary'], 'output worker-a')

    def test_missing_output_is_never_a_successful_empty_result(self):
        report = adapter.aggregate(self.workflow, [out('worker-a'), out('worker-c')],
                                   [verdict('worker-a'), verdict('worker-c')],
                                   all_completed('worker-a', 'worker-b', 'worker-c'))
        self.assertFalse(report['joinOk'])
        self.assertEqual(report['workers']['worker-b']['status'], 'missing-output')
        self.assertIsNone(report['workers']['worker-b']['output'])
        self.assertIn('worker-b', report['missing'])

    def test_failed_node_is_accounted_as_failed(self):
        joined = all_completed('worker-a', 'worker-c')
        joined['worker-b'] = 'failed'
        report = adapter.aggregate(self.workflow, [out('worker-a'), out('worker-c')],
                                   [verdict('worker-a'), verdict('worker-c')], joined)
        self.assertFalse(report['joinOk'])
        self.assertEqual(report['workers']['worker-b']['status'], 'failed')
        self.assertIn('worker-b', report['failed'])

    def test_stale_verdict_never_counts_as_an_approval(self):
        verdicts = [verdict('worker-a'), verdict('worker-b', revision='rev-OLD'),
                    verdict('worker-c')]
        report = adapter.aggregate(self.workflow,
                                   [out(n) for n in ('worker-a', 'worker-b', 'worker-c')],
                                   verdicts, all_completed('worker-a', 'worker-b', 'worker-c'))
        self.assertFalse(report['joinOk'])
        self.assertEqual(report['staleVerdicts'][0]['targetNodeId'], 'worker-b')
        self.assertEqual(report['workers']['worker-b']['verdicts'], [])
        self.assertIn('worker-b', report['unreviewed'])

    def test_orphan_verdict_for_an_unknown_node_is_surfaced(self):
        verdicts = [verdict(n) for n in ('worker-a', 'worker-b', 'worker-c')] + [verdict('ghost')]
        report = adapter.aggregate(self.workflow,
                                   [out(n) for n in ('worker-a', 'worker-b', 'worker-c')],
                                   verdicts, all_completed('worker-a', 'worker-b', 'worker-c'))
        self.assertEqual(len(report['orphanVerdicts']), 1)
        self.assertEqual(report['orphanVerdicts'][0]['targetNodeId'], 'ghost')

    def test_output_without_a_stable_id_is_a_conflict(self):
        report = adapter.aggregate(self.workflow, [{'summary': 'anonymous'}], [],
                                   all_completed('worker-a', 'worker-b', 'worker-c'))
        self.assertFalse(report['joinOk'])
        self.assertEqual(report['conflicts'][0]['stableId'], None)


class EndToEndJoinTest(unittest.TestCase):
    """Same guarantees through a full bench-controlled run."""

    def test_full_graph_joins_and_charges_the_reviewer_to_the_candidate(self):
        with tempfile.TemporaryDirectory() as workspace:
            events = []
            result = adapter.run(fixtures.graph_shape(), adapter.FakeExecutor(),
                                 fixtures.limits(), events, workspace, source_revision=REV)
            self.assertEqual(result['status'], 'complete')
            self.assertTrue(result['joinOk'])
            self.assertEqual(result['aggregate']['joinedBy'], ['stableId', 'sourceRevision'])
            reviewer_usage = [e for e in events
                              if e['type'] == 'usage' and e['role'] == 'reviewer']
            self.assertTrue(reviewer_usage)
            self.assertEqual(reviewer_usage[0]['payload']['chargedTo'], 'candidate')

    def test_failed_worker_surfaces_in_the_join_and_blocks_success(self):
        with tempfile.TemporaryDirectory() as workspace:
            result = adapter.run(fixtures.graph_shape(),
                                 adapter.FakeExecutor(behaviors={'worker-b': 'fail'}),
                                 fixtures.limits(), [], workspace, source_revision=REV)
            self.assertEqual(result['join']['worker-b'], 'failed')
            self.assertFalse(result['joinOk'])
            self.assertEqual(result['status'], 'incomplete')
            self.assertIn('worker-b', result['aggregate']['failed'])

    def test_stale_reviewer_verdicts_block_success_end_to_end(self):
        with tempfile.TemporaryDirectory() as workspace:
            result = adapter.run(fixtures.graph_shape(),
                                 adapter.FakeExecutor(behaviors={'reviewer': 'stale_verdict'}),
                                 fixtures.limits(), [], workspace, source_revision=REV)
            self.assertFalse(result['joinOk'])
            self.assertTrue(result['aggregate']['staleVerdicts'])

    def test_duplicate_worker_emission_is_deduplicated(self):
        with tempfile.TemporaryDirectory() as workspace:
            result = adapter.run(fixtures.graph_shape(),
                                 adapter.FakeExecutor(behaviors={'worker-a': 'duplicate'}),
                                 fixtures.limits(), [], workspace, source_revision=REV)
            self.assertEqual(result['aggregate']['duplicatesIgnored'], ['worker-a'])
            self.assertTrue(result['joinOk'])

    def test_completed_node_with_no_output_is_not_a_success(self):
        with tempfile.TemporaryDirectory() as workspace:
            result = adapter.run(fixtures.graph_shape(),
                                 adapter.FakeExecutor(behaviors={'worker-a': 'missing_output'}),
                                 fixtures.limits(), [], workspace, source_revision=REV)
            self.assertEqual(result['join']['worker-a'], 'completed')
            self.assertEqual(result['aggregate']['workers']['worker-a']['status'],
                             'missing-output')
            self.assertFalse(result['joinOk'])

    def test_reviewer_inputs_exclude_the_worker_conversation(self):
        captured = {}

        class Recording(adapter.FakeExecutor):
            def execute(self, task):
                if task.role == 'reviewer':
                    captured['inputs'] = dict(task.inputs)
                return adapter.FakeExecutor.execute(self, task)

        with tempfile.TemporaryDirectory() as workspace:
            adapter.run(fixtures.graph_shape(), Recording(), fixtures.limits(), [], workspace,
                        source_revision=REV)
        inputs = captured['inputs']
        self.assertEqual(sorted(inputs), ['evidence', 'excluded', 'specification',
                                          'workerOutputs'])
        # the reviewer receives specification + outputs + evidence, and nothing else
        for key in inputs:
            self.assertNotIn('conversation', key.lower())
            self.assertNotIn('transcript', key.lower())
        self.assertIn('worker-conversation', inputs['excluded'])
        self.assertIn('planner-conversation', inputs['excluded'])
        self.assertIn('external-evaluator-output', inputs['excluded'])


if __name__ == '__main__':
    unittest.main()
