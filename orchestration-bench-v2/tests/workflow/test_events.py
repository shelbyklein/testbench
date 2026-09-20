"""OFFLINE validation: every emitted event satisfies trace-event/1 and is synthetic.

The adapter is exercised against both sink shapes (a plain list and a real TraceStore).
No paid model call is made.
"""
import tempfile
import unittest
from pathlib import Path

from adapters import claude_workflow as adapter
from bench_core import traces
from tests.workflow import fixtures

REV = 'rev-events'


def run_full(workspace, sink, **kwargs):
    return adapter.run(fixtures.graph_shape(), adapter.FakeExecutor(), fixtures.limits(),
                       sink, workspace, scenario='S6', run_id='run-abc123',
                       experiment_id='exp-offline', source_revision=REV, **kwargs)


class EmittedEventTest(unittest.TestCase):

    def test_every_event_validates_and_is_marked_synthetic(self):
        with tempfile.TemporaryDirectory() as workspace:
            events = []
            run_full(workspace, events)
            self.assertTrue(events)
            for event in events:
                traces.validate_event(event)
                self.assertTrue(event['synthetic'], f'{event["type"]} is not marked synthetic')
                self.assertEqual(event['schema'], 'trace-event/1')
                self.assertEqual(event['evidence']['importer'], adapter.IMPORTER)
                self.assertEqual(event['evidence']['importerVersion'], adapter.VERSION)
                self.assertEqual(event['clock']['source'], 'synthetic')
                self.assertEqual(event['runId'], 'run-abc123')
                self.assertEqual(event['experimentId'], 'exp-offline')

    def test_the_expected_event_types_are_emitted(self):
        with tempfile.TemporaryDirectory() as workspace:
            events = []
            run_full(workspace, events)
            kinds = {event['type'] for event in events}
            self.assertLessEqual({'node_declared', 'node_started', 'node_completed', 'usage'},
                                 kinds)

    def test_failure_cancellation_skip_fault_and_restart_types_all_appear(self):
        seen = set()
        # failure + cancellation via an attempt budget
        with tempfile.TemporaryDirectory() as workspace:
            events = []
            adapter.run(fixtures.flat_workers(3, max_attempts_per_node=2),
                        adapter.FakeExecutor(behaviors={f'worker-{i}': 'fail' for i in range(3)}),
                        fixtures.limits(max_attempts_total=3, max_concurrency=1),
                        events, workspace, source_revision=REV)
            seen |= {e['type'] for e in events}
        # skip via the worker cap
        with tempfile.TemporaryDirectory() as workspace:
            events = []
            adapter.run(fixtures.flat_workers(3), adapter.FakeExecutor(),
                        fixtures.limits(max_workers=1, max_concurrency=1), events, workspace)
            seen |= {e['type'] for e in events}
        # fault + restart
        with tempfile.TemporaryDirectory() as workspace:
            events = []
            adapter.run(fixtures.flat_workers(2), adapter.FakeExecutor(),
                        fixtures.limits(max_concurrency=1), events, workspace,
                        source_revision=REV,
                        fault_plan=adapter.FaultPlan('first_persisted_ack', 'crash',
                                                     node_id='worker-1'))
            adapter.run(fixtures.flat_workers(2), adapter.FakeExecutor(),
                        fixtures.limits(max_concurrency=1), events, workspace,
                        source_revision=REV)
            seen |= {e['type'] for e in events}
        for kind in ('node_declared', 'node_started', 'node_completed', 'node_failed',
                     'node_canceled', 'node_skipped', 'usage', 'fault', 'restart'):
            self.assertIn(kind, seen)

    def test_events_are_accepted_by_a_real_trace_store(self):
        with tempfile.TemporaryDirectory() as workspace:
            store = traces.TraceStore(Path(workspace) / 'trace.jsonl')
            result = run_full(workspace, store)
            self.assertEqual(len(store), len(result['events']))
            self.assertTrue(store.synthetic('run-abc123'))
            declared = store.declared_graph('run-abc123')
            self.assertEqual(sorted(declared['nodes']),
                             ['integrator', 'planner', 'reviewer', 'worker-a', 'worker-b'])
            join = store.join(['worker-a', 'worker-b'], 'run-abc123')
            self.assertTrue(join.join_ok)
            self.assertEqual(dict(join), dict(result['join']))

    def test_store_join_and_adapter_join_agree_on_a_failure(self):
        with tempfile.TemporaryDirectory() as workspace:
            store = traces.TraceStore(Path(workspace) / 'trace.jsonl')
            result = adapter.run(fixtures.graph_shape(),
                                 adapter.FakeExecutor(behaviors={'worker-a': 'fail'}),
                                 fixtures.limits(), store, workspace, run_id='run-fail',
                                 source_revision=REV)
            join = store.join(['worker-a', 'worker-b'], 'run-fail')
            self.assertEqual(dict(join), dict(result['join']))
            self.assertEqual(join['worker-a'], 'failed')
            self.assertFalse(join.join_ok)

    def test_reimporting_the_same_events_is_idempotent(self):
        with tempfile.TemporaryDirectory() as workspace:
            path = Path(workspace) / 'trace.jsonl'
            store = traces.TraceStore(path)
            result = run_full(workspace, store)
            again = traces.TraceStore(path).add(result['events'])
            self.assertEqual(again['added'], 0)
            self.assertEqual(again['duplicates'], len(result['events']))

    def test_usage_events_carry_measurement_objects_with_honest_provenance(self):
        with tempfile.TemporaryDirectory() as workspace:
            events = []
            run_full(workspace, events)
            usage_events = [e for e in events if e['type'] == 'usage']
            self.assertTrue(usage_events)
            for event in usage_events:
                usage = event['usage']
                self.assertEqual(usage['scope'], 'self')
                self.assertEqual(usage['durationSeconds']['provenance'], 'measured')
                for key in ('inputTokens', 'outputTokens', 'costUSD'):
                    self.assertIsNone(usage[key]['value'])
                    self.assertEqual(usage[key]['provenance'], 'unavailable')

    def test_declared_nodes_carry_their_limits_and_honest_enforcement_labels(self):
        with tempfile.TemporaryDirectory() as workspace:
            events = []
            run_full(workspace, events)
            declared = [e for e in events if e['type'] == 'node_declared']
            self.assertTrue(declared)
            limits = declared[0]['payload']['limits']
            self.assertEqual(limits['max_concurrency']['enforcement'], 'enforced')
            self.assertEqual(limits['max_tokens']['enforcement'], 'unavailable')
            self.assertEqual(limits['max_cost_usd']['enforcement'], 'unavailable')

    def test_model_and_settings_stay_unverified_on_every_event(self):
        with tempfile.TemporaryDirectory() as workspace:
            events = []
            run_full(workspace, events)
            for event in events:
                self.assertIsNone(event['model']['effective'])
                self.assertFalse(event['model']['verified'])
                self.assertIsNone(event['settings']['effective'])
                self.assertFalse(event['settings']['verified'])

    def test_event_ids_are_unique(self):
        with tempfile.TemporaryDirectory() as workspace:
            events = []
            run_full(workspace, events)
            ids = [e['eventId'] for e in events]
            self.assertEqual(len(ids), len(set(ids)))

    def test_declared_and_observed_graphs_are_kept_distinct(self):
        with tempfile.TemporaryDirectory() as workspace:
            store = traces.TraceStore(Path(workspace) / 'trace.jsonl')
            adapter.run(fixtures.graph_shape(), adapter.FakeExecutor(),
                        fixtures.limits(max_workers=1), store, workspace, run_id='run-part',
                        source_revision=REV)
            declared = store.declared_graph('run-part')
            observed = store.observed_graph('run-part')
            self.assertIn('worker-b', declared['nodes'])
            self.assertEqual(observed['nodes']['worker-b']['role'], 'worker')
            self.assertLess(len([n for n in observed['nodes'].values()]),
                            len(declared['nodes']) + 1)


if __name__ == '__main__':
    unittest.main()
