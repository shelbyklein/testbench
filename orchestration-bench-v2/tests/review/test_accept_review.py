"""Reviews are bound to the exact submission and evaluator they judged."""
import copy
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402

from bench_core import common, review_projection  # noqa: E402


class AcceptReviewTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ob2-review-')
        self.addCleanup(self.temp.cleanup)
        self.exp = Path(self.temp.name) / 'experiment'
        support.build_experiment(self.exp)
        self.projection = review_projection.build(self.exp, 'first')[0]
        self.run_id = review_projection.resolve_label(self.exp, self.projection['label'])['run']

    def accept(self, review=None, hash_value=None, version=None):
        return review_projection.accept_review(
            self.exp, self.projection['label'], 'first',
            hash_value or self.projection['submissionHash'],
            version or self.projection['evaluatorVersion'],
            review if review is not None else support.good_review())

    def test_accepted_review_is_stored_bound_to_the_submission(self):
        record = self.accept()
        stored = common.read(self.exp / 'results' / self.run_id / 'first' / 'review.json')
        self.assertEqual(stored, record)
        self.assertEqual(stored['submissionHash'], self.projection['submissionHash'])
        self.assertEqual(stored['evaluatorVersion'], support.EVALUATOR_VERSION)
        self.assertEqual(stored['label'], self.projection['label'])
        self.assertEqual(stored['reviewer'], 'anon-7')
        self.assertTrue(stored['savedAt'])
        data = common.read(self.exp / 'experiment.json')
        run = next(r for r in data['runs'] if r['id'] == self.run_id)
        self.assertEqual(run['phases']['first']['review']['label'], self.projection['label'])

    def test_history_is_preserved_on_resave(self):
        self.accept()
        second = support.good_review()
        second['notes'] = 'Second pass.'
        self.accept(review=second)
        history = self.exp / 'results' / self.run_id / 'first' / review_projection.HISTORY_DIR
        self.assertEqual(len(list(history.glob('*.json'))), 1)
        current = common.read(self.exp / 'results' / self.run_id / 'first' / 'review.json')
        self.assertEqual(current['notes'], 'Second pass.')

    def test_stale_hash_is_refused(self):
        target = self.exp / 'snapshots' / self.run_id / 'first' / 'src/app.mjs'
        target.write_text(target.read_text() + '// changed after projection\n')
        with self.assertRaises(review_projection.StaleReview):
            self.accept()
        self.assertFalse((self.exp / 'results' / self.run_id / 'first' / 'review.json').exists())

    def test_stale_evaluator_version_is_refused(self):
        data = common.read(self.exp / 'experiment.json')
        data['scenarios'][0]['grader']['version'] = '9.9.9'
        common.write(self.exp / 'experiment.json', data)
        with self.assertRaises(review_projection.StaleReview):
            self.accept()

    def test_hash_from_another_submission_is_refused(self):
        other = review_projection.build(self.exp, 'first')[1]
        with self.assertRaises(review_projection.StaleReview):
            self.accept(hash_value=other['submissionHash'])

    def test_repaired_label_cannot_be_saved_under_the_first_phase(self):
        repaired = review_projection.build(self.exp, 'repaired')[0]
        with self.assertRaises(review_projection.ReviewError):
            review_projection.accept_review(self.exp, repaired['label'], 'first',
                                            repaired['submissionHash'],
                                            repaired['evaluatorVersion'], support.good_review())

    def test_first_and_repaired_reviews_are_stored_separately(self):
        repaired = review_projection.build(self.exp, 'repaired')[0]
        paired_run = review_projection.resolve_label(self.exp, repaired['label'])['run']
        first = next(p for p in review_projection.build(self.exp, 'first')
                     if review_projection.resolve_label(self.exp, p['label'])['run'] == paired_run)
        review_projection.accept_review(self.exp, first['label'], 'first',
                                        first['submissionHash'], first['evaluatorVersion'],
                                        support.good_review())
        review_projection.accept_review(self.exp, repaired['label'], 'repaired',
                                        repaired['submissionHash'],
                                        repaired['evaluatorVersion'], support.good_review())
        run_id = review_projection.resolve_label(self.exp, repaired['label'])['run']
        first = common.read(self.exp / 'results' / run_id / 'first' / 'review.json')
        second = common.read(self.exp / 'results' / run_id / 'repaired' / 'review.json')
        self.assertNotEqual(first['label'], second['label'])
        self.assertNotEqual(first['submissionHash'], second['submissionHash'])

    def test_unknown_label_is_refused(self):
        with self.assertRaises(review_projection.ReviewError):
            review_projection.accept_review(self.exp, 'B-000000', 'first', 'x', 'y',
                                            support.good_review())

    def test_invalid_reviews_are_rejected(self):
        cases = {}
        missing_reviewer = support.good_review()
        missing_reviewer['reviewer'] = '  '
        cases['blank reviewer'] = missing_reviewer
        short_scores = support.good_review()
        short_scores['scores'].pop('ux')
        cases['missing dimension'] = short_scores
        bad_score = support.good_review()
        bad_score['scores']['ux'] = {'value': 5, 'evidence': 'x'}
        cases['out of range'] = bad_score
        no_evidence = support.good_review()
        no_evidence['scores']['ux'] = {'value': 2, 'evidence': ''}
        cases['scored without evidence'] = no_evidence
        wrong_manual = support.good_review()
        wrong_manual['manual'][0]['id'] = 'not-a-check'
        cases['wrong manual ids'] = wrong_manual
        executed_blank = support.good_review()
        executed_blank['manual'][1] = {'id': 'zm-mobile', 'status': 'fail', 'evidence': ''}
        cases['executed check without evidence'] = executed_blank
        bad_severity = support.good_review()
        bad_severity['defects'] = [{'severity': 'cosmetic', 'evidence': 'x'}]
        cases['unknown severity'] = bad_severity
        defect_blank = support.good_review()
        defect_blank['defects'] = [{'severity': 'major', 'evidence': ''}]
        cases['defect without evidence'] = defect_blank
        cases['not an object'] = 'looks good to me'
        for name, review in cases.items():
            with self.subTest(case=name):
                with self.assertRaises(review_projection.ReviewError):
                    self.accept(review=copy.deepcopy(review))
                self.assertFalse(
                    (self.exp / 'results' / self.run_id / 'first' / 'review.json').exists())

    def test_v1_experiment_refuses_a_review(self):
        v1 = support.build_v1_experiment(Path(self.temp.name) / 'v1')
        with self.assertRaises(review_projection.ReviewError):
            review_projection.accept_review(v1, self.projection['label'], 'first', 'x', 'y',
                                            support.good_review())


if __name__ == '__main__':
    unittest.main()
