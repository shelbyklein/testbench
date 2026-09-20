"""Registry health, participant/private separation and workspace contamination for S4 and S5."""
import json
import re
import tempfile
import unittest
from pathlib import Path

from tests.scenarios import support
from bench_core import registry, experiment

PACKS = ('S4', 'S5')
TEXT_SUFFIXES = {'.md', '.mjs', '.js', '.json', '.txt', '.html', '.css'}


def participant_files(pack_id):
    root = support.ROOT / 'scenario_packs' / pack_id / 'participant'
    return [p for p in sorted(root.rglob('*')) if p.is_file()]


class RegistryTest(unittest.TestCase):
    def test_registry_validate_stays_clean(self):
        self.assertEqual(registry.validate(support.ROOT), [])

    def test_both_packs_are_loaded_with_the_scenario_contract(self):
        loaded = registry.load(support.ROOT, strict=False)
        for pack_id in PACKS:
            scenario = loaded.scenario(pack_id)
            self.assertEqual(scenario['contract'], 'scenario/1')
            self.assertEqual(scenario['version'], '1.0.0')
            self.assertEqual(scenario['grader']['version'], '1.0.0')

    def test_calibration_paths_are_real_directories(self):
        loaded = registry.load(support.ROOT, strict=False)
        for pack_id in PACKS:
            calibration = loaded.scenario(pack_id)['calibration']
            self.assertTrue((support.ROOT / calibration['reference']).is_dir())
            self.assertTrue(calibration['known_bad'])
            for fixture in calibration['known_bad']:
                self.assertTrue((support.ROOT / fixture['path']).is_dir(), fixture['path'])
                self.assertTrue(fixture['must_fail'])


class ContaminationTest(unittest.TestCase):
    def test_no_participant_file_references_private_material(self):
        forbidden = ['private', 'inventory', 'oracle', 'reference/', 'known_bad', 'grade.mjs',
                     'aggregate.mjs']
        inventory = json.loads(
            (support.ROOT / 'scenario_packs' / 'S4' / 'private' / 'inventory.json').read_text())
        forbidden += [d['id'] for d in inventory['defects']]
        forbidden += [n['id'] for n in inventory['nonbugs']]
        for pack_id in PACKS:
            for path in participant_files(pack_id):
                if path.suffix not in TEXT_SUFFIXES:
                    continue
                text = path.read_text()
                for term in forbidden:
                    self.assertNotIn(term, text, f'{path} mentions {term!r}')

    def test_no_participant_file_contains_reference_solution_content(self):
        markers = ['requireV2', 'migrateRecord', 'SCHEMA_VERSION', 'schemaVersion: 2']
        for path in participant_files('S5'):
            if path.suffix not in TEXT_SUFFIXES or path.name == 'TASK.md':
                continue
            text = path.read_text()
            for marker in markers:
                self.assertNotIn(marker, text, f'{path} leaks reference content {marker!r}')

    def test_participant_source_never_overlaps_a_private_path(self):
        loaded = registry.load(support.ROOT, strict=False)
        for pack_id in PACKS:
            scenario = loaded.scenario(pack_id)
            source = Path(scenario['participant']['source']).parts
            for private in scenario['private']:
                parts = Path(private).parts
                shortest = min(len(source), len(parts))
                self.assertNotEqual(source[:shortest], parts[:shortest])

    def test_prepare_copies_nothing_private_into_a_workspace(self):
        with tempfile.TemporaryDirectory(prefix='ob2-scenarios-') as temp:
            root = support.copy_registry_root(Path(temp) / 'root')
            definition = {
                'contract': 'experiment-definition/1', 'id': 'scenarios-lane-fixture',
                'title': 'Scenarios lane fixture', 'question': 'Does prepare leak private material?',
                'establishes': 'Workspace isolation only.',
                'methods': [], 'scenarios': list(PACKS), 'repeats': 1, 'seed': 20260920,
                'phases': ['first'],
                'environment': {'id': 'fixture-env', 'notes': 'Scenarios lane fixture.'},
                'controls': {'same_external_grading': True, 'repair_feedback': 'identical',
                             'fixed_worker': None, 'internal_reviewer': None}}
            path = root / 'experiments' / 'definitions' / 'scenarios-lane-fixture.json'
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(definition, indent=2) + '\n')

            loaded = registry.load(root, strict=False)
            out = Path(temp) / 'prepared'
            for pack_id in PACKS:
                scenario = loaded.scenario(pack_id)
                workspace = out / pack_id
                experiment._copy_participant(root, scenario, workspace)
                copied = [p for p in workspace.rglob('*') if p.is_file()]
                self.assertTrue(copied, f'{pack_id}: nothing was copied')
                names = {str(p.relative_to(workspace)) for p in copied}
                self.assertIn('TASK.md', names)
                self.assertNotIn('scenario.json', names)
                for path in copied:
                    self.assertNotIn('private', str(path.relative_to(workspace)))
                    if path.suffix in TEXT_SUFFIXES:
                        self.assertNotIn('grade.mjs', path.read_text())
                for private in scenario['private']:
                    leaf = Path(private).name
                    self.assertFalse((workspace / leaf).exists())

    def test_public_checks_reference_only_participant_files(self):
        loaded = registry.load(support.ROOT, strict=False)
        for pack_id in PACKS:
            scenario = loaded.scenario(pack_id)
            for check in scenario['public_checks']:
                for token in check:
                    self.assertNotIn('private', token)
                    if '/' in token:
                        self.assertTrue(
                            (support.ROOT / 'scenario_packs' / pack_id / 'participant' / token).exists(),
                            f'{pack_id}: public check path {token} is not in the participant source')


class GraderHygieneTest(unittest.TestCase):
    def test_graders_declare_the_check_ids_the_scenario_promises(self):
        loaded = registry.load(support.ROOT, strict=False)
        for pack_id, fixture in (('S4', 'private/reference'), ('S5', 'private/reference')):
            scenario = loaded.scenario(pack_id)
            report = support.grade(pack_id, support.ROOT / 'scenario_packs' / pack_id / fixture)
            self.assertEqual(sorted(c['id'] for c in report['checks']),
                             sorted(scenario['grader']['expected_check_ids']))
            self.assertEqual(report['total'], len(report['checks']))
            self.assertEqual(report['passed'],
                             len([c for c in report['checks'] if c['status'] == 'pass']))

    def test_every_check_carries_evidence(self):
        for pack_id in PACKS:
            report = support.grade(pack_id, support.ROOT / 'scenario_packs' / pack_id / 'private' / 'reference')
            for check in report['checks']:
                self.assertTrue(check.get('description'))
                self.assertTrue(check.get('evidence'), check['id'])

    def test_graders_never_name_an_absolute_home_path(self):
        for pack_id in PACKS:
            for path in (support.ROOT / 'scenario_packs' / pack_id / 'private').rglob('*.mjs'):
                self.assertIsNone(re.search(r'/Users/[A-Za-z0-9_.-]+', path.read_text()),
                                  f'{path} contains an absolute home path')


if __name__ == '__main__':
    unittest.main()
