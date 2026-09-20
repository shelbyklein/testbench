"""Prepared experiments: isolation, launch rendering, readiness gating and v1 compatibility."""
import json
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402

from bench_core import common, experiment, registry  # noqa: E402


class PreparedExperiment(unittest.TestCase):
    """A small data-only registry: two fixture methods and two fixture scenarios."""

    definition_id = 'fixture-comparison'

    def setUp(self):
        self._temp = tempfile.TemporaryDirectory(prefix='ob2-experiment-')
        self.addCleanup(self._temp.cleanup)
        self.base = Path(self._temp.name)
        self.root = support.copy_registry_root(self.base / 'root')
        support.add_fixture_scenario(self.root, 'FX1')
        support.add_fixture_scenario(self.root, 'FX2')
        support.add_method(self.root, 'fixture-a', configured=True)
        support.add_method(self.root, 'fixture-b', configured=True)
        support.add_definition(self.root, self.definition_id,
                               ['fixture-a', 'fixture-b'], ['FX1', 'FX2'], repeats=1, seed=77)
        self.registry = registry.load(self.root)
        self.exp = self.base / 'exp'

    def prepare(self):
        return experiment.prepare(self.root, self.definition_id, self.exp, self.registry)


class Preparation(PreparedExperiment):
    def test_prepare_creates_one_workspace_per_run_with_a_baseline_commit(self):
        data = self.prepare()
        self.assertEqual(data['format'], experiment.FORMAT)
        self.assertEqual(len(data['runs']), 4)
        for run in data['runs']:
            workspace = experiment.workspace_for(self.exp, run)
            self.assertTrue((workspace / 'TASK.md').is_file())
            self.assertTrue((workspace / 'AGENTS.md').is_file())
            self.assertTrue((workspace / 'LAUNCH.md').is_file())
            self.assertTrue((workspace / '.git').is_dir())
            self.assertRegex(run['baselineCommit'], r'^[0-9a-f]{40}$')
            self.assertTrue(run['initialHashes'])

    def test_private_material_and_scenario_json_never_reach_a_workspace(self):
        data = self.prepare()
        for run in data['runs']:
            workspace = experiment.workspace_for(self.exp, run)
            names = {p.name for p in workspace.rglob('*')}
            self.assertNotIn('scenario.json', names)
            self.assertNotIn('grade.mjs', names)
            self.assertNotIn('private', names)
            body = '\n'.join(p.read_text(errors='ignore') for p in workspace.rglob('*')
                             if p.is_file() and p.suffix in {'.md', '.txt', '.json'}
                             and '.git' not in p.parts)
            self.assertNotIn('known_bad', body)

    def test_private_directory_nested_inside_the_participant_source_is_not_copied(self):
        pack = self.root / 'scenario_packs' / 'FX1'
        hidden = pack / 'participant' / 'solutions'
        hidden.mkdir()
        (hidden / 'answer.txt').write_text('the widget answer\n')
        scenario = json.loads((pack / 'scenario.json').read_text())
        scenario['private'].append('scenario_packs/FX1/participant/solutions')
        support.write_json(pack / 'scenario.json', scenario)
        loaded = registry.load(self.root, strict=False)
        data = experiment.prepare(self.root, self.definition_id, self.exp, loaded)
        for run in data['runs']:
            if run['scenario'] != 'FX1':
                continue
            workspace = experiment.workspace_for(self.exp, run)
            self.assertFalse((workspace / 'solutions').exists())

    def test_pair_keys_group_runs_of_the_same_scenario_repeat_and_environment(self):
        data = self.prepare()
        groups = {}
        for run in data['runs']:
            groups.setdefault(run['pairKey'], []).append(run['method'])
        self.assertEqual(len(groups), 2)
        for methods in groups.values():
            self.assertEqual(sorted(methods), ['fixture-a', 'fixture-b'])

    def test_launch_text_comes_from_the_method_template(self):
        data = self.prepare()
        run = data['runs'][0]
        text = (experiment.workspace_for(self.exp, run) / 'LAUNCH.md').read_text()
        self.assertIn(run['id'], text)
        self.assertIn(run['scenario'], text)
        self.assertIn(str(experiment.workspace_for(self.exp, run)), text)
        self.assertNotIn('${', text)

    def test_preparing_twice_into_the_same_directory_is_refused(self):
        self.prepare()
        with self.assertRaises(ValueError):
            self.prepare()

    def test_policy_hashes_cover_the_compared_inputs(self):
        data = self.prepare()
        self.assertIn('scenario_packs/FX1/scenario.json', data['policyHashes'])
        self.assertIn('methods/fixture-a.json', data['policyHashes'])
        self.assertTrue(any(key.startswith('methods/templates/') for key in data['policyHashes']))


class Isolation(PreparedExperiment):
    def test_prepare_spawns_only_git_or_node_and_opens_no_socket(self):
        seen = []
        real_popen = subprocess.Popen

        class RecordingPopen(real_popen):
            def __init__(self, argv, *args, **kwargs):
                seen.append([argv] if isinstance(argv, str) else list(argv))
                super().__init__(argv, *args, **kwargs)

        def no_socket(*args, **kwargs):
            raise AssertionError('preparation must not open a network socket')

        with mock.patch.object(subprocess, 'Popen', RecordingPopen), \
                mock.patch.object(socket, 'socket', side_effect=no_socket), \
                mock.patch.object(socket, 'create_connection', side_effect=no_socket):
            data = self.prepare()
            for definition in registry.load(self.root).definitions.values():
                experiment.readiness(definition, self.registry)
        self.assertEqual(len(data['runs']), 4)
        self.assertTrue(seen, 'preparation is expected to invoke git')
        self.assertTrue(any(Path(argv[0]).name == 'git' for argv in seen))
        for argv in seen:
            self.assertIn(Path(argv[0]).name, {'git', 'node'}, f'unexpected process: {argv}')


class Readiness(PreparedExperiment):
    def test_a_fully_configured_definition_is_ready(self):
        state = experiment.readiness(self.registry.definition(self.definition_id), self.registry)
        self.assertTrue(state['ready'], state['blockers'])

    def test_unconfigured_method_blocks_readiness_and_names_what_is_missing(self):
        support.add_method(self.root, 'fixture-b', configured=False)
        loaded = registry.load(self.root)
        state = experiment.readiness(loaded.definition(self.definition_id), loaded)
        self.assertFalse(state['ready'])
        self.assertTrue(any('fixture-b' in blocker for blocker in state['blockers']))

    def test_readiness_is_never_stored_as_true(self):
        data = self.prepare()
        self.assertNotIn('ready', data['definition'])
        self.assertIn('readinessAtPrepare', data)


class Start(PreparedExperiment):
    def test_start_marks_a_ready_run_running_and_freezes_the_method(self):
        data = self.prepare()
        run_id = data['runs'][0]['id']
        run = experiment.start(self.exp, run_id)
        self.assertEqual(run['status'], 'running')
        self.assertTrue(run['methodFrozen'])
        with self.assertRaises(ValueError):
            experiment.start(self.exp, run_id)

    def test_start_is_refused_when_a_method_is_unconfigured(self):
        data = self.prepare()
        stored = common.read(self.exp / 'experiment.json')
        for method in stored['methods']:
            method['configured'] = False
            method['roles'][0]['model']['requested'] = 'RECORD WORKER MODEL'
        common.write(self.exp / 'experiment.json', stored)
        with self.assertRaises(ValueError) as caught:
            experiment.start(self.exp, data['runs'][0]['id'])
        self.assertIn('not ready', str(caught.exception))

    def test_start_is_refused_after_the_workspace_is_edited(self):
        data = self.prepare()
        run = data['runs'][0]
        (experiment.workspace_for(self.exp, run) / 'sneaky.txt').write_text('edited\n')
        with self.assertRaises(ValueError) as caught:
            experiment.start(self.exp, run['id'])
        self.assertIn('differs from its starting fixture', str(caught.exception))


class Compatibility(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory(prefix='ob2-compat-')
        self.addCleanup(self._temp.cleanup)
        self.dir = Path(self._temp.name)

    def test_v1_experiments_load_read_only(self):
        common.write(self.dir / 'experiment.json', {'version': 1, 'runs': []})
        data, writable = experiment.load(self.dir)
        self.assertFalse(writable)
        with self.assertRaises(ValueError):
            experiment.require_writable(data, writable)

    def test_v2_experiments_are_writable(self):
        common.write(self.dir / 'experiment.json',
                     {'format': experiment.FORMAT, 'version': 2, 'runs': []})
        data, writable = experiment.load(self.dir)
        self.assertTrue(writable)
        experiment.require_writable(data, writable)

    def test_unknown_formats_are_rejected(self):
        for payload in ({'version': 3}, {'format': 'ob2-experiment/2', 'version': 2}, {}):
            common.write(self.dir / 'experiment.json', payload)
            with self.assertRaises(ValueError):
                experiment.load(self.dir)


class Grading(PreparedExperiment):
    def test_evaluate_with_grader_validates_expected_check_ids(self):
        scenario = self.registry.scenario('FX1')
        candidate = self.base / 'candidate'
        candidate.mkdir()
        (candidate / 'answer.txt').write_text('the widget works\n')
        out = self.base / 'results' / 'evaluation.json'
        report = experiment.evaluate_with_grader(scenario, candidate, out, self.root)
        self.assertTrue(report['allPassed'])
        self.assertEqual(report['status'], 'complete')
        self.assertEqual({c['id'] for c in report['checks']}, {'X1', 'X2'})
        self.assertTrue(out.is_file())

    def test_a_failing_submission_is_reported_as_failing_not_as_an_error(self):
        scenario = self.registry.scenario('FX1')
        candidate = self.base / 'candidate-bad'
        candidate.mkdir()
        (candidate / 'answer.txt').write_text('nothing useful\n')
        report = experiment.evaluate_with_grader(scenario, candidate,
                                                 self.base / 'bad.json', self.root)
        self.assertFalse(report['allPassed'])
        self.assertEqual(report['status'], 'complete')
        self.assertEqual(report['passed'], 1)


if __name__ == '__main__':
    unittest.main()
