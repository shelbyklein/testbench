"""Behavior of effort and recovery analysis (contracts/CONTRACTS.md §7 run shape, §8)."""
import json
import tempfile
import unittest
from pathlib import Path

from bench_core import metrics, traces

FIXTURES = Path(__file__).resolve().parent / 'fixtures'


def run_dict(run_id, scenario, method, repeat=1, phases=None, environment='local-default',
             scenario_version='1.0.0'):
    """A minimal `ob2-experiment/1` run row (§7)."""
    return {
        'id': run_id, 'scenario': scenario, 'scenarioVersion': scenario_version,
        'method': method, 'methodVersion': '1.0.0', 'repeat': repeat,
        'environment': environment, 'block': 1, 'position': 1, 'order': 1,
        'pairKey': f'{scenario}@{scenario_version}|{environment}|r{repeat}',
        'status': 'complete', 'phases': phases or {}, 'metrics': {},
        'baselineCommit': 'a86b094', 'initialHashes': {},
    }


def phase(all_passed=None, defects=()):
    body = {}
    if all_passed is not None:
        body['evaluation'] = {'allPassed': all_passed, 'passed': 3 if all_passed else 1, 'total': 3}
    if defects:
        body['review'] = {'defects': [{'severity': s} for s in defects]}
    return body


def experiment(runs, phases=('first', 'repaired')):
    return {'format': 'ob2-experiment/1', 'version': 2,
            'definition': {'contract': 'experiment-definition/1', 'id': 'practical-setups',
                           'phases': list(phases)},
            'runs': runs}


class AnalyzeTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def report(self, fixture, run_id, **kw):
        store = traces.TraceStore(Path(self.tmp.name) / f'{run_id}.jsonl')
        traces.import_file(FIXTURES / fixture, run_id, 'exp-demo', store)
        return metrics.analyze(store, run_dict(run_id, kw.pop('scenario', 'S2'),
                                               kw.pop('method', 'active'), **kw))


class WallTimeTests(AnalyzeTestCase):
    def test_overlapping_workers_make_wall_time_less_than_the_sum(self):
        report = self.report('active.jsonl', 'run-act001')
        wall = report['wallTime']
        self.assertEqual(wall['method'], 'interval-union')
        self.assertEqual(wall['seconds']['value'], 360.0)
        self.assertEqual(wall['sumOfDurationsSeconds'], 510.0)
        self.assertLess(wall['seconds']['value'], wall['sumOfDurationsSeconds'])

    def test_sequential_handoff_wall_time_equals_the_sum(self):
        report = self.report('handoff.jsonl', 'run-hand01', method='handoff')
        wall = report['wallTime']
        self.assertEqual(wall['seconds']['value'], wall['sumOfDurationsSeconds'])

    def test_waiting_integration_and_retry_are_reported_separately(self):
        overhead = self.report('active.jsonl', 'run-act001')['overhead']
        self.assertEqual(overhead['waitingSeconds']['value'], 180.0)
        self.assertEqual(overhead['integrationSeconds']['value'], 120.0)
        self.assertEqual(overhead['retrySeconds']['value'], 90.0)
        self.assertTrue(overhead['measured'])

    def test_clock_uncertainty_is_surfaced(self):
        self.assertEqual(self.report('active.jsonl', 'run-act001')['wallTime']['clockUncertaintySeconds'], 2)
        self.assertIsNone(self.report('solo.jsonl', 'run-solo01',
                                      method='solo')['wallTime']['clockUncertaintySeconds'])

    def test_an_unfinished_node_leaves_wall_time_unknown(self):
        store = traces.TraceStore(Path(self.tmp.name) / 'open.jsonl')
        traces.import_file(FIXTURES / 'active.jsonl', 'run-act001', 'exp-demo', store)
        store.add(traces.normalize_event({
            'eventId': 'extra-start', 'runId': 'run-act001', 'nodeId': 'worker-e',
            'role': 'worker', 'type': 'node_started', 'timestamp': '2026-09-20T12:06:00+00:00',
            'status': 'ok', 'evidence': {'importer': 'synthetic', 'importerVersion': '1.0.0'}}))
        report = metrics.analyze(store, run_dict('run-act001', 'S2', 'active'))
        self.assertIsNone(report['wallTime']['seconds']['value'])
        self.assertEqual(report['wallTime']['openIntervals'], ['worker-e'])
        self.assertFalse(report['complete'])


class UsageTests(AnalyzeTestCase):
    def test_roles_are_broken_out_only_where_evidence_supports_it(self):
        report = self.report('active.jsonl', 'run-act001')
        self.assertEqual(sorted(report['roles']), ['integrator', 'retry', 'worker'])
        self.assertEqual(report['roles']['worker']['nodes'], ['worker-a', 'worker-b', 'worker-c'])
        self.assertEqual(report['roles']['retry']['nodes'], ['worker-a'])
        self.assertNotIn('planner', report['roles'])

    def test_planner_and_worker_split_on_a_written_handoff(self):
        report = self.report('handoff.jsonl', 'run-hand01', method='handoff')
        self.assertEqual(sorted(report['roles']), ['planner', 'worker'])
        self.assertEqual(report['roles']['planner']['inputTokens']['value'], 1200)
        self.assertEqual(report['roles']['worker']['inputTokens']['value'], 3000)

    def test_inclusive_parent_is_never_added_to_its_children(self):
        report = self.report('inclusive.jsonl', 'run-incl01')
        self.assertEqual(sorted(report['roles']), ['orchestrator'])
        self.assertEqual(report['usageTotals']['inputTokens']['value'], 300)
        self.assertEqual(report['usageTotals']['outputTokens']['value'], 30)
        self.assertEqual(len(report['trace']['usageNotes']), 2)
        self.assertEqual(report['trace']['issues'], [])
        self.assertEqual(report['reconciliation']['status'], 'matches')

    def test_reconciliation_matches_when_roles_sum_to_the_imported_total(self):
        reconciliation = self.report('active.jsonl', 'run-act001')['reconciliation']
        self.assertEqual(reconciliation['status'], 'matches')
        self.assertEqual(reconciliation['differences']['inputTokens'], 0)
        self.assertEqual(reconciliation['importedScope'], 'inclusive')

    def test_reconciliation_detects_a_mismatch(self):
        store = traces.TraceStore(Path(self.tmp.name) / 'm.jsonl')
        traces.import_file(FIXTURES / 'active.jsonl', 'run-act001', 'exp-demo', store)
        store.add(traces.normalize_event({
            'eventId': 'stray-usage', 'runId': 'run-act001', 'nodeId': 'worker-b',
            'role': 'worker', 'type': 'usage', 'timestamp': '2026-09-20T12:03:59+00:00',
            'status': 'ok', 'evidence': {'importer': 'synthetic', 'importerVersion': '1.0.0'},
            'usage': {'inputTokens': {'value': 70, 'unit': 'tokens', 'provenance': 'measured',
                                      'source': 'test'},
                      'outputTokens': None, 'costUSD': None, 'durationSeconds': None,
                      'scope': 'self'}}))
        report = metrics.analyze(store, run_dict('run-act001', 'S2', 'active'))
        self.assertEqual(report['reconciliation']['status'], 'mismatch')
        self.assertEqual(report['reconciliation']['differences']['inputTokens'], 70)
        self.assertFalse(report['complete'])

    def test_reconciliation_is_unknown_without_an_imported_total(self):
        report = self.report('unknown_usage.jsonl', 'run-unk001', method='solo')
        self.assertEqual(report['reconciliation']['status'], 'unknown')
        self.assertIsNone(report['reconciliation']['imported'])
        self.assertFalse(report['complete'])

    def test_unknown_usage_makes_the_aggregate_incomplete_and_invents_no_cost(self):
        report = self.report('unknown_usage.jsonl', 'run-unk001', method='solo')
        totals = report['usageTotals']
        self.assertEqual(totals['inputTokens']['value'], 1000)
        self.assertTrue(totals['inputTokens']['complete'])
        self.assertIsNone(totals['outputTokens']['value'])
        self.assertFalse(totals['outputTokens']['complete'])
        self.assertEqual(totals['outputTokens']['unknownCount'], 1)
        self.assertIsNone(totals['costUSD']['value'])
        self.assertFalse(totals['costUSD']['complete'])
        self.assertFalse(report['complete'])
        self.assertNotIn('0', [str(totals['costUSD']['value'])])


class JoinAndGraphTests(AnalyzeTestCase):
    def test_join_reports_failed_missing_and_skipped(self):
        join = self.report('active.jsonl', 'run-act001')['join']
        self.assertEqual(join['failed'], ['worker-c'])
        self.assertEqual(join['missing'], ['worker-d'])
        self.assertEqual(join['skipped'], ['reviewer'])
        self.assertFalse(join['joinOk'])

    def test_declared_and_observed_graphs_are_both_reported(self):
        graphs = self.report('active.jsonl', 'run-act001')['graphs']
        self.assertTrue(graphs['deviated'])
        self.assertEqual(graphs['declaredOnly'], ['worker-d'])
        self.assertEqual(graphs['observedOnly'], [])

    def test_lineage_and_recovery_are_exposed(self):
        report = self.report('active.jsonl', 'run-act001')
        self.assertEqual(report['staleRevisionNodes'], ['worker-a'])
        self.assertEqual(report['reusedArtifactNodes'], ['worker-a'])
        self.assertEqual(report['retries']['nodes'], ['worker-a'])
        self.assertEqual(report['faults']['count'], 1)

    def test_human_interventions_are_counted_separately_from_usage(self):
        report = self.report('active.jsonl', 'run-act001')
        self.assertEqual(report['interventions']['count'], 1)
        self.assertNotIn('intervention', report['roles'])

    def test_critical_path_is_null_with_a_reason_when_unsupported(self):
        report = self.report('active.jsonl', 'run-act001')
        self.assertIsNone(report['criticalPath']['nodes'])
        self.assertFalse(report['criticalPath']['supported'])
        self.assertTrue(report['criticalPath']['reason'])
        solo = self.report('solo.jsonl', 'run-solo01', method='solo')
        self.assertIsNone(solo['criticalPath']['nodes'])
        self.assertIn('dependency', solo['criticalPath']['reason'])

    def test_critical_path_is_reported_when_supported(self):
        report = self.report('inclusive.jsonl', 'run-incl01')
        self.assertTrue(report['criticalPath']['supported'])
        self.assertEqual(report['criticalPath']['nodes'][0], 'lead')
        self.assertGreater(report['criticalPath']['seconds']['value'], 0)

    def test_a_clean_solo_run_is_complete(self):
        report = self.report('solo.jsonl', 'run-solo01', method='solo')
        self.assertTrue(report['complete'])
        self.assertTrue(report['synthetic'])
        self.assertTrue(report['join']['joinOk'])


class CompareTests(AnalyzeTestCase):
    def build(self, specs, phases=('first', 'repaired')):
        """specs: [(runId, scenario, method, repeat, fixture, phase_bodies)]"""
        runs, reports = [], []
        for run_id, scenario, method, repeat, fixture, bodies in specs:
            run = run_dict(run_id, scenario, method, repeat, bodies)
            runs.append(run)
            if fixture:
                store = traces.TraceStore(Path(self.tmp.name) / f'{run_id}.jsonl')
                traces.import_file(FIXTURES / fixture, run_id, 'exp-demo', store)
                reports.append(metrics.analyze(store, run))
        return experiment(runs, phases), reports

    def test_never_declares_a_winner(self):
        exp, reports = self.build([
            ('run-a', 'S1', 'solo', 1, 'solo.jsonl', {'first': phase(True), 'repaired': phase(True)}),
            ('run-b', 'S1', 'active', 1, 'active.jsonl', {'first': phase(False), 'repaired': phase(True)}),
        ])
        comparison = metrics.compare(exp, reports)
        self.assertIsNone(comparison['winner'])
        self.assertEqual(comparison['winnerPolicy'], 'not computed')
        self.assertIsNone(comparison['compositeScore'])
        blob = json.dumps(comparison)
        self.assertNotIn('"score"', blob)

    def test_pairing_separates_first_and_repaired(self):
        exp, reports = self.build([
            ('run-a', 'S1', 'solo', 1, 'solo.jsonl', {'first': phase(True), 'repaired': phase(True)}),
            ('run-b', 'S1', 'active', 1, 'active.jsonl', {'first': phase(False), 'repaired': phase(True)}),
        ])
        comparison = metrics.compare(exp, reports)
        by_phase = {c['phase']: c for c in comparison['paired']}
        self.assertEqual(by_phase['first']['result'], 'win')
        self.assertEqual(by_phase['first']['acceptanceWinner'], 'solo')
        self.assertEqual(by_phase['repaired']['result'], 'tie')
        summary = comparison['pairedSummary']
        self.assertEqual(summary['solo']['active'], {'wins': 1, 'losses': 0, 'ties': 1, 'incomplete': 0})
        self.assertEqual(summary['active']['solo'], {'wins': 0, 'losses': 1, 'ties': 1, 'incomplete': 0})

    def test_ties_are_recorded_both_ways(self):
        exp, reports = self.build([
            ('run-a', 'S1', 'solo', 1, 'solo.jsonl', {'first': phase(False)}),
            ('run-b', 'S1', 'active', 1, 'active.jsonl', {'first': phase(False)}),
        ], phases=('first',))
        comparison = metrics.compare(exp, reports)
        self.assertEqual([c['result'] for c in comparison['paired']], ['tie'])
        self.assertIsNone(comparison['paired'][0]['acceptanceWinner'])

    def test_a_missing_partner_is_reported_not_silently_dropped(self):
        exp, reports = self.build([
            ('run-a', 'S1', 'solo', 1, 'solo.jsonl', {'first': phase(True)}),
            ('run-b', 'S2', 'active', 1, 'active.jsonl', {'first': phase(True)}),
        ], phases=('first',))
        comparison = metrics.compare(exp, reports)
        self.assertEqual(comparison['paired'], [])
        self.assertEqual(len(comparison['unpaired']), 2)
        self.assertEqual(sorted(u['pairKey'] for u in comparison['unpaired']),
                         ['S1@1.0.0|local-default|r1', 'S2@1.0.0|local-default|r1'])

    def test_an_unevaluated_phase_is_incomplete_not_a_loss(self):
        exp, reports = self.build([
            ('run-a', 'S1', 'solo', 1, 'solo.jsonl', {'first': phase(True)}),
            ('run-b', 'S1', 'active', 1, 'active.jsonl', {'first': {}}),
        ], phases=('first',))
        comparison = metrics.compare(exp, reports)
        self.assertEqual(comparison['paired'][0]['result'], 'incomplete')
        self.assertIsNone(comparison['paired'][0]['acceptanceWinner'])
        self.assertEqual(comparison['pairedSummary']['solo']['active']['incomplete'], 1)

    def test_acceptance_and_serious_defects_are_reported_separately(self):
        exp, reports = self.build([
            ('run-a', 'S1', 'solo', 1, 'solo.jsonl',
             {'first': phase(True, defects=('serious', 'minor'))}),
            ('run-b', 'S1', 'active', 1, 'active.jsonl', {'first': phase(True, defects=('minor',))}),
        ], phases=('first',))
        comparison = metrics.compare(exp, reports)
        solo = comparison['methods']['solo']['phases']['first']
        self.assertEqual(solo['accepted'], 1)
        self.assertEqual(solo['seriousDefects'], 1)
        self.assertEqual(comparison['methods']['active']['phases']['first']['seriousDefects'], 0)
        self.assertEqual(comparison['paired'][0]['result'], 'tie')  # acceptance does not hide the defect

    def test_any_unknown_makes_the_aggregate_incomplete(self):
        exp, reports = self.build([
            ('run-a', 'S1', 'solo', 1, 'unknown_usage.jsonl', {'first': phase(True)}),
            ('run-b', 'S1', 'active', 1, 'active.jsonl', {'first': phase(True)}),
        ], phases=('first',))
        comparison = metrics.compare(exp, reports)
        solo = comparison['methods']['solo']
        self.assertFalse(solo['complete'])
        self.assertFalse(solo['usage']['costUSD']['complete'])
        self.assertIsNone(solo['usage']['costUSD']['value'])
        self.assertFalse(comparison['complete'])
        self.assertTrue(comparison['incompleteTraces'])

    def test_a_run_without_a_trace_is_named_not_costed(self):
        exp, reports = self.build([
            ('run-a', 'S1', 'solo', 1, None, {'first': phase(True)}),
            ('run-b', 'S1', 'active', 1, 'active.jsonl', {'first': phase(True)}),
        ], phases=('first',))
        comparison = metrics.compare(exp, reports)
        self.assertIn('run-a', [i['runId'] for i in comparison['incompleteTraces']])
        row = [r for r in comparison['rows'] if r['runId'] == 'run-a'][0]
        self.assertIsNone(row['inputTokens'])
        self.assertIsNone(row['wallSeconds'])
        self.assertFalse(row['traceComplete'])

    def test_raw_rows_are_emitted_per_run_and_phase(self):
        exp, reports = self.build([
            ('run-a', 'S1', 'solo', 1, 'solo.jsonl', {'first': phase(True), 'repaired': phase(True)}),
            ('run-b', 'S1', 'active', 1, 'active.jsonl', {'first': phase(False), 'repaired': phase(True)}),
        ])
        rows = metrics.compare(exp, reports)['rows']
        self.assertEqual(len(rows), 4)
        self.assertEqual({r['phase'] for r in rows}, {'first', 'repaired'})

    def test_repeats_of_one_task_are_not_task_diversity(self):
        exp, reports = self.build([
            ('run-a', 'S1', 'solo', 1, 'solo.jsonl', {'first': phase(True)}),
            ('run-b', 'S1', 'active', 1, 'active.jsonl', {'first': phase(True)}),
            ('run-c', 'S1', 'solo', 2, 'solo.jsonl', {'first': phase(True)}),
            ('run-d', 'S1', 'active', 2, 'active.jsonl', {'first': phase(False)}),
        ], phases=('first',))
        variation = metrics.compare(exp, reports)['variation']
        self.assertEqual(variation['taskLevel']['distinctTasks'], 1)
        self.assertEqual(variation['repeatLevel']['repeatsByScenario'], {'S1': 2})
        self.assertEqual(variation['repeatLevel']['totalRepeatRuns'], 4)

    def test_repeats_pair_independently(self):
        exp, reports = self.build([
            ('run-a', 'S1', 'solo', 1, 'solo.jsonl', {'first': phase(True)}),
            ('run-b', 'S1', 'active', 1, 'active.jsonl', {'first': phase(True)}),
            ('run-c', 'S1', 'solo', 2, 'solo.jsonl', {'first': phase(True)}),
            ('run-d', 'S1', 'active', 2, 'active.jsonl', {'first': phase(False)}),
        ], phases=('first',))
        summary = metrics.compare(exp, reports)['pairedSummary']
        self.assertEqual(summary['solo']['active'], {'wins': 1, 'losses': 0, 'ties': 1, 'incomplete': 0})

    def test_comparison_is_json_serializable(self):
        exp, reports = self.build([
            ('run-a', 'S1', 'solo', 1, 'solo.jsonl', {'first': phase(True)}),
            ('run-b', 'S1', 'active', 1, 'active.jsonl', {'first': phase(False)}),
        ], phases=('first',))
        json.dumps(metrics.compare(exp, reports))
        json.dumps(reports)


if __name__ == '__main__':
    unittest.main()
