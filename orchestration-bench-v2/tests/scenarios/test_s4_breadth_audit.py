"""S4 breadth audit: calibration, intended failure reasons, and the verdict join."""
import json
import tempfile
import unittest
from pathlib import Path

from tests.scenarios import support
from bench_core import registry

PACK = support.ROOT / 'scenario_packs' / 'S4'
REFERENCE = PACK / 'private' / 'reference'
INVENTORY = json.loads((PACK / 'private' / 'inventory.json').read_text())


class CalibrationTest(unittest.TestCase):
    def test_reference_passes_every_check(self):
        report = support.grade('S4', REFERENCE)
        self.assertTrue(report['allPassed'], support.failed_ids(report))
        self.assertEqual(report['details']['defectsMissed'], [])
        self.assertEqual(sorted(report['details']['defectsFound']),
                         sorted(d['id'] for d in INVENTORY['defects']))

    def test_calibrate_catches_every_known_bad(self):
        report = registry.calibrate(support.scenario('S4'), support.ROOT)
        self.assertEqual(report['status'], 'ok', report['problems'])
        self.assertEqual([f['id'] for f in report['known_bad']],
                         ['missed-defect', 'plausible-nonbug', 'duplicate-finding', 'count-padding'])
        for fixture in report['known_bad']:
            self.assertTrue(fixture['detected'], fixture)

    def test_grading_the_reference_twice_is_identical(self):
        first = support.grade('S4', REFERENCE)
        second = support.grade('S4', REFERENCE)
        self.assertEqual(first, second)


class IntendedReasonTest(unittest.TestCase):
    def fixture(self, name):
        return support.grade('S4', PACK / 'private' / 'known_bad' / name)

    def test_missed_defect_fails_recall_and_names_the_defect(self):
        report = self.fixture('missed-defect')
        self.assertIn('A2', support.failed_ids(report))
        self.assertEqual(report['details']['defectsMissed'], ['D4-sorting-tie-descending'])
        self.assertIn('D4-sorting-tie-descending', support.evidence(report, 'A2'))
        # Recall is isolated: breadth, precision and de-duplication are unaffected.
        self.assertEqual(support.failed_ids(report), ['A2'])

    def test_plausible_nonbug_fails_precision_on_the_nonbug(self):
        report = self.fixture('plausible-nonbug')
        self.assertEqual(support.failed_ids(report), ['A3'])
        self.assertEqual(report['details']['falsePositiveIds'], ['F-07'])
        self.assertIn('archive.visibleNotes', support.evidence(report, 'A3'))
        self.assertIn('as specified', support.evidence(report, 'A3'))

    def test_duplicate_finding_fails_deduplication_on_one_defect(self):
        report = self.fixture('duplicate-finding')
        self.assertEqual(support.failed_ids(report), ['A4'])
        self.assertEqual(report['details']['duplicateClaims'],
                         ['D6-pagination-floor-total-pages claimed by F-02, F-08'])
        # Both findings are genuine: precision and recall are untouched.
        self.assertEqual(report['details']['falsePositiveIds'], [])
        self.assertEqual(report['details']['defectsMissed'], [])

    def test_count_padding_fails_precision_and_signal(self):
        report = self.fixture('count-padding')
        failed = support.failed_ids(report)
        self.assertIn('A3', failed)
        self.assertIn('A7', failed)
        self.assertEqual(report['details']['findingCount'], 12)
        self.assertEqual(report['details']['reproducingCount'], 2)
        self.assertIn('2/12', support.evidence(report, 'A7'))
        self.assertEqual(len(report['details']['falsePositiveIds']), 10)


class NoCreditTest(unittest.TestCase):
    def test_an_empty_findings_file_earns_nothing(self):
        with tempfile.TemporaryDirectory() as temp:
            candidate = support.submission(temp, None, FINDINGS__json={'findings': []})
            report = support.grade('S4', candidate)
        self.assertEqual(report['passed'], 0)
        self.assertIn('no findings', support.evidence(report, 'A1'))

    def test_a_missing_findings_file_earns_nothing(self):
        with tempfile.TemporaryDirectory() as temp:
            candidate = support.submission(temp, None, README__md='nothing here\n')
            report = support.grade('S4', candidate)
        self.assertEqual(report['passed'], 0)
        self.assertIn('missing', support.evidence(report, 'A1'))

    def test_schema_valid_prose_without_a_reproduction_is_a_false_positive(self):
        finding = {
            'id': 'X-1', 'module': 'tags', 'location': 'src/tags.mjs:normalizeTags',
            'claimedBehavior': 'Tags are lowercased, which loses the writer\'s capitalisation.',
            'expectedBehavior': 'Tags should keep their case.',
            'severity': 'critical',
            'reproduction': {'module': 'tags', 'export': 'normalizeTags', 'args': [['alpha', 'beta']]},
        }
        with tempfile.TemporaryDirectory() as temp:
            candidate = support.submission(temp, None, FINDINGS__json={'findings': [finding]})
            report = support.grade('S4', candidate)
        self.assertTrue(support.evidence(report, 'A1'))  # schema-valid
        self.assertEqual(report['details']['falsePositiveIds'], ['X-1'])
        self.assertIn('A3', support.failed_ids(report))

    def test_duplicate_finding_ids_are_a_schema_error(self):
        finding = json.loads((REFERENCE / 'FINDINGS.json').read_text())['findings'][0]
        with tempfile.TemporaryDirectory() as temp:
            candidate = support.submission(
                temp, None, FINDINGS__json={'findings': [finding, dict(finding)]})
            report = support.grade('S4', candidate)
        self.assertIn('A1', support.failed_ids(report))
        self.assertIn('duplicate finding ID', support.evidence(report, 'A1'))

    def test_severity_inflation_is_caught(self):
        data = json.loads((REFERENCE / 'FINDINGS.json').read_text())
        for finding in data['findings']:
            finding['severity'] = 'critical'
        with tempfile.TemporaryDirectory() as temp:
            candidate = support.submission(temp, None, FINDINGS__json=data)
            report = support.grade('S4', candidate)
        self.assertIn('A5', support.failed_ids(report))
        self.assertIn('claimed critical', support.evidence(report, 'A5'))


class AggregationTest(unittest.TestCase):
    def test_aggregate_node_suite_passes(self):
        result = support.node_test('scenario_packs/S4/private/aggregate.test.mjs')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('fail 0', result.stdout)
        self.assertIn('pass 11', result.stdout)

    def test_the_grader_joins_verdicts_by_stable_id_and_revision(self):
        report = support.grade('S4', REFERENCE)
        aggregation = report['details']['aggregation']
        self.assertEqual(aggregation['joinedBy'], 'findingId+sourceRevision')
        self.assertEqual(aggregation['unresolved'], [])
        self.assertEqual(aggregation['stale'], [])
        self.assertEqual(sorted(aggregation['accepted']),
                         ['F-01', 'F-02', 'F-03', 'F-04', 'F-05', 'F-06'])

    def test_the_source_revision_is_stable_and_derived_from_the_modules(self):
        first = support.grade('S4', REFERENCE)['details']['sourceRevision']
        second = support.grade('S4', PACK / 'private' / 'known_bad' / 'missed-defect')
        self.assertTrue(first.startswith('rev-'))
        self.assertEqual(first, second['details']['sourceRevision'])


class InventoryTest(unittest.TestCase):
    def test_inventory_matches_the_shipped_modules(self):
        modules = {p.stem for p in (PACK / 'participant' / 'src').glob('*.mjs')}
        self.assertEqual(len(modules), 12, sorted(modules))
        for defect in INVENTORY['defects']:
            self.assertIn(defect['module'], modules)
            self.assertIn(defect['severity'], ('critical', 'major', 'minor'))
        for nonbug in INVENTORY['nonbugs']:
            self.assertIn(nonbug['module'], modules)
        self.assertEqual(len(INVENTORY['defects']), 6)
        self.assertGreaterEqual(len(INVENTORY['nonbugs']), 4)

    def test_every_inventory_witness_reproduces_its_own_defect(self):
        findings = [{
            'id': f'W-{index}', 'module': defect['module'],
            'location': f"src/{defect['module']}.mjs:{defect['export']}",
            'claimedBehavior': defect['summary'], 'expectedBehavior': 'the specified behavior',
            'severity': defect['severity'],
            'reproduction': {'module': defect['module'], 'export': defect['export'],
                             'args': defect['witness']['args']},
        } for index, defect in enumerate(INVENTORY['defects'])]
        with tempfile.TemporaryDirectory() as temp:
            candidate = support.submission(temp, None, FINDINGS__json={'findings': findings})
            report = support.grade('S4', candidate)
        self.assertTrue(report['allPassed'], support.failed_ids(report))

    def test_no_nonbug_export_has_an_oracle(self):
        # A nonbug can never be "demonstrated": the grader has no oracle that disagrees with it.
        oracle_keys = set()
        for line in (PACK / 'private' / 'oracles.mjs').read_text().splitlines():
            line = line.strip()
            if line.startswith("'") and '.' in line and line.endswith('{'):
                oracle_keys.add(line.split("'")[1])
        self.assertEqual(oracle_keys,
                         {f"{d['module']}.{d['export']}" for d in INVENTORY['defects']})
        for nonbug in INVENTORY['nonbugs']:
            self.assertNotIn(f"{nonbug['module']}.{nonbug['export']}", oracle_keys)


class PublicChecksTest(unittest.TestCase):
    def test_public_smoke_tests_pass_on_the_start_state(self):
        result = support.node_test('scenario_packs/S4/participant/tests/smoke.test.mjs')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
