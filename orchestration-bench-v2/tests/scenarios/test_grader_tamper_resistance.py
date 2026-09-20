"""Graded code must not be able to write its own grade (review findings F1 and F2).

The S4, S5 and S6 graders execute submission-influenced code. Before this lane's fix they did
so inside the grader's own process, so a submitted module could — at import time — neutralise
``process.exit``, write a forged all-pass report over the grader's output path and leave with
status 0. The S4 grader additionally built a module path out of the submission-controlled
``reproduction.module`` with ``path.join``, so ``"../../"`` walked out of the frozen modules
directory and got an arbitrary ``.mjs`` file imported and executed.

Everything asserted here is **fixture-tested and offline**: the "attacks" are known-bad
fixtures in the packs and candidate directories this file builds in a temporary directory. No
provider is contacted and no model call is made.

What these tests establish is narrow and worth stating plainly: the *grade* is defended against
report forgery, early exits and arbitrary module execution. They do **not** establish that the
graders are a sandbox. Candidate code still runs with the user's OS permissions inside the
worker process.
"""
import json
import os
import tempfile
import unittest
from pathlib import Path

from tests.scenarios import support

FORGED_MARKERS = ('forged', 'allPassed')
NO_RESULT = 'no authenticated result'


def tamper_signals(report):
    return report['details'].get('tamperSignals')


class ForgeryIsRefusedTest(unittest.TestCase):
    """The import-time forgery fixture buys nothing in either pack that runs candidate code."""

    def fixture(self, pack, name):
        return support.grade(pack, support.ROOT / 'scenario_packs' / pack /
                             'private' / 'known_bad' / name)

    def test_report_forgery_earns_nothing_and_is_named(self):
        for pack in ('S5', 'S6'):
            with self.subTest(pack=pack):
                report = self.fixture(pack, 'report-forgery')
                self.assertFalse(report['allPassed'])
                self.assertEqual(report['passed'], 0)
                self.assertEqual(support.failed_ids(report),
                                 sorted(support.scenario(pack)['grader']['expected_check_ids']))
                signals = tamper_signals(report)
                self.assertTrue(signals, 'the forgery attempt left no tamper signal')
                self.assertTrue(any(NO_RESULT in c['evidence'] for c in report['checks']))
                self.assertTrue(any('no authenticated result' in s for s in signals))

    def test_the_forged_content_never_reaches_the_report(self):
        # The supervisor rebuilds the report; nothing the fixture wrote can survive into it.
        for pack in ('S5', 'S6'):
            with self.subTest(pack=pack):
                report = self.fixture(pack, 'report-forgery')
                blob = json.dumps(report)
                self.assertNotIn('"forged": true', blob)
                self.assertNotIn('forged', json.dumps(report['checks']))

    def test_passed_total_and_exit_code_are_the_supervisor_s_own_arithmetic(self):
        for pack in ('S5', 'S6'):
            with self.subTest(pack=pack):
                report = self.fixture(pack, 'report-forgery')
                expected = support.scenario(pack)['grader']['expected_check_ids']
                self.assertEqual(report['total'], len(expected))
                self.assertEqual(sorted(c['id'] for c in report['checks']), sorted(expected))
                self.assertEqual(report['passed'],
                                 len([c for c in report['checks'] if c['status'] == 'pass']))
                self.assertIs(report['allPassed'], report['passed'] == report['total'])

    def test_mid_import_exit_fails_loudly_instead_of_quietly(self):
        for pack in ('S5', 'S6'):
            with self.subTest(pack=pack):
                report = self.fixture(pack, 'mid-import-exit')
                self.assertEqual(report['passed'], 0)
                signals = tamper_signals(report)
                self.assertTrue(any('process.exit(0)' in s for s in signals), signals)

    def test_an_unauthenticated_all_pass_message_is_discarded_and_recorded(self):
        for pack in ('S5', 'S6'):
            with self.subTest(pack=pack):
                report = self.fixture(pack, 'fake-ipc-result')
                self.assertFalse(report['allPassed'])
                signals = tamper_signals(report)
                self.assertTrue(any('without the run nonce' in s for s in signals), signals)
                # The submission is still graded on what it actually does: the start state's
                # own failures stand, and the start state's own passes are not taken away.
                must_fail = next(f['must_fail'] for f in support.scenario(pack)['calibration']['known_bad']
                                 if f['id'] == 'fake-ipc-result')
                self.assertEqual(support.failed_ids(report), sorted(must_fail))
                self.assertGreater(report['passed'], 0)

    def test_the_run_nonce_never_appears_in_the_report(self):
        for pack in ('S5', 'S6'):
            with self.subTest(pack=pack):
                blob = json.dumps(self.fixture(pack, 'fake-ipc-result'))
                self.assertNotIn('nonce', blob.replace('run nonce', ''))

    def test_grading_an_adversarial_fixture_twice_is_identical(self):
        # Determinism survives the split: the nonce and the timings are not in the report.
        for pack in ('S5', 'S6'):
            for name in ('report-forgery', 'fake-ipc-result'):
                with self.subTest(pack=pack, fixture=name):
                    self.assertEqual(self.fixture(pack, name), self.fixture(pack, name))


class CleanSubmissionsAreUnaffectedTest(unittest.TestCase):
    """The defence costs an honest submission nothing, and says so in the report."""

    def test_the_reference_passes_with_no_tamper_signal(self):
        for pack in ('S4', 'S5', 'S6'):
            with self.subTest(pack=pack):
                report = support.grade(pack, support.ROOT / 'scenario_packs' / pack /
                                       'private' / 'reference')
                self.assertTrue(report['allPassed'], support.failed_ids(report))
                self.assertEqual(tamper_signals(report), [])

    def test_every_report_carries_a_tamper_signal_list(self):
        for pack in ('S4', 'S5', 'S6'):
            with self.subTest(pack=pack):
                report = support.grade(pack, support.ROOT / 'scenario_packs' / pack /
                                       'private' / 'reference')
                self.assertIsInstance(tamper_signals(report), list)
                self.assertIn('supervisor/worker', report['details']['graderModel'])


class S4PathTraversalTest(unittest.TestCase):
    """``reproduction.module`` may only ever name a frozen module of this pack."""

    MODULES = support.ROOT / 'scenario_packs' / 'S4' / 'participant' / 'src'

    def finding(self, module, export='matchesQuery', args=None):
        return {
            'id': 'F-01', 'module': 'search', 'location': 'src/search.mjs:matchesQuery',
            'claimedBehavior': 'Something is wrong.', 'expectedBehavior': 'It should be right.',
            'severity': 'major',
            'reproduction': {'module': module, 'export': export,
                             'args': [] if args is None else args},
        }

    def test_a_traversal_payload_is_never_imported(self):
        with tempfile.TemporaryDirectory(prefix='ob2-s4-payload-') as temp:
            payload_dir = Path(temp) / 'payload'
            payload_dir.mkdir()
            marker = payload_dir / 'EXECUTED'
            (payload_dir / 'evil.mjs').write_text(
                "import fs from 'node:fs';\n"
                f"fs.writeFileSync({json.dumps(str(marker))}, 'the grader imported me\\n');\n"
                "export function matchesQuery() { return true; }\n")
            # The exact shape of the v1 exploit: a relative escape out of participant/src.
            escape = os.path.relpath(payload_dir / 'evil', self.MODULES)
            self.assertTrue(escape.startswith('..'), escape)

            candidate = support.submission(
                temp, None, FINDINGS__json={'findings': [self.finding(escape)]})
            report = support.grade('S4', candidate)

        self.assertFalse(marker.exists(), 'the traversal payload was imported and executed')
        self.assertIn('A1', support.failed_ids(report))
        self.assertIn('must name one of the modules in src/', support.evidence(report, 'A1'))
        self.assertIn(escape, support.evidence(report, 'A1'))

    def test_an_absolute_module_path_is_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            candidate = support.submission(
                temp, None,
                FINDINGS__json={'findings': [self.finding(str(self.MODULES / 'search'))]})
            report = support.grade('S4', candidate)
        self.assertIn('A1', support.failed_ids(report))
        self.assertIn('must name one of the modules in src/', support.evidence(report, 'A1'))

    def test_the_static_traversal_fixture_fails_the_schema_check(self):
        report = support.grade('S4', support.ROOT / 'scenario_packs' / 'S4' /
                               'private' / 'known_bad' / 'path-traversal')
        self.assertIn('A1', support.failed_ids(report))
        self.assertEqual(report['details']['reproducingCount'], 0)
        self.assertIn('/tmp/ob2-s4-payload/evil', support.evidence(report, 'A1'))

    def test_the_allowed_modules_are_exactly_the_frozen_ones(self):
        report = support.grade('S4', support.ROOT / 'scenario_packs' / 'S4' / 'private' / 'reference')
        self.assertEqual(sorted(report['details']['allowedModules']),
                         sorted(p.stem for p in self.MODULES.glob('*.mjs')))

    def test_an_export_outside_the_allow_list_reproduces_nothing(self):
        report = support.grade('S4', support.ROOT / 'scenario_packs' / 'S4' /
                               'private' / 'known_bad' / 'unknown-export')
        self.assertEqual(support.failed_ids(report), ['A3'])
        self.assertEqual(report['details']['falsePositiveIds'], ['F-09'])
        self.assertIn('has no exported function', support.evidence(report, 'A3'))
        # The six genuine findings are untouched by the invalid one.
        self.assertEqual(report['details']['defectsMissed'], [])

    def test_arguments_cannot_smuggle_a_prototype(self):
        # Args are plain JSON, re-serialised by the supervisor and parsed with no reviver.
        poisoned = self.finding('sorting', 'sortNotes',
                                [[{'title': 'a', 'updatedAt': '2026-01-01T00:00:00.000Z',
                                   '__proto__': {'polluted': True}}]])
        with tempfile.TemporaryDirectory() as temp:
            candidate = support.submission(temp, None, FINDINGS__json={'findings': [poisoned]})
            report = support.grade('S4', candidate)
        self.assertNotIn('A1', support.failed_ids(report))   # schema-valid, just not a defect
        self.assertEqual(tamper_signals(report), [])

    def test_grading_the_traversal_fixture_twice_is_identical(self):
        path = support.ROOT / 'scenario_packs' / 'S4' / 'private' / 'known_bad' / 'path-traversal'
        self.assertEqual(support.grade('S4', path), support.grade('S4', path))


class GraderNeverWritesIntoTheCandidateTest(unittest.TestCase):
    """The property the split had to keep: the submission directory is read-only in practice."""

    def test_no_pack_writes_into_an_adversarial_candidate(self):
        cases = [('S5', 'report-forgery'), ('S6', 'report-forgery'), ('S4', 'path-traversal')]
        for pack, name in cases:
            with self.subTest(pack=pack, fixture=name):
                source = support.ROOT / 'scenario_packs' / pack / 'private' / 'known_bad' / name
                with tempfile.TemporaryDirectory() as temp:
                    candidate = support.submission(temp, source)
                    before = {str(p.relative_to(candidate)): (p.stat().st_size, p.read_bytes())
                              for p in sorted(candidate.rglob('*')) if p.is_file()}
                    report = support.grade(pack, candidate)
                    after = {str(p.relative_to(candidate)): (p.stat().st_size, p.read_bytes())
                             for p in sorted(candidate.rglob('*')) if p.is_file()}
                self.assertEqual(before, after)
                self.assertFalse(any('candidate directory was written to' in s
                                     for s in tamper_signals(report)))


if __name__ == '__main__':
    unittest.main()
