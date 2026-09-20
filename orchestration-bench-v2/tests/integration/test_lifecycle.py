"""Integration regressions found while wiring the lanes together (synthetic, offline)."""
import contextlib
import io
import unittest
from pathlib import Path

import validate
from bench_core import common, registry

ROOT = Path(__file__).resolve().parents[2]


class SyntheticLifecycle(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with contextlib.redirect_stdout(io.StringIO()):
            cls.result = validate.lifecycle()
        cls.exp = ROOT / cls.result['experiment']

    def test_full_lifecycle_runs_without_provider_or_network(self):
        self.assertTrue(self.result['synthetic'])
        self.assertLessEqual(set(self.result['processesSpawned']), {'git', 'node'})

    def test_shipped_saved_records_reach_workspace_and_snapshot(self):
        # A global `data` exclusion once dropped S5's saved records before grading.
        for run in common.read(self.exp / 'experiment.json')['runs']:
            self.assertTrue((self.exp / 'workspaces' / run['id'] / 'data' / 'notes.json').is_file())
            self.assertIn('data/notes.json', common.read(self.exp / 'receipts' / run['id'] / 'first.json')['hashes'])

    def test_runtime_data_of_the_v1_app_stays_out_of_captures(self):
        self.assertIn('data', common.excluded_for(registry.load(ROOT).scenario('S1')))

    def test_reference_passes_and_partial_migration_needs_repair(self):
        gates = self.result['gates']
        self.assertEqual(gates['Synthetic A']['first'], 'Meets acceptance')
        self.assertEqual(gates['Synthetic B']['first'], 'Automated checks failed')
        self.assertIn('repaired', gates['Synthetic B'])


if __name__ == '__main__':
    unittest.main()
