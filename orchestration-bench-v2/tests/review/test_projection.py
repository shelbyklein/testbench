"""The projection is an allow-list, its labels are stable, and its packages are sanitized."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402

from bench_core import common, review_projection  # noqa: E402

ALLOWED_KEYS = {'contract', 'label', 'scenario', 'scenarioVersion', 'repeat', 'phase',
                'submissionHash', 'evaluatorVersion', 'files', 'evaluation', 'reviewTemplate',
                'residualCues'}


class ProjectionTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ob2-review-')
        self.addCleanup(self.temp.cleanup)
        self.exp = Path(self.temp.name) / 'experiment'
        support.build_experiment(self.exp)
        self.terms = review_projection.forbidden_terms(self.exp)

    # ------------------------------------------------------------ shape
    def test_projection_has_only_allow_listed_fields(self):
        projections = review_projection.build(self.exp, 'first')
        self.assertEqual(len(projections), 3)
        for projection in projections:
            self.assertEqual(set(projection), ALLOWED_KEYS)
            self.assertEqual(projection['contract'], 'review-projection/1')
            self.assertEqual(projection['scenario'], support.SCENARIO_ID)
            self.assertEqual(projection['evaluatorVersion'], support.EVALUATOR_VERSION)
            self.assertIn('best-effort', projection['residualCues'])

    def test_projection_payload_contains_no_operator_term(self):
        for projection in review_projection.build(self.exp, 'first'):
            leaks = review_projection.scan(projection, self.terms)
            self.assertEqual(leaks, [], f'projection leaked: {leaks}')

    def test_forbidden_terms_include_the_identities_the_fixture_planted(self):
        for expected in ('Zebra-Method-Q7', 'ModelXYZ-9', 'zebramode', 'run-zz0001',
                         str(self.exp.resolve())):
            self.assertIn(expected, self.terms)

    # ------------------------------------------------------------ files
    def test_files_exclude_identity_hidden_and_symlinked_entries(self):
        projection = review_projection.build(self.exp, 'first')[0]
        paths = {entry['path'] for entry in projection['files']}
        self.assertEqual(paths, {'src/app.mjs', 'src/cue.mjs', 'README.md',
                                 'tests/smoke.test.mjs'})
        for name in review_projection.IDENTITY_FILES:
            self.assertNotIn(name, paths)
        self.assertNotIn(f'{support.PRIVATE_DIR}/expected.json', paths)
        self.assertNotIn('src/link.mjs', paths)

    def test_submission_hash_is_the_visible_inventory_hash(self):
        projection = review_projection.build(self.exp, 'first')[0]
        inventory = {entry['path']: entry['sha256'] for entry in projection['files']}
        self.assertEqual(projection['submissionHash'], common.inventory_hash(inventory))
        run_id = review_projection.resolve_label(self.exp, projection['label'])['run']
        self.assertEqual(projection['submissionHash'],
                         review_projection.submission_hash(self.exp, run_id, 'first'))

    def test_hash_changes_when_the_snapshot_is_tampered_with(self):
        projection = review_projection.build(self.exp, 'first')[0]
        run_id = review_projection.resolve_label(self.exp, projection['label'])['run']
        target = self.exp / 'snapshots' / run_id / 'first' / 'src/app.mjs'
        target.write_text(target.read_text() + '// late edit\n')
        self.assertNotEqual(projection['submissionHash'],
                            review_projection.submission_hash(self.exp, run_id, 'first'))

    def test_identity_file_edits_do_not_change_the_submission_hash(self):
        """The hash covers what the reviewer sees, so operator files cannot shift it."""
        projection = review_projection.build(self.exp, 'first')[0]
        run_id = review_projection.resolve_label(self.exp, projection['label'])['run']
        (self.exp / 'snapshots' / run_id / 'first' / 'LAUNCH.md').write_text('rewritten\n')
        self.assertEqual(projection['submissionHash'],
                         review_projection.submission_hash(self.exp, run_id, 'first'))

    # ------------------------------------------------------------ evaluation
    def test_evaluation_is_reduced_to_id_description_status(self):
        projection = review_projection.build(self.exp, 'first')[0]
        evaluation = projection['evaluation']
        self.assertEqual(set(evaluation), {'checks', 'passed', 'total'})
        self.assertEqual(evaluation['total'], 2)
        for check in evaluation['checks']:
            self.assertEqual(set(check), {'id', 'description', 'status'})
            self.assertIn(check['status'], ('pass', 'fail'))
        blob = common.canonical(evaluation)
        for hidden in ('evidence', 'runner', 'stdout', 'stderr', 'details', 'AssertionError',
                       str(self.exp)):
            self.assertNotIn(hidden, blob)

    # ------------------------------------------------------------ template
    def test_review_template_uses_scenario_manual_checks_and_the_five_dimensions(self):
        template = review_projection.build(self.exp, 'first')[0]['reviewTemplate']
        self.assertEqual(template['dimensions'], list(review_projection.DIMENSIONS))
        self.assertEqual([c['id'] for c in template['manualChecks']],
                         ['zm-keyboard', 'zm-mobile'])
        blank = template['blank']
        self.assertEqual(set(blank['scores']), set(review_projection.DIMENSIONS))
        self.assertTrue(all(item['status'] == 'not_run' for item in blank['manual']))

    # ------------------------------------------------------------ labels
    def test_labels_are_stable_across_rebuilds(self):
        first = {p['label']: p['submissionHash'] for p in review_projection.build(self.exp, 'first')}
        second = {p['label']: p['submissionHash'] for p in review_projection.build(self.exp, 'first')}
        self.assertEqual(first, second)
        for label in first:
            self.assertRegex(label, r'^B-[0-9A-F]{6}$')

    def test_first_and_repaired_are_separate_labels_and_packages(self):
        first = review_projection.build(self.exp, 'first')
        repaired = review_projection.build(self.exp, 'repaired')
        self.assertEqual(len(repaired), 1)
        self.assertFalse({p['label'] for p in first} & {p['label'] for p in repaired})
        first_run = {review_projection.resolve_label(self.exp, p['label'])['run'] for p in first}
        repaired_run = review_projection.resolve_label(self.exp, repaired[0]['label'])['run']
        self.assertIn(repaired_run, first_run)
        by_run = {review_projection.resolve_label(self.exp, p['label'])['run']: p for p in first}
        self.assertNotEqual(by_run[repaired_run]['submissionHash'], repaired[0]['submissionHash'])

    def test_listing_order_is_label_order_not_schedule_order(self):
        projections = review_projection.build(self.exp, 'first')
        labels = [p['label'] for p in projections]
        self.assertEqual(labels, sorted(labels))
        data = common.read(self.exp / 'experiment.json')
        data['runs'] = list(reversed(data['runs']))
        common.write(self.exp / 'experiment.json', data)
        self.assertEqual([p['label'] for p in review_projection.build(self.exp, 'first')], labels)

    def test_review_map_stays_operator_side(self):
        review_projection.build(self.exp, 'first')
        mapping = common.read(self.exp / review_projection.MAP_FILE)
        self.assertEqual(set(mapping['labels'].values()), set(mapping['byLabel']))
        self.assertIn('run-zz0001|first', mapping['labels'])

    # ------------------------------------------------------------ export
    def test_export_packages_are_sanitized(self):
        out = Path(self.temp.name) / 'packages'
        packages = review_projection.export(self.exp, 'first', out)
        self.assertEqual(len(packages), 3)
        leaks = review_projection.scan(out, self.terms)
        hard = [leak for leak in leaks if leak['kind'] == 'leak']
        self.assertEqual(hard, [], f'export leaked: {hard}')
        cues = [leak for leak in leaks if leak['kind'] == 'residualCue']
        self.assertTrue(cues, 'the planted residual cue in submitted source must be reported')
        self.assertTrue(all('cue.mjs' in cue['where'] for cue in cues))

    def test_export_contents_and_names(self):
        out = Path(self.temp.name) / 'packages'
        for package in review_projection.export(self.exp, 'first', out):
            names = {p.relative_to(package).as_posix() for p in package.rglob('*') if p.is_file()}
            self.assertEqual(names, {'projection.json', 'review.json', 'REVIEW.md',
                                     'submission/src/app.mjs', 'submission/src/cue.mjs',
                                     'submission/README.md', 'submission/tests/smoke.test.mjs'})
            projection = common.read(package / 'projection.json')
            self.assertEqual(projection['label'], package.name)
            blank = common.read(package / 'review.json')
            self.assertEqual([item['id'] for item in blank['manual']],
                             ['zm-keyboard', 'zm-mobile'])
            markdown = (package / 'REVIEW.md').read_text()
            self.assertIn('Reviewer rubric', markdown)
            self.assertIn('anonymized coding submissions', markdown)

    # ------------------------------------------------------------ refusals
    def test_v1_experiment_is_refused(self):
        v1 = support.build_v1_experiment(Path(self.temp.name) / 'v1')
        with self.assertRaises(review_projection.ReviewError):
            review_projection.build(v1, 'first')
        with self.assertRaises(review_projection.ReviewError):
            review_projection.export(v1, 'first', Path(self.temp.name) / 'v1-out')
        self.assertFalse((v1 / review_projection.MAP_FILE).exists())

    def test_unevaluated_submissions_are_not_projected(self):
        (self.exp / 'results' / 'run-zz0002' / 'first' / 'evaluation.json').unlink()
        labels = {review_projection.resolve_label(self.exp, p['label'])['run']
                  for p in review_projection.build(self.exp, 'first')}
        self.assertNotIn('run-zz0002', labels)


if __name__ == '__main__':
    unittest.main()
