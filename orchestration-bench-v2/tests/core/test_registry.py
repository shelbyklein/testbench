"""Registry behaviour: data-only extensibility, discovery and invalid-configuration rejection."""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402

from bench_core import registry  # noqa: E402


class TempRoot(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory(prefix='ob2-registry-')
        self.addCleanup(self._temp.cleanup)
        self.root = support.copy_registry_root(Path(self._temp.name) / 'root')


class ShippedRegistry(unittest.TestCase):
    def test_shipped_registry_is_valid(self):
        self.assertEqual(registry.validate(support.ROOT), [])

    def test_every_shipped_method_and_scenario_is_discovered_by_listing(self):
        loaded = registry.load(support.ROOT)
        on_disk = {json.loads(p.read_text())['id']
                   for p in (support.ROOT / 'methods').glob('*.json')
                   if isinstance(json.loads(p.read_text()), dict)}
        self.assertEqual(set(loaded.methods), on_disk)
        packs = {p.name for p in (support.ROOT / 'scenario_packs').iterdir()
                 if (p / 'scenario.json').is_file()}
        self.assertEqual(set(loaded.scenarios), packs)

    def test_legacy_non_object_json_in_methods_is_ignored(self):
        legacy = [p for p in (support.ROOT / 'methods').glob('*.json')
                  if isinstance(json.loads(p.read_text()), list)]
        self.assertTrue(legacy, 'expected at least one v1 carry-over list file to still be present')
        self.assertEqual(registry.validate(support.ROOT), [])


class Extensibility(TempRoot):
    def test_extra_method_and_scenario_are_added_by_writing_files_only(self):
        before = registry.load(self.root)
        support.add_method(self.root, 'fixture-extra', configured=True)
        support.add_fixture_scenario(self.root)
        after = registry.load(self.root)
        self.assertEqual(set(after.methods) - set(before.methods), {'fixture-extra'})
        self.assertEqual(set(after.scenarios) - set(before.scenarios), {'FX1'})
        self.assertEqual(after.errors, [])

    def test_a_definition_may_reference_the_new_data_only_entries(self):
        support.add_method(self.root, 'fixture-extra', configured=True)
        support.add_fixture_scenario(self.root)
        support.add_definition(self.root, 'fixture-comparison', ['fixture-extra'], ['FX1'])
        loaded = registry.load(self.root)
        self.assertIn('fixture-comparison', loaded.definitions)
        self.assertEqual(loaded.definition('fixture-comparison')['scenarios'], ['FX1'])


class Rejection(TempRoot):
    def assert_error(self, fragment):
        errors = registry.validate(self.root)
        self.assertTrue(any(fragment in error for error in errors),
                        f'expected an error containing {fragment!r}; got {errors}')
        with self.assertRaises(ValueError):
            registry.load(self.root)

    def test_duplicate_method_ids_are_rejected(self):
        support.add_method(self.root, 'fixture-extra')
        shutil.copyfile(self.root / 'methods' / 'fixture-extra.json',
                        self.root / 'methods' / 'fixture-extra-copy.json')
        self.assert_error('duplicate ID')

    def test_duplicate_scenario_ids_are_rejected(self):
        support.add_fixture_scenario(self.root, 'FX1')
        second = support.add_fixture_scenario(self.root, 'FX2')
        data = json.loads((second / 'scenario.json').read_text())
        data['id'] = 'FX1'
        support.write_json(second / 'scenario.json', data)
        self.assert_error('duplicate ID')

    def test_missing_grader_file_is_rejected(self):
        pack = support.add_fixture_scenario(self.root)
        os.remove(pack / 'private' / 'grade.mjs')
        self.assert_error('grader file not found')

    def test_unknown_contract_string_is_rejected(self):
        support.add_method(self.root, 'fixture-extra', contract='method/99')
        self.assert_error('incompatible contract')

    def test_configured_method_with_placeholders_is_rejected(self):
        support.add_method(self.root, 'fixture-extra', configured=True)
        path = self.root / 'methods' / 'fixture-extra.json'
        data = json.loads(path.read_text())
        data['transport'] = 'RECORD TRANSPORT'
        support.write_json(path, data)
        self.assert_error('placeholders')

    def test_configured_method_without_a_requested_model_is_rejected(self):
        support.add_method(self.root, 'fixture-extra', configured=True)
        path = self.root / 'methods' / 'fixture-extra.json'
        data = json.loads(path.read_text())
        data['roles'][0]['model']['requested'] = None
        support.write_json(path, data)
        self.assert_error('no requested model')

    def test_participant_source_overlapping_a_private_path_is_rejected(self):
        pack = support.add_fixture_scenario(self.root)
        data = json.loads((pack / 'scenario.json').read_text())
        data['private'].append(data['participant']['source'])
        support.write_json(pack / 'scenario.json', data)
        self.assert_error('overlaps private path')

    def test_private_path_inside_participant_source_is_rejected(self):
        pack = support.add_fixture_scenario(self.root)
        hidden = pack / 'participant' / 'answers'
        hidden.mkdir()
        (hidden / 'answer.txt').write_text('widget\n')
        data = json.loads((pack / 'scenario.json').read_text())
        data['private'].append(f'{data["participant"]["source"]}/answers')
        support.write_json(pack / 'scenario.json', data)
        self.assert_error('overlaps private path')

    def test_definition_referencing_unknown_ids_is_rejected(self):
        support.add_definition(self.root, 'fixture-comparison', ['no-such-method'], ['NOPE'])
        self.assert_error('is not in the registry')

    def test_definition_may_not_store_readiness(self):
        support.add_method(self.root, 'fixture-extra', configured=True)
        support.add_fixture_scenario(self.root)
        support.add_definition(self.root, 'fixture-comparison', ['fixture-extra'], ['FX1'], ready=True)
        self.assert_error('readiness is computed')

    def test_missing_launch_template_is_rejected(self):
        support.add_method(self.root, 'fixture-extra')
        os.remove(self.root / 'methods' / 'templates' / 'fixture-extra.md')
        self.assert_error('launch template not found')


class Calibration(TempRoot):
    def test_reference_passes_and_known_bad_is_caught_with_its_reason(self):
        support.add_fixture_scenario(self.root)
        scenario = registry.load(self.root).scenario('FX1')
        report = registry.calibrate(scenario, self.root)
        self.assertEqual(report['status'], 'ok', report['problems'])
        self.assertTrue(report['reference']['allPassed'])
        entry = report['known_bad'][0]
        self.assertTrue(entry['detected'])
        self.assertIn('X2', entry['failed'])
        self.assertTrue(any(reason for reason in entry['reasons']),
                        'the calibration report must carry the reason the fixture failed')

    def test_uncalibrated_scenario_reports_unavailable_rather_than_success(self):
        support.add_fixture_scenario(self.root, 'FX2', calibrated=False)
        scenario = registry.load(self.root).scenario('FX2')
        report = registry.calibrate(scenario, self.root)
        self.assertEqual(report['status'], 'unavailable')
        self.assertTrue(report['problems'])

    def test_known_bad_that_is_not_caught_is_reported_as_failed(self):
        pack = support.add_fixture_scenario(self.root)
        data = json.loads((pack / 'scenario.json').read_text())
        data['calibration']['known_bad'][0]['must_fail'] = ['X1', 'X2']
        support.write_json(pack / 'scenario.json', data)
        report = registry.calibrate(registry.load(self.root).scenario('FX1'), self.root)
        self.assertEqual(report['status'], 'failed')
        self.assertFalse(report['known_bad'][0]['detected'])


class GraderContract(TempRoot):
    def test_grader_ids_must_match_the_scenario_contract(self):
        pack = support.add_fixture_scenario(self.root)
        data = json.loads((pack / 'scenario.json').read_text())
        data['grader']['expected_check_ids'] = ['X1', 'X2', 'X3']
        support.write_json(pack / 'scenario.json', data)
        scenario = registry.load(self.root).scenario('FX1')
        with tempfile.TemporaryDirectory() as temp:
            candidate = Path(temp) / 'submission'
            candidate.mkdir()
            (candidate / 'answer.txt').write_text('widget\n')
            with self.assertRaises(ValueError) as caught:
                registry.run_grader(scenario, candidate, Path(temp) / 'out.json', self.root)
        self.assertIn('X3', str(caught.exception))

    def test_grader_evidence_does_not_leak_candidate_absolute_paths(self):
        support.add_fixture_scenario(self.root)
        scenario = registry.load(self.root).scenario('FX1')
        with tempfile.TemporaryDirectory() as temp:
            candidate = Path(temp) / 'submission'
            candidate.mkdir()
            (candidate / 'answer.txt').write_text('widget\n')
            report, process = registry.run_grader(scenario, candidate, Path(temp) / 'out.json', self.root)
            self.assertEqual(process['exitCode'], 0)
            self.assertNotIn(str(candidate.resolve()), json.dumps(report))
            self.assertIn('<submission>', json.dumps(report))


if __name__ == '__main__':
    unittest.main()
