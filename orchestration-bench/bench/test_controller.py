"""Fast invariant checks. Run: python3 -m unittest discover -s bench -p 'test_*.py'"""
import copy
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('controller', ROOT/'bench.py')
bench = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bench)

class ReviewGates(unittest.TestCase):
    def complete_review(self):
        review=bench.blank_review('S1');review['reviewer']='unit-test'
        for score in review['scores'].values():score.update(value=2,evidence='Synthetic unit-test evidence')
        for item in review['manual']:item.update(status='pass',evidence='Synthetic unit-test evidence')
        return review

    def test_unreviewed_is_not_accepted(self):
        self.assertEqual(bench.gate({'status':'complete','allPassed':True},None),'Manual review pending')
    def test_complete_evidence_can_meet_acceptance(self):
        review=self.complete_review();bench.validate_review(review,'S1')
        self.assertEqual(bench.gate({'status':'complete','allPassed':True},review),'Meets acceptance')
    def test_major_defect_blocks_polished_result(self):
        review=self.complete_review();review['defects']=[{'severity':'major','evidence':'Synthetic broken workflow'}]
        self.assertEqual(bench.gate({'status':'complete','allPassed':True},review),'Serious defect remains')
    def test_low_rubric_score_blocks_acceptance(self):
        review=self.complete_review();review['scores']['maintainability']['value']=1
        self.assertEqual(bench.gate({'status':'complete','allPassed':True},review),'Quality bar not met')
    def test_missing_or_duplicate_manual_checks_rejected(self):
        review=self.complete_review();review['manual'][1]=copy.deepcopy(review['manual'][0])
        with self.assertRaises(ValueError):bench.validate_review(review,'S1')
    def test_scores_require_evidence(self):
        review=self.complete_review();review['scores']['ux']['evidence']=''
        with self.assertRaises(ValueError):bench.validate_review(review,'S1')
    def test_evaluator_error_is_not_a_functional_pass(self):
        self.assertEqual(bench.gate({'status':'error','allPassed':False},self.complete_review()),'Evaluation error')
    def test_unexecuted_manual_check_stays_pending(self):
        review=self.complete_review();review['manual'][0].update(status='not_run',evidence='')
        self.assertEqual(bench.gate({'status':'complete','allPassed':True},review),'Manual review pending')

if __name__=='__main__':unittest.main()
