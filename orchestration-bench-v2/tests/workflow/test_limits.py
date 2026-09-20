"""OFFLINE validation: the four limits the bench really enforces.

Concurrency, worker count, total attempts and elapsed time. The elapsed-time test spawns
a real sleeping child process and asserts the bench reaped it. No paid model call is made.
"""
import errno
import os
import tempfile
import unittest
from pathlib import Path

from adapters import claude_workflow as adapter
from tests.workflow import fixtures


def _alive(pid):
    try:
        os.kill(pid, 0)
    except OSError as error:
        return error.errno != errno.ESRCH
    return True


class ConcurrencyCapTest(unittest.TestCase):
    """Peak simultaneous execution never exceeds max_concurrency."""

    def test_peak_concurrency_is_bounded(self):
        for cap in (1, 2, 3):
            with self.subTest(cap=cap), tempfile.TemporaryDirectory() as workspace:
                events = []
                result = adapter.run(
                    fixtures.flat_workers(8), adapter.FakeExecutor(step_seconds=0.05),
                    fixtures.limits(max_concurrency=cap, max_workers=8), events, workspace)
                self.assertLessEqual(result['peakConcurrency'], cap)
                self.assertEqual(result['limits']['max_concurrency']['enforcement'], 'enforced')

    def test_a_higher_cap_actually_overlaps(self):
        """Guards against the cap passing only because nothing ever ran in parallel."""
        with tempfile.TemporaryDirectory() as workspace:
            result = adapter.run(
                fixtures.flat_workers(8), adapter.FakeExecutor(step_seconds=0.15),
                fixtures.limits(max_concurrency=4, max_workers=8), [], workspace)
            self.assertGreater(result['peakConcurrency'], 1)
            self.assertLessEqual(result['peakConcurrency'], 4)


class WorkerCapTest(unittest.TestCase):

    def test_surplus_workers_are_skipped_not_silently_dropped(self):
        with tempfile.TemporaryDirectory() as workspace:
            events = []
            result = adapter.run(fixtures.flat_workers(5), adapter.FakeExecutor(),
                                 fixtures.limits(max_workers=2, max_concurrency=2),
                                 events, workspace)
            self.assertEqual(len(result['skippedForWorkerLimit']), 3)
            skipped = [e for e in events if e['type'] == 'node_skipped']
            self.assertEqual(len(skipped), 3)
            self.assertEqual({e['payload']['limit'] for e in skipped}, {'max_workers'})
            # skipped workers are accounted, and the run is NOT a success
            self.assertFalse(result['joinOk'])
            self.assertEqual(result['status'], 'incomplete')
            for node_id in result['skippedForWorkerLimit']:
                self.assertEqual(result['join'][node_id], 'skipped')


class AttemptCapTest(unittest.TestCase):

    def test_total_attempts_are_capped_across_all_nodes(self):
        with tempfile.TemporaryDirectory() as workspace:
            events = []
            workflow = fixtures.flat_workers(3, max_attempts_per_node=3)
            executor = adapter.FakeExecutor(behaviors={f'worker-{i}': 'fail_times:2'
                                                       for i in range(3)})
            result = adapter.run(workflow, executor,
                                 fixtures.limits(max_attempts_total=4, max_concurrency=1),
                                 events, workspace)
            self.assertEqual(result['attemptsUsed'], 4)
            self.assertEqual(len(executor.executed), 4)
            self.assertEqual(result['limits']['max_attempts_total']['enforcement'], 'enforced')
            canceled = [e for e in events if e['type'] == 'node_canceled'
                        and e['payload'].get('limit') == 'max_attempts_total']
            self.assertTrue(canceled)
            self.assertFalse(result['joinOk'])

    def test_retries_are_allowed_within_the_budget(self):
        with tempfile.TemporaryDirectory() as workspace:
            workflow = fixtures.flat_workers(1, max_attempts_per_node=3)
            result = adapter.run(workflow,
                                 adapter.FakeExecutor(behaviors={'worker-0': 'fail_times:2'}),
                                 fixtures.limits(max_attempts_total=5), [], workspace)
            self.assertEqual(result['attemptsUsed'], 3)
            self.assertTrue(result['joinOk'])


class ElapsedCapAndReapTest(unittest.TestCase):
    """A real sleeping child process must be gone once the run returns."""

    def test_timeout_stops_the_run_and_reaps_the_owned_child(self):
        with tempfile.TemporaryDirectory() as workspace:
            events = []
            executor = adapter.FakeExecutor(behaviors={'worker-0': 'spawn_child_and_hang'},
                                            child_seconds=120)
            result = adapter.run(fixtures.flat_workers(1), executor,
                                 fixtures.limits(max_elapsed_seconds=1.0, max_concurrency=1),
                                 events, workspace)

            self.assertTrue(result['timedOut'])
            self.assertEqual(result['status'], 'timed-out')
            self.assertEqual(len(result['ownedProcesses']), 1)
            pid = result['ownedProcesses'][0]
            self.assertIn(pid, result['reapedProcesses'])
            self.assertFalse(_alive(pid), f'child {pid} survived the elapsed-time limit')

            canceled = [e for e in events if e['type'] == 'node_canceled']
            self.assertTrue(canceled)
            self.assertEqual(canceled[0]['payload']['limit'], 'max_elapsed_seconds')
            self.assertFalse(result['joinOk'])

    def test_the_spawned_child_is_this_interpreter_not_a_model_cli(self):
        """FakeExecutor's only possible subprocess is python sleeping."""
        import sys
        self.assertEqual(adapter.FakeExecutor.CHILD_ARGV_HEAD, (sys.executable, '-c'))
        self.assertEqual(Path(sys.executable).name.split('.')[0][:6], 'python')


class EnforcementLabelTest(unittest.TestCase):

    def test_token_and_cost_limits_are_never_labelled_enforced(self):
        plain = adapter.Limits.coerce(fixtures.limits()).enforcement()
        self.assertEqual(plain['max_tokens']['enforcement'], 'unavailable')
        self.assertEqual(plain['max_cost_usd']['enforcement'], 'unavailable')

        supplied = adapter.Limits.coerce(
            fixtures.limits(max_tokens=1_000_000, max_cost_usd=25.0)).enforcement()
        self.assertEqual(supplied['max_tokens']['enforcement'], 'advisory')
        self.assertEqual(supplied['max_cost_usd']['enforcement'], 'advisory')
        for key in ('max_concurrency', 'max_workers', 'max_attempts_total', 'max_elapsed_seconds'):
            self.assertEqual(supplied[key]['enforcement'], 'enforced')

    def test_unknown_limit_keys_are_rejected(self):
        with self.assertRaises(ValueError):
            adapter.Limits.coerce({'max_tokens_really': 5})


if __name__ == '__main__':
    unittest.main()
