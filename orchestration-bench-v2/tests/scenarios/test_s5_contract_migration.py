"""S5 shared-contract migration: calibration, intended failure reasons, start state."""
import json
import unittest
from pathlib import Path

from tests.scenarios import support
from bench_core import registry

PACK = support.ROOT / 'scenario_packs' / 'S5'
REFERENCE = PACK / 'private' / 'reference'
KNOWN_BAD = PACK / 'private' / 'known_bad'


class CalibrationTest(unittest.TestCase):
    def test_reference_passes_every_check(self):
        report = support.grade('S5', REFERENCE)
        self.assertTrue(report['allPassed'], support.failed_ids(report))
        self.assertEqual(report['details']['failed'], [])

    def test_calibrate_catches_every_known_bad(self):
        report = registry.calibrate(support.scenario('S5'), support.ROOT)
        self.assertEqual(report['status'], 'ok', report['problems'])
        self.assertEqual([f['id'] for f in report['known_bad']],
                         ['single-consumer-pass', 'partial-migration', 'data-loss',
                          'contract-regression', 'report-forgery', 'mid-import-exit',
                          'fake-ipc-result'])
        for fixture in report['known_bad']:
            self.assertTrue(fixture['detected'], fixture)

    def test_grading_the_reference_twice_is_identical(self):
        self.assertEqual(support.grade('S5', REFERENCE), support.grade('S5', REFERENCE))


class StartStateTest(unittest.TestCase):
    def test_the_unmodified_start_state_fails_the_grader(self):
        report = support.grade('S5', PACK / 'participant')
        self.assertFalse(report['allPassed'])
        failed = support.failed_ids(report)
        for check_id in ('C1', 'C4', 'C8', 'C9'):
            self.assertIn(check_id, failed)

    def test_public_smoke_tests_pass_on_the_start_state(self):
        result = support.node_test('scenario_packs/S5/participant/tests/smoke.test.mjs')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_the_saved_records_are_v1_and_complete(self):
        data = json.loads((PACK / 'participant' / 'data' / 'notes.json').read_text())
        self.assertEqual(data['schemaVersion'], 1)
        self.assertEqual(len(data['notes']), 5)
        self.assertTrue(all(isinstance(note['tags'], str) for note in data['notes']))

    def test_the_grader_does_not_write_into_the_candidate_directory(self):
        participant = PACK / 'participant'
        before = {str(p.relative_to(participant)): p.stat().st_mtime_ns
                  for p in sorted(participant.rglob('*')) if p.is_file()}
        digest_before = (participant / 'data' / 'notes.json').read_text()
        support.grade('S5', participant)
        after = {str(p.relative_to(participant)): p.stat().st_mtime_ns
                 for p in sorted(participant.rglob('*')) if p.is_file()}
        self.assertEqual(before, after)
        self.assertEqual(digest_before, (participant / 'data' / 'notes.json').read_text())


class IntendedReasonTest(unittest.TestCase):
    def fixture(self, name):
        return support.grade('S5', KNOWN_BAD / name)

    def test_single_consumer_pass_breaks_the_other_consumers_and_integration(self):
        report = self.fixture('single-consumer-pass')
        failed = support.failed_ids(report)
        for check_id in ('C5', 'C7', 'C8', 'C9'):
            self.assertIn(check_id, failed)
        # Its own consumer — the API — and the persistence layer still pass.
        self.assertNotIn('C1', failed)
        self.assertNotIn('C4', failed)
        self.assertIn('created', support.evidence(report, 'C5'))  # the old v1 CSV column
        self.assertIn('nothing was thrown', support.evidence(report, 'C8'))

    def test_partial_migration_is_missing_the_new_required_fields(self):
        report = self.fixture('partial-migration')
        failed = support.failed_ids(report)
        for check_id in ('C1', 'C4', 'C9'):
            self.assertIn(check_id, failed)
        self.assertIn('archived', support.evidence(report, 'C4'))
        self.assertIn('not v2', support.evidence(report, 'C9'))

    def test_data_loss_is_reported_as_lost_records(self):
        report = self.fixture('data-loss')
        self.assertIn('C1', support.failed_ids(report))
        self.assertIn('records were lost', support.evidence(report, 'C1'))
        self.assertIn('4 records came back', support.evidence(report, 'C1'))

    def test_contract_regression_breaks_the_declared_legacy_compatibility(self):
        report = self.fixture('contract-regression')
        failed = support.failed_ids(report)
        self.assertIn('C8', failed)
        self.assertIn('C9', failed)
        self.assertIn('legacy', support.evidence(report, 'C8'))
        # Everything else about the migration is correct.
        self.assertEqual(failed, ['C8', 'C9'])


class EvidenceHygieneTest(unittest.TestCase):
    def test_no_absolute_candidate_path_leaks_into_the_evidence(self):
        for name in ('single-consumer-pass', 'partial-migration', 'data-loss', 'contract-regression'):
            report = support.grade('S5', KNOWN_BAD / name)
            blob = json.dumps(report)
            self.assertNotIn(str(KNOWN_BAD / name), blob)
            self.assertNotIn(str(support.ROOT / 'scenario_packs' / 'S5' / 'private'), blob)


if __name__ == '__main__':
    unittest.main()
