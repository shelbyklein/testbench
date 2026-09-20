"""OFFLINE validation: deterministic restart from a semantic-milestone crash.

Completed nodes are reused only after an explicit source-revision AND artifact-hash
identity check, and no externally visible effect is duplicated (proved with an
append-only effects log). The same FaultPlan works unchanged against the single-node
`solo` workflow, which the S6 scenario lane reuses. No paid model call is made.
"""
import tempfile
import unittest
from pathlib import Path

from adapters import claude_workflow as adapter
from tests.workflow import fixtures

REV = 'rev-restart-1'
MILESTONE = 'first_persisted_ack'


def chain():
    """worker-0 -> worker-1 -> worker-2, so a crash leaves a recorded prefix."""
    return fixtures.workflow([
        fixtures.node('worker-0'),
        fixtures.node('worker-1', depends_on=['worker-0']),
        fixtures.node('worker-2', depends_on=['worker-1']),
    ])


class FaultPlanTest(unittest.TestCase):

    def test_fires_once_and_only_for_its_milestone(self):
        plan = adapter.FaultPlan(MILESTONE, 'crash')
        self.assertFalse(plan.claim('other_milestone', 'worker-0', 1))
        self.assertTrue(plan.claim(MILESTONE, 'worker-0', 1))
        self.assertFalse(plan.claim(MILESTONE, 'worker-0', 1))
        plan.reset()
        self.assertTrue(plan.claim(MILESTONE, 'worker-0', 1))

    def test_node_and_attempt_filters(self):
        plan = adapter.FaultPlan(MILESTONE, 'fail', node_id='worker-1', attempt=2)
        self.assertFalse(plan.claim(MILESTONE, 'worker-0', 2))
        self.assertFalse(plan.claim(MILESTONE, 'worker-1', 1))
        self.assertTrue(plan.claim(MILESTONE, 'worker-1', 2))

    def test_rejects_an_unknown_kind_or_an_empty_milestone(self):
        with self.assertRaises(ValueError):
            adapter.FaultPlan(MILESTONE, 'explode')
        with self.assertRaises(ValueError):
            adapter.FaultPlan('  ', 'crash')


class EffectsLogTest(unittest.TestCase):

    def test_append_once_is_idempotent_across_instances(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'effects.log'
            self.assertTrue(adapter.EffectsLog(path).append_once('k', 1))
            self.assertFalse(adapter.EffectsLog(path).append_once('k', 1))
            self.assertFalse(adapter.EffectsLog(path).append_once('k', 2))
            self.assertEqual(adapter.EffectsLog(path).keys(), ['k'])


class RestartTest(unittest.TestCase):

    def _crash_then_restart(self, workspace, node_id='worker-1'):
        plan = adapter.FaultPlan(MILESTONE, 'crash', node_id=node_id)
        first = adapter.run(chain(), adapter.FakeExecutor(), fixtures.limits(max_concurrency=1),
                            [], workspace, source_revision=REV, fault_plan=plan)
        second = adapter.run(chain(), adapter.FakeExecutor(), fixtures.limits(max_concurrency=1),
                             [], workspace, source_revision=REV, fault_plan=None)
        return first, second

    def test_crash_aborts_the_run_and_is_recorded_as_a_fault(self):
        with tempfile.TemporaryDirectory() as workspace:
            events = []
            plan = adapter.FaultPlan(MILESTONE, 'crash', node_id='worker-1')
            result = adapter.run(chain(), adapter.FakeExecutor(),
                                 fixtures.limits(max_concurrency=1), events, workspace,
                                 source_revision=REV, fault_plan=plan)
            self.assertEqual(result['status'], 'crashed')
            self.assertEqual(result['crash']['milestone'], MILESTONE)
            self.assertEqual(result['crash']['nodeId'], 'worker-1')
            self.assertFalse(result['joinOk'])
            faults = [e for e in events if e['type'] == 'fault']
            self.assertEqual(len(faults), 1)
            self.assertEqual(faults[0]['payload']['milestone'], MILESTONE)
            self.assertTrue(faults[0]['payload']['injected'])

    def test_restart_reuses_the_completed_prefix_and_finishes(self):
        with tempfile.TemporaryDirectory() as workspace:
            first, second = self._crash_then_restart(workspace)
            self.assertEqual(first['status'], 'crashed')
            self.assertEqual(second['status'], 'complete')
            self.assertTrue(second['joinOk'])
            self.assertIn('worker-0', second['reusedNodes'])
            self.assertNotIn('worker-1', second['reusedNodes'])
            reuse = {r['nodeId']: r for r in second['replay']}
            self.assertTrue(reuse['worker-0']['reused'])
            self.assertIn('source revision', reuse['worker-0']['reason'])
            self.assertIn('artifact hash', reuse['worker-0']['reason'])

    def test_restart_is_deterministic(self):
        runs = []
        for _ in range(2):
            with tempfile.TemporaryDirectory() as workspace:
                first, second = self._crash_then_restart(workspace)
                runs.append((first['nodeStatus'], second['nodeStatus'],
                             second['reusedNodes'], [e['key'] for e in second['effects']]))
        self.assertEqual(runs[0], runs[1])

    def test_no_externally_visible_effect_is_duplicated(self):
        with tempfile.TemporaryDirectory() as workspace:
            _, second = self._crash_then_restart(workspace)
            keys = [entry['key'] for entry in second['effects']]
            self.assertEqual(sorted(keys), ['worker-0:persisted', 'worker-1:persisted',
                                            'worker-2:persisted'])
            self.assertEqual(len(keys), len(set(keys)), 'an effect was applied twice')

    def test_reuse_is_refused_when_the_source_revision_changed(self):
        with tempfile.TemporaryDirectory() as workspace:
            adapter.run(chain(), adapter.FakeExecutor(), fixtures.limits(max_concurrency=1),
                        [], workspace, source_revision=REV,
                        fault_plan=adapter.FaultPlan(MILESTONE, 'crash', node_id='worker-1'))
            second = adapter.run(chain(), adapter.FakeExecutor(),
                                 fixtures.limits(max_concurrency=1), [], workspace,
                                 source_revision='rev-DIFFERENT')
            self.assertEqual(second['reusedNodes'], [])
            reasons = {r['nodeId']: r['reason'] for r in second['replay']}
            self.assertIn('source revision changed', reasons['worker-0'])

    def test_reuse_is_refused_when_the_artifact_hash_changed(self):
        with tempfile.TemporaryDirectory() as workspace:
            adapter.run(chain(), adapter.FakeExecutor(), fixtures.limits(max_concurrency=1),
                        [], workspace, source_revision=REV,
                        fault_plan=adapter.FaultPlan(MILESTONE, 'crash', node_id='worker-1'))
            tampered = adapter.FakeExecutor(artifact_hashes={'worker-0': 'hash-changed'})
            second = adapter.run(chain(), tampered, fixtures.limits(max_concurrency=1),
                                 [], workspace, source_revision=REV)
            self.assertNotIn('worker-0', second['reusedNodes'])
            reasons = {r['nodeId']: r['reason'] for r in second['replay']}
            self.assertIn('artifact hash changed', reasons['worker-0'])

    def test_replay_behaviour_is_logged_as_a_restart_event(self):
        with tempfile.TemporaryDirectory() as workspace:
            adapter.run(chain(), adapter.FakeExecutor(), fixtures.limits(max_concurrency=1),
                        [], workspace, source_revision=REV,
                        fault_plan=adapter.FaultPlan(MILESTONE, 'crash', node_id='worker-1'))
            events = []
            adapter.run(chain(), adapter.FakeExecutor(), fixtures.limits(max_concurrency=1),
                        events, workspace, source_revision=REV)
            restarts = [e for e in events if e['type'] == 'restart']
            self.assertEqual(len(restarts), 1)
            payload = restarts[0]['payload']
            self.assertEqual(payload['identityChecks'], ['sourceRevision', 'artifactHash'])
            self.assertFalse(payload['nativeReplayRelied'])
            self.assertIn('worker-0', payload['reusedNodes'])

    def test_reused_node_is_not_re_executed(self):
        with tempfile.TemporaryDirectory() as workspace:
            adapter.run(chain(), adapter.FakeExecutor(), fixtures.limits(max_concurrency=1),
                        [], workspace, source_revision=REV,
                        fault_plan=adapter.FaultPlan(MILESTONE, 'crash', node_id='worker-1'))
            executor = adapter.FakeExecutor()
            adapter.run(chain(), executor, fixtures.limits(max_concurrency=1), [], workspace,
                        source_revision=REV)
            self.assertNotIn('worker-0', [node_id for node_id, _ in executor.executed])


class SoloFaultHookTest(unittest.TestCase):
    """The identical milestone hook drives the shipped single-node `solo` workflow.

    The S6 scenario lane reuses exactly this: `FaultPlan(milestone, kind)` plus
    `adapter.load_workflow(adapter.SOLO_WORKFLOW)`.
    """

    def test_solo_workflow_crashes_at_the_same_milestone_and_restarts_cleanly(self):
        solo = adapter.load_workflow(adapter.SOLO_WORKFLOW)
        with tempfile.TemporaryDirectory() as workspace:
            crashed = adapter.run(solo, adapter.FakeExecutor(),
                                  fixtures.limits(max_concurrency=1, max_workers=1),
                                  [], workspace, source_revision=REV,
                                  fault_plan=adapter.FaultPlan(MILESTONE, 'crash'))
            self.assertEqual(crashed['status'], 'crashed')
            self.assertEqual(crashed['crash']['nodeId'], 'solo')

            resumed = adapter.run(solo, adapter.FakeExecutor(),
                                  fixtures.limits(max_concurrency=1, max_workers=1),
                                  [], workspace, source_revision=REV)
            self.assertEqual(resumed['nodeStatus']['solo'], 'completed')
            keys = [entry['key'] for entry in resumed['effects']]
            self.assertEqual(keys, ['solo:persisted'])

    def test_solo_workflow_accepts_the_fail_and_hang_kinds_too(self):
        solo = adapter.load_workflow(adapter.SOLO_WORKFLOW)
        with tempfile.TemporaryDirectory() as workspace:
            result = adapter.run(solo, adapter.FakeExecutor(),
                                 fixtures.limits(max_concurrency=1, max_workers=1),
                                 [], workspace, source_revision=REV,
                                 fault_plan=adapter.FaultPlan(MILESTONE, 'fail'))
            self.assertEqual(result['nodeStatus']['solo'], 'completed')  # retry policy is 2
        with tempfile.TemporaryDirectory() as workspace:
            result = adapter.run(solo, adapter.FakeExecutor(),
                                 fixtures.limits(max_concurrency=1, max_workers=1,
                                                 max_elapsed_seconds=1.0),
                                 [], workspace, source_revision=REV,
                                 fault_plan=adapter.FaultPlan(MILESTONE, 'hang'))
            self.assertTrue(result['timedOut'])


if __name__ == '__main__':
    unittest.main()
