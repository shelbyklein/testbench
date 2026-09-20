"""Regressions for defects found by the fresh-context review (OB2-13). Offline and synthetic."""
import json
import tempfile
import unittest
from pathlib import Path

import bench
import validate
from bench_core import common, experiment, metrics, registry, traces

ROOT = Path(__file__).resolve().parents[2]


def stub_scenario(folder, body):
    grader = Path(folder) / 'grade.mjs'
    grader.write_text("import fs from 'node:fs';\nfs.writeFileSync(process.argv[3], JSON.stringify(" + json.dumps(body) + "));\n")
    return {'id': 'X', 'version': '1', 'grader': {'argv': ['node', str(grader)], 'version': '1',
                                                'expected_check_ids': ['X1', 'X2'], 'timeout_seconds': 30}}


def event(node, kind, second, **extra):
    return traces.normalize_event(dict({'eventId': f'{node}-{kind}', 'runId': 'r', 'nodeId': node, 'attempt': 1, 'role': 'worker',
                                        'type': kind, 'timestamp': f'2026-01-01T00:00:{second:02d}+00:00', 'status': 'ok', 'synthetic': True,
                                        'evidence': {'importer': 'test', 'importerVersion': '1'}}, **extra))


class GraderArithmetic(unittest.TestCase):
    def test_claimed_totals_are_recomputed_from_the_checks(self):
        with tempfile.TemporaryDirectory() as temp:
            scenario = stub_scenario(temp, {'checks': [{'id': 'X1', 'status': 'fail'}, {'id': 'X2', 'status': 'pass'}],
                                            'passed': 2, 'total': 2, 'allPassed': True})
            report = experiment.evaluate_with_grader(scenario, temp, Path(temp) / 'out.json', ROOT)
        self.assertEqual((report['passed'], report['total'], report['allPassed']), (1, 2, False))
        self.assertIn('arithmeticMismatch', report)

    def test_a_status_other_than_pass_or_fail_is_a_grader_error(self):
        with tempfile.TemporaryDirectory() as temp:
            scenario = stub_scenario(temp, {'checks': [{'id': 'X1', 'status': 'error'}, {'id': 'X2', 'status': 'pass'}],
                                            'passed': 2, 'total': 2, 'allPassed': True})
            with self.assertRaises(ValueError):
                experiment.evaluate_with_grader(scenario, temp, Path(temp) / 'out.json', ROOT)


class PolicyHashes(unittest.TestCase):
    def test_every_private_grading_file_is_hashed(self):
        scenario = registry.load(ROOT).scenario('S4')
        hashed = set(experiment.policy_hashes(ROOT, [], [scenario]))
        private = {str(p.relative_to(ROOT)) for p in (ROOT / 'scenario_packs/S4/private').rglob('*') if p.is_file()}
        self.assertTrue(private and private <= hashed, sorted(private - hashed)[:3])


class Joins(unittest.TestCase):
    def test_a_node_skipped_because_its_dependency_failed_is_not_a_successful_join(self):
        with tempfile.TemporaryDirectory() as temp:
            store = traces.TraceStore(Path(temp) / 'events.jsonl')
            store.add([event('A', 'node_started', 1), event('A', 'node_completed', 2),
                       event('B', 'node_skipped', 3, payload={'reason': 'a dependency did not complete', 'forced': True})])
            joined = store.join(['A', 'B'])
            self.assertEqual(joined['B'], 'skipped')
            self.assertFalse(joined.join_ok)
            report = metrics.analyze(store, 'r')
        self.assertFalse(report['join']['joinOk'])
        self.assertEqual(report['join']['forcedSkips'], ['B'])

    def test_a_deliberate_skip_still_joins(self):
        with tempfile.TemporaryDirectory() as temp:
            store = traces.TraceStore(Path(temp) / 'events.jsonl')
            store.add([event('A', 'node_started', 1), event('A', 'node_completed', 2),
                       event('B', 'node_skipped', 3, payload={'reason': 'method declares internal_review disabled'})])
            self.assertTrue(store.join(['A', 'B']).join_ok)

    def test_a_trace_conflict_is_reported_by_the_cli_error_handler(self):
        self.assertTrue(issubclass(traces.TraceConflict, ValueError))


class ReadOnlyV1(unittest.TestCase):
    def test_no_lock_file_is_written_into_a_v1_experiment(self):
        with tempfile.TemporaryDirectory() as temp:
            exp = Path(temp)
            common.write(exp / 'experiment.json', {'version': 1, 'methods': [], 'scenarios': [], 'runs': [], 'pairs': []})
            before = sorted(p.name for p in exp.iterdir())
            with self.assertRaises(ValueError):
                bench.capture(exp, 'run-x', 'first')
            self.assertEqual(sorted(p.name for p in exp.iterdir()), before)


class Validation(unittest.TestCase):
    def test_a_missing_suite_fails_validation(self):
        self.assertEqual(validate.suite('no-such-suite', True)['status'], 'FAILED')


class StaleReviews(unittest.TestCase):
    def test_a_stale_review_does_not_feed_the_comparison(self):
        run = {'id': 'r1', 'scenario': 'S', 'scenarioVersion': '1', 'method': 'm', 'repeat': 1, 'pairKey': 'k',
               'phases': {'first': {'evaluation': {'allPassed': True}, 'reviewCurrent': False,
                                    'review': {'defects': [{'severity': 'critical', 'evidence': 'x'}]}}}}
        outcome = metrics._phase_outcome(run, 'first')
        self.assertEqual((outcome['seriousDefects'], outcome['reviewed'], outcome['staleReview']), (0, False, True))


if __name__ == '__main__':
    unittest.main()
