"""S6 interruption and recovery: calibration, intended failure reasons, and a bench-level
recovery harness.

EVERYTHING HERE IS OFFLINE AND SYNTHETIC. The bench-level harness drives `FakeExecutor`
workers through the merged workflow adapter, so what it establishes is that *the bench*
observes, records and scores an interruption honestly. It is **simulated worker recovery,
not a verified real coding-agent restart**: no provider is contacted, no model call is made,
and the "process kill" is an injected exception at a semantic milestone rather than a signal
to a real process.
"""
import json
import tempfile
import unittest
from pathlib import Path

from tests.scenarios import support
from bench_core import registry, metrics, traces
from adapters import claude_workflow as adapter

PACK = support.ROOT / 'scenario_packs' / 'S6'
REFERENCE = PACK / 'private' / 'reference'
KNOWN_BAD = PACK / 'private' / 'known_bad'

MILESTONE = 'first_persisted_ack'
REV = 'rev-s6-1'


# --------------------------------------------------------------------------- pack
class CalibrationTest(unittest.TestCase):
    def test_reference_passes_every_check(self):
        report = support.grade('S6', REFERENCE)
        self.assertTrue(report['allPassed'], support.failed_ids(report))
        self.assertEqual(report['details']['failed'], [])

    def test_calibrate_catches_every_known_bad(self):
        report = registry.calibrate(support.scenario('S6'), support.ROOT)
        self.assertEqual(report['status'], 'ok', report['problems'])
        self.assertEqual([f['id'] for f in report['known_bad']],
                         ['duplicate-effects', 'lost-progress', 'swallowed-failure',
                          'non-durable-ack'])
        for fixture in report['known_bad']:
            self.assertTrue(fixture['detected'], fixture)

    def test_registry_validate_stays_clean_with_s6(self):
        self.assertEqual(registry.validate(support.ROOT), [])
        scenario = support.scenario('S6')
        self.assertEqual(scenario['contract'], 'scenario/1')
        self.assertFalse(scenario.get('baseline_regression_gate', False))
        # data/ holds the shipped saved records the grader needs, so it is never excluded.
        self.assertEqual(scenario['participant'].get('runtime_paths') or [], [])

    def test_grading_the_reference_twice_is_identical(self):
        self.assertEqual(support.grade('S6', REFERENCE), support.grade('S6', REFERENCE))

    def test_the_milestone_is_semantic_not_a_call_count(self):
        report = support.grade('S6', REFERENCE)
        self.assertEqual(report['details']['milestone'], MILESTONE)
        self.assertIn('durably', report['details']['milestoneDefinition'])
        grader = (PACK / 'private' / 'grade.mjs').read_text()
        self.assertIn('SEMANTIC milestone', grader)


class StartStateTest(unittest.TestCase):
    def test_the_unmodified_start_state_fails_the_grader(self):
        report = support.grade('S6', PACK / 'participant')
        self.assertFalse(report['allPassed'])
        failed = support.failed_ids(report)
        for check_id in ('R2', 'R3', 'R4', 'R5', 'R7', 'R8'):
            self.assertIn(check_id, failed)

    def test_public_smoke_tests_pass_on_the_start_state(self):
        result = support.node_test('scenario_packs/S6/participant/tests/smoke.test.mjs')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_the_saved_records_are_complete_and_one_is_archived(self):
        data = json.loads((PACK / 'participant' / 'data' / 'notes.json').read_text())
        self.assertEqual(len(data['notes']), 5)
        self.assertEqual([n['id'] for n in data['notes'] if n['archived']], ['n-4'])
        self.assertTrue(all('revision' in n for n in data['notes']))

    def test_the_grader_does_not_write_into_the_candidate_directory(self):
        participant = PACK / 'participant'
        before = {str(p.relative_to(participant)): p.stat().st_mtime_ns
                  for p in sorted(participant.rglob('*')) if p.is_file()}
        records = (participant / 'data' / 'notes.json').read_text()
        support.grade('S6', participant)
        after = {str(p.relative_to(participant)): p.stat().st_mtime_ns
                 for p in sorted(participant.rglob('*')) if p.is_file()}
        self.assertEqual(before, after)
        self.assertEqual(records, (participant / 'data' / 'notes.json').read_text())


class IntendedReasonTest(unittest.TestCase):
    def fixture(self, name):
        return support.grade('S6', KNOWN_BAD / name)

    def test_duplicate_effects_replays_the_acknowledged_operation(self):
        report = self.fixture('duplicate-effects')
        failed = support.failed_ids(report)
        for check_id in ('R2', 'R5', 'R8'):
            self.assertIn(check_id, failed)
        self.assertIn('re-sent already-finished work', support.evidence(report, 'R8'))
        self.assertIn('note:n-1@3', support.evidence(report, 'R5'))
        # The happy path and the failure reporting are still correct.
        self.assertNotIn('R1', failed)
        self.assertNotIn('R3', failed)

    def test_lost_progress_restarts_from_scratch_and_truncates_the_ledger(self):
        report = self.fixture('lost-progress')
        failed = support.failed_ids(report)
        for check_id in ('R2', 'R6', 'R8', 'R9'):
            self.assertIn(check_id, failed)
        self.assertIn('lost entries across the restart', support.evidence(report, 'R6'))
        self.assertIn('truncated or rewritten', support.evidence(report, 'R9'))
        self.assertIn('sent 4 effect(s) again', support.evidence(report, 'R2'))

    def test_swallowed_failure_reports_a_missing_effect_as_done(self):
        report = self.fixture('swallowed-failure')
        failed = support.failed_ids(report)
        self.assertEqual(failed, ['R3', 'R4'])
        self.assertIn('never retried', support.evidence(report, 'R3'))
        self.assertIn('missing effect was reported as done', support.evidence(report, 'R4'))

    def test_non_durable_ack_records_the_operation_before_performing_it(self):
        report = self.fixture('non-durable-ack')
        failed = support.failed_ids(report)
        for check_id in ('R5', 'R7'):
            self.assertIn(check_id, failed)
        self.assertIn('reached the transport 0 times', support.evidence(report, 'R5'))
        self.assertIn('no effect ever reached the transport', support.evidence(report, 'R4'))


class EvidenceHygieneTest(unittest.TestCase):
    def test_no_absolute_candidate_path_leaks_into_the_evidence(self):
        for name in ('duplicate-effects', 'lost-progress', 'swallowed-failure', 'non-durable-ack'):
            report = support.grade('S6', KNOWN_BAD / name)
            blob = json.dumps(report)
            self.assertNotIn(str(KNOWN_BAD / name), blob)
            self.assertNotIn(str(PACK / 'private'), blob)

    def test_every_check_carries_a_description_and_evidence(self):
        report = support.grade('S6', REFERENCE)
        self.assertEqual(sorted(c['id'] for c in report['checks']),
                         sorted(support.scenario('S6')['grader']['expected_check_ids']))
        for check in report['checks']:
            self.assertTrue(check.get('description'))
            self.assertTrue(check.get('evidence'), check['id'])


# --------------------------------------------------------------------------- bench harness
def graph_workflow():
    """The shipped graph candidate: planner -> workers -> reviewer -> integrator."""
    return adapter.load_workflow(adapter.DEFAULT_WORKFLOW)


def solo_workflow():
    return adapter.load_workflow(adapter.SOLO_WORKFLOW)


def limits(**overrides):
    merged = {'max_concurrency': 2, 'max_workers': 8,
              'max_attempts_total': 32, 'max_elapsed_seconds': 30.0}
    merged.update(overrides)
    return merged


FIRST_RUN = 'run-s6-first'
RESTART_RUN = 'run-s6-restart'


def crash_then_restart(workflow, workspace, plan, executor=None, revision=REV):
    """One interruption at `plan`'s milestone and one restart on the same workspace.

    SIMULATED: `FakeExecutor` workers, an injected exception, and a second in-process
    `run()` standing in for a restarted process. The two phases carry distinct run IDs
    because they are two processes; the workspace, the effects log and the recorded state
    are the same.
    """
    events = []
    plan.reset()
    first = adapter.run(workflow, adapter.FakeExecutor(), limits(max_concurrency=1), events,
                        workspace, run_id=FIRST_RUN, source_revision=revision, fault_plan=plan)
    second = adapter.run(workflow, executor or adapter.FakeExecutor(), limits(max_concurrency=1),
                         events, workspace, run_id=RESTART_RUN, source_revision=revision,
                         fault_plan=None)
    return first, second, events


class SameMilestoneTest(unittest.TestCase):
    """The SAME FaultPlan object interrupts the solo and the graph workflow at the same
    semantic milestone. Asserted on the emitted fault/restart events, never on a count of
    agents or calls. SIMULATED worker recovery, not a real coding-agent restart."""

    def setUp(self):
        self.plan = adapter.FaultPlan(MILESTONE, 'crash')
        self.results = {}
        self.stack = []
        for name, workflow in (('solo', solo_workflow()), ('graph', graph_workflow())):
            temp = tempfile.TemporaryDirectory(prefix=f'ob2-s6-{name}-')
            self.stack.append(temp)
            first, second, events = crash_then_restart(workflow, temp.name, self.plan)
            self.results[name] = {'first': first, 'second': second, 'events': events,
                                  'workspace': temp.name}

    def tearDown(self):
        for temp in self.stack:
            temp.cleanup()

    def fault_milestones(self, name):
        return [e['payload']['milestone'] for e in self.results[name]['events']
                if e['type'] == 'fault']

    def test_both_adapters_are_interrupted_at_the_same_semantic_milestone(self):
        for name in ('solo', 'graph'):
            self.assertEqual(self.results[name]['first']['status'], 'crashed', name)
            self.assertEqual(self.fault_milestones(name), [MILESTONE], name)
            self.assertEqual(self.results[name]['first']['crash']['milestone'], MILESTONE, name)
        self.assertEqual(self.fault_milestones('solo'), self.fault_milestones('graph'))
        # The identical plan object drove both; the scenario pack names the same string.
        self.assertEqual(self.plan.milestone, MILESTONE)
        self.assertEqual(support.grade('S6', REFERENCE)['details']['milestone'], MILESTONE)

    def test_the_milestone_is_not_a_position_in_the_run(self):
        """The two shapes crash at different node counts — same milestone, different graph."""
        solo_nodes = len(self.results['solo']['first']['nodeStatus'])
        graph_nodes = len(self.results['graph']['first']['nodeStatus'])
        self.assertNotEqual(solo_nodes, graph_nodes)
        self.assertEqual(self.fault_milestones('solo'), self.fault_milestones('graph'))

    def test_recovery_completes_for_both_adapters(self):
        for name in ('solo', 'graph'):
            second = self.results[name]['second']
            self.assertEqual(second['status'], 'complete', (name, second['nodeStatus']))
            self.assertTrue(second['joinOk'], name)

    def test_no_externally_visible_effect_is_duplicated(self):
        for name in ('solo', 'graph'):
            keys = [entry['key'] for entry in self.results[name]['second']['effects']]
            self.assertEqual(sorted(keys), sorted(set(keys)),
                             f'{name}: an effect was applied twice')
            self.assertTrue(keys, name)

    def test_no_data_is_lost_across_the_restart(self):
        """Every effect recorded before the crash is still there, unreordered, afterwards."""
        for name in ('solo', 'graph'):
            first_keys = [e['key'] for e in self.results[name]['first']['effects']]
            final_keys = [e['key'] for e in self.results[name]['second']['effects']]
            self.assertTrue(first_keys, name)
            self.assertEqual(final_keys[:len(first_keys)], first_keys,
                             f'{name}: the pre-crash effects log was rewritten')
            state = json.loads(
                (Path(self.results[name]['workspace']) / '.runtime' / 'state.json').read_text())
            self.assertTrue(state['nodes'], name)

    def test_nothing_is_reused_when_the_crash_left_no_recorded_completion(self):
        """Both shapes crash on their first node, so there is no completed prefix at all.

        The restart re-runs it rather than assuming it was done, and the keyed effects log
        is what keeps that re-run from duplicating the external effect."""
        for name in ('solo', 'graph'):
            second = self.results[name]['second']
            self.assertEqual(second['reusedNodes'], [], name)
            self.assertEqual(second['replay'], [], name)
            self.assertEqual([e for e in self.results[name]['events']
                              if e['type'] == 'restart'], [], name)


class ReuseIdentityTest(unittest.TestCase):
    """Completed work is reused only after an explicit source-revision AND artifact-hash
    check, and is not reused when either differs."""

    #: the same semantic milestone string, aimed at a node with a completed prefix in front
    PLAN = dict(node_id='worker-b')

    def test_reuse_is_granted_only_after_both_identity_checks(self):
        for workflow in (graph_workflow(),):
            with tempfile.TemporaryDirectory(prefix='ob2-s6-reuse-') as workspace:
                plan = adapter.FaultPlan(MILESTONE, 'crash', **self.PLAN)
                _, second, _ = crash_then_restart(workflow, workspace, plan)
                reasons = {r['nodeId']: r['reason'] for r in second['replay'] if r['reused']}
                self.assertTrue(reasons, workflow['id'])
                for node_id, reason in reasons.items():
                    self.assertIn('source revision', reason, node_id)
                    self.assertIn('artifact hash', reason, node_id)
                    self.assertIn(node_id, second['reusedNodes'])

    def test_nothing_is_reused_when_the_source_revision_differs(self):
        with tempfile.TemporaryDirectory(prefix='ob2-s6-rev-') as workspace:
            plan = adapter.FaultPlan(MILESTONE, 'crash', **self.PLAN)
            adapter.run(graph_workflow(), adapter.FakeExecutor(), limits(max_concurrency=1),
                        [], workspace, run_id=FIRST_RUN, source_revision=REV, fault_plan=plan)
            second = adapter.run(graph_workflow(), adapter.FakeExecutor(),
                                 limits(max_concurrency=1), [], workspace,
                                 run_id=RESTART_RUN, source_revision='rev-s6-DIFFERENT')
            self.assertEqual(second['reusedNodes'], [])
            for entry in second['replay']:
                self.assertFalse(entry['reused'])
                self.assertIn('source revision changed', entry['reason'])

    def test_nothing_is_reused_when_the_artifact_hash_differs(self):
        with tempfile.TemporaryDirectory(prefix='ob2-s6-hash-') as workspace:
            plan = adapter.FaultPlan(MILESTONE, 'crash', **self.PLAN)
            first = adapter.run(graph_workflow(), adapter.FakeExecutor(),
                                limits(max_concurrency=1), [], workspace, run_id=FIRST_RUN,
                                source_revision=REV, fault_plan=plan)
            completed = [n for n, s in first['nodeStatus'].items() if s == 'completed']
            self.assertTrue(completed)
            tampered = adapter.FakeExecutor(
                artifact_hashes={node_id: 'hash-changed' for node_id in completed})
            second = adapter.run(graph_workflow(), tampered, limits(max_concurrency=1), [],
                                 workspace, run_id=RESTART_RUN, source_revision=REV)
            for node_id in completed:
                self.assertNotIn(node_id, second['reusedNodes'])
            reasons = {r['nodeId']: r['reason'] for r in second['replay']}
            for node_id in completed:
                self.assertIn('artifact hash changed', reasons[node_id])

    def test_a_reused_node_is_not_re_executed(self):
        with tempfile.TemporaryDirectory(prefix='ob2-s6-noexec-') as workspace:
            plan = adapter.FaultPlan(MILESTONE, 'crash', **self.PLAN)
            adapter.run(graph_workflow(), adapter.FakeExecutor(), limits(max_concurrency=1),
                        [], workspace, run_id=FIRST_RUN, source_revision=REV, fault_plan=plan)
            executor = adapter.FakeExecutor()
            second = adapter.run(graph_workflow(), executor, limits(max_concurrency=1), [],
                                 workspace, run_id=RESTART_RUN, source_revision=REV)
            executed = {node_id for node_id, _ in executor.executed}
            self.assertTrue(second['reusedNodes'])
            for node_id in second['reusedNodes']:
                self.assertNotIn(node_id, executed)

    def test_the_restart_is_deterministic(self):
        runs = []
        for _ in range(2):
            with tempfile.TemporaryDirectory(prefix='ob2-s6-det-') as workspace:
                plan = adapter.FaultPlan(MILESTONE, 'crash', **self.PLAN)
                first, second, _ = crash_then_restart(graph_workflow(), workspace, plan)
                runs.append((first['nodeStatus'], second['nodeStatus'], second['reusedNodes'],
                             [e['key'] for e in second['effects']]))
        self.assertEqual(runs[0], runs[1])


class TraceAndMetricsTest(unittest.TestCase):
    """The events import into a TraceStore and `metrics.analyze` reports the interruption.
    Unknowns stay unknown: nothing unmeasured is shown as 0."""

    def harness(self, workflow, workspace, store_path, node_id='worker-b'):
        plan = adapter.FaultPlan(MILESTONE, 'crash',
                                 node_id=node_id if workflow['id'] != 'solo' else None)
        store = traces.TraceStore(store_path)
        first, second, events = crash_then_restart(workflow, workspace, plan)
        added = store.add(events)
        crashed = metrics.analyze(store, {'id': FIRST_RUN, 'scenario': 'S6',
                                          'scenarioVersion': '1.0.0'})
        analysis = metrics.analyze(store, {'id': RESTART_RUN, 'scenario': 'S6',
                                           'scenarioVersion': '1.0.0'})
        return first, second, events, store, analysis, added, crashed

    def test_events_import_and_reimport_idempotently(self):
        with tempfile.TemporaryDirectory(prefix='ob2-s6-trace-') as temp:
            first, second, events, store, analysis, added, crashed = self.harness(
                graph_workflow(), Path(temp) / 'ws', Path(temp) / 'trace.jsonl')
            self.assertEqual(added['added'], len(events))
            self.assertEqual(store.add(events), {'added': 0, 'duplicates': len(events)})
            for run_id in (FIRST_RUN, RESTART_RUN):
                self.assertTrue(store.synthetic(run_id))
            self.assertEqual(crashed['eventCount'] + analysis['eventCount'], len(events))

    def test_metrics_report_the_fault_the_restart_and_the_retries(self):
        with tempfile.TemporaryDirectory(prefix='ob2-s6-metrics-') as temp:
            _, second, events, _, analysis, _, crashed = self.harness(
                graph_workflow(), Path(temp) / 'ws', Path(temp) / 'trace.jsonl')
            # The interruption is a `fault` in the crashed phase...
            self.assertEqual({e['type'] for e in crashed['faults']['events']}, {'fault'})
            self.assertEqual(crashed['faults']['count'], 1)
            faulted = [e for e in events if e['type'] == 'fault']
            self.assertEqual([e['payload']['milestone'] for e in faulted], [MILESTONE])
            # ...and the recovery is a `restart` in the phase that resumes.
            self.assertEqual({e['type'] for e in analysis['faults']['events']}, {'restart'})
            self.assertEqual(analysis['faults']['count'], 1)
            self.assertIn('retries', analysis)
            self.assertIsInstance(analysis['retries']['nodes'], list)
            self.assertTrue(second['reusedNodes'])
            self.assertIn('staleRevisionNodes', analysis)
            self.assertIn('reusedArtifactNodes', analysis)

    def test_unmeasured_values_are_unavailable_and_never_zero(self):
        with tempfile.TemporaryDirectory(prefix='ob2-s6-unknown-') as temp:
            first, second, _, _, analysis, _, _ = self.harness(
                graph_workflow(), Path(temp) / 'ws', Path(temp) / 'trace.jsonl')
            # The fake executor reports no tokens and no cost: unknown, not 0.
            for key in ('inputTokens', 'outputTokens', 'costUSD'):
                total = analysis['usageTotals'][key]
                self.assertFalse(total['complete'], key)
                self.assertGreater(total['unknownCount'], 0, key)
                self.assertIsNone(total['value'], key)
            self.assertNotEqual(analysis['reconciliation']['status'], 'matches')
            self.assertFalse(analysis['complete'])

            report = support.recovery_report(first, second, analysis)
            self.assertEqual(report['milestone'], MILESTONE)
            self.assertTrue(report['synthetic'])
            self.assertIn('not a verified real', report['note'])
            self.assertEqual(report['duplicatedEffects'], [])
            self.assertEqual(report['reuseIdentityChecks'], ['sourceRevision', 'artifactHash'])
            for key in ('recoveryTokens', 'recoveryCostUSD'):
                value = report[key]
                self.assertIsNone(value['value'], key)
                self.assertEqual(value['provenance'], 'unavailable', key)
                self.assertTrue(value['reason'].strip(), key)
            for key, value in report.items():
                if isinstance(value, dict) and value.get('provenance') == 'unavailable':
                    self.assertIsNone(value['value'], f'{key} was fabricated')
                    self.assertNotEqual(value['value'], 0, f'{key} shows an unknown as 0')

    def test_the_critical_path_is_null_with_a_reason_when_unsupported(self):
        with tempfile.TemporaryDirectory(prefix='ob2-s6-cp-') as temp:
            first, second, _, _, analysis, _, _ = self.harness(
                solo_workflow(), Path(temp) / 'ws', Path(temp) / 'trace.jsonl')
            critical = analysis['criticalPath']
            if not critical['supported']:
                self.assertIsNone(critical['seconds']['value'])
                self.assertTrue(critical['reason'])
                report = support.recovery_report(first, second, analysis)
                self.assertIsNone(report['criticalPathSeconds']['value'])
                self.assertTrue(report['criticalPathSeconds']['reason'])


class SyntheticLabellingTest(unittest.TestCase):
    def test_the_pack_and_the_harness_say_this_is_simulated(self):
        readme = (PACK / 'README.md').read_text().replace('**', '')
        self.assertIn('offline', readme)
        self.assertIn('verified real coding-agent restart', readme)
        self.assertIn('simulated worker recovery', readme.lower())
        self.assertIn('not a verified real coding-agent restart', __doc__)
        self.assertIn('SIMULATED', crash_then_restart.__doc__)

    def test_the_offline_run_never_claims_a_paid_call(self):
        with tempfile.TemporaryDirectory(prefix='ob2-s6-paid-') as workspace:
            plan = adapter.FaultPlan(MILESTONE, 'crash')
            first, second, _ = crash_then_restart(graph_workflow(), workspace, plan)
            for result in (first, second):
                self.assertFalse(result['paidCallsMade'])
                self.assertTrue(result['synthetic'])
                self.assertTrue(result['offlineValidation'])
                self.assertIsNone(result['executor']['provider'])


if __name__ == '__main__':
    unittest.main()
