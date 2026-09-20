"""The S4 participant brief must give away no answer (review finding F4).

The brief's worked example used to be byte-identical to the private oracle witness for a seeded
defect and to reference finding F-01 — same module, same export, same args, same severity — so
reading TASK.md handed a participant one of the six defects, its reproduction and its severity
for free.

These tests are structural: they parse every JSON example out of TASK.md and grade it through
the real S4 grader. Everything is offline and fixture-tested.
"""
import json
import re
import tempfile
import unittest
from pathlib import Path

from tests.scenarios import support

PACK = support.ROOT / 'scenario_packs' / 'S4'
TASK = PACK / 'participant' / 'TASK.md'
INVENTORY = json.loads((PACK / 'private' / 'inventory.json').read_text())
MODULES = {p.stem for p in (PACK / 'participant' / 'src').glob('*.mjs')}


def examples():
    """Every ``reproduction`` object that appears in a JSON code block of the brief."""
    found = []
    for block in re.findall(r'```json\n(.*?)```', TASK.read_text(), re.S):
        try:
            parsed = json.loads(block)
        except json.JSONDecodeError:
            continue
        findings = parsed.get('findings') if isinstance(parsed, dict) else parsed
        for finding in findings or []:
            if isinstance(finding, dict) and isinstance(finding.get('reproduction'), dict):
                found.append(finding)
    return found


class ExampleIsFictionalTest(unittest.TestCase):
    def test_the_brief_carries_at_least_one_worked_example(self):
        self.assertTrue(examples(), 'TASK.md no longer shows the FINDINGS.json shape')

    def test_no_example_names_a_real_module(self):
        for finding in examples():
            self.assertNotIn(finding['reproduction']['module'], MODULES, finding['id'])
            self.assertNotIn(finding['module'], MODULES, finding['id'])

    def test_no_example_names_a_real_export(self):
        exports = {d['export'] for d in INVENTORY['defects']} | {n['export'] for n in INVENTORY['nonbugs']}
        for finding in examples():
            self.assertNotIn(finding['reproduction']['export'], exports, finding['id'])

    def test_the_brief_says_the_example_is_fictional(self):
        text = TASK.read_text()
        self.assertIn('shape only', text)
        self.assertRegex(text, r'no `?\w+`? module in `src/`|does not exist')

    def test_no_example_matches_an_oracle_or_inventory_witness(self):
        witnesses = {(d['module'], d['export'], json.dumps(d['witness']['args'], sort_keys=True))
                     for d in INVENTORY['defects']}
        pairs = {(d['module'], d['export']) for d in INVENTORY['defects']}
        for finding in examples():
            repro = finding['reproduction']
            key = (repro['module'], repro['export'], json.dumps(repro.get('args'), sort_keys=True))
            self.assertNotIn(key, witnesses, f"{finding['id']} is a private oracle witness")
            self.assertNotIn((repro['module'], repro['export']), pairs,
                             f"{finding['id']} names a seeded defect's (module, export)")

    def test_no_example_matches_a_reference_finding(self):
        reference = json.loads((PACK / 'private' / 'reference' / 'FINDINGS.json').read_text())
        known = {json.dumps(f['reproduction'], sort_keys=True) for f in reference['findings']}
        severities = {(f['reproduction']['module'], f['severity']) for f in reference['findings']}
        for finding in examples():
            self.assertNotIn(json.dumps(finding['reproduction'], sort_keys=True), known,
                             f"{finding['id']} is a reference finding verbatim")
            self.assertNotIn((finding['reproduction']['module'], finding['severity']), severities)

    def test_the_example_demonstrates_nothing_when_graded(self):
        """The strongest form: submit the brief's example and it earns no defect at all."""
        findings = examples()
        with tempfile.TemporaryDirectory() as temp:
            candidate = support.submission(temp, None, FINDINGS__json={'findings': findings})
            report = support.grade('S4', candidate)
        self.assertEqual(report['details']['defectsFound'], [])
        self.assertEqual(report['details']['reproducingCount'], 0)
        self.assertEqual(sorted(report['details']['defectsMissed']),
                         sorted(d['id'] for d in INVENTORY['defects']))
        # It names a module that does not exist, so it never even runs.
        self.assertIn('A1', support.failed_ids(report))
        self.assertIn('must name one of the modules in src/', support.evidence(report, 'A1'))

    def test_the_brief_leaks_no_defect_summary(self):
        text = TASK.read_text().lower()
        for defect in INVENTORY['defects']:
            self.assertNotIn(f"{defect['module']}.{defect['export']}".lower(), text)
            self.assertNotIn(defect['id'].lower(), text)


class BriefVersionTest(unittest.TestCase):
    def test_the_scenario_version_moved_with_the_brief(self):
        scenario = support.scenario('S4')
        self.assertEqual(scenario['version'], '1.1.0')
        self.assertEqual(scenario['grader']['version'], '1.1.0')


if __name__ == '__main__':
    unittest.main()
