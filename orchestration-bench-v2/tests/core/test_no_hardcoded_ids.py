"""Adding a method or a scenario must be a data change, so the core modules may not name one."""
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402

from bench_core import registry  # noqa: E402

MODULES = ('bench_core/registry.py', 'bench_core/schedule.py', 'bench_core/experiment.py')


class NoHardcodedIdentifiers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = registry.load(support.ROOT)
        cls.sources = {name: (support.ROOT / name).read_text() for name in MODULES}

    def test_no_module_names_a_method_id(self):
        for method_id in self.registry.methods:
            pattern = re.compile(rf'(?<![\w-]){re.escape(method_id)}(?![\w-])')
            for name, source in self.sources.items():
                with self.subTest(module=name, method=method_id):
                    self.assertIsNone(pattern.search(source),
                                      f'{name} names the method ID {method_id!r}')

    def test_no_module_names_a_method_mode(self):
        for method in self.registry.methods.values():
            for name, source in self.sources.items():
                with self.subTest(module=name, mode=method['mode']):
                    self.assertNotIn(method['mode'], source)

    def test_no_module_names_a_scenario_id(self):
        # Slugs are prose and may collide with ordinary English; the ID is the branch key.
        for scenario in self.registry.scenarios.values():
            token = scenario['id']
            pattern = re.compile(rf'(?<![\w-]){re.escape(token)}(?![\w-])')
            for name, source in self.sources.items():
                with self.subTest(module=name, token=token):
                    self.assertIsNone(pattern.search(source),
                                      f'{name} names the scenario ID {token!r}')

    def test_no_module_names_a_shipped_experiment_definition_id(self):
        for definition_id in self.registry.definitions:
            pattern = re.compile(rf'(?<![\w-]){re.escape(definition_id)}(?![\w-])')
            for name, source in self.sources.items():
                with self.subTest(module=name, definition=definition_id):
                    self.assertIsNone(pattern.search(source))

    def test_no_module_branches_on_a_launch_template_name(self):
        for method in self.registry.methods.values():
            leaf = Path(method['launch_template']).name
            for name, source in self.sources.items():
                with self.subTest(module=name, template=leaf):
                    self.assertNotIn(leaf, source)


if __name__ == '__main__':
    unittest.main()
