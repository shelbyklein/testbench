"""The shipped controlled-comparison definitions: honest, unstarted and fully disclosed."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402

from bench_core import experiment, registry  # noqa: E402

SHIPPED = ('practical-setups', 'fixed-worker', 'internal-review-ablation')
PLACEHOLDER = 'RECORD '


class Shipped(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = registry.load(support.ROOT)

    def test_the_three_definitions_ship(self):
        for definition_id in SHIPPED:
            self.assertIn(definition_id, self.registry.definitions)

    def test_every_definition_is_not_ready_and_says_exactly_why(self):
        for definition_id in SHIPPED:
            with self.subTest(definition=definition_id):
                state = experiment.readiness(self.registry.definition(definition_id), self.registry)
                self.assertFalse(state['ready'])
                self.assertTrue(state['blockers'])
                for blocker in state['blockers']:
                    self.assertTrue(blocker.strip().endswith(('.', ':')) or blocker.strip(),
                                    'blockers must be readable sentences')
                unconfigured = {method for method in self.registry.definition(definition_id)['methods']
                                if not self.registry.method(method).get('configured')}
                for method in unconfigured:
                    self.assertTrue(any(repr(method) in blocker for blocker in state['blockers']),
                                    f'{method} must be named in the blockers of {definition_id}')

    def test_astra_low_solo_is_preserved_exactly(self):
        v1 = {entry['id']: entry for entry in json.loads(
            (support.ROOT / 'methods' / 'defaults.json').read_text())}
        method = self.registry.method('solo')
        original = v1['solo']
        self.assertEqual(method['mode'], original['mode'])
        self.assertTrue(method['configured'])
        self.assertEqual(len(method['roles']), 1)
        role = method['roles'][0]
        self.assertEqual(role['model']['requested'], original['roles'][0]['model'])
        self.assertEqual(role['reasoning']['requested'], original['roles'][0]['reasoning'])
        self.assertIsNone(role['model']['effective'])
        self.assertFalse(role['model']['verified'])
        self.assertIn('solo', self.registry.definition('practical-setups')['methods'])

    def test_unresolved_v1_roles_stay_placeholders_and_unconfigured(self):
        for method_id in ('handoff', 'active'):
            method = self.registry.method(method_id)
            self.assertFalse(method['configured'])
            self.assertIn(PLACEHOLDER, json.dumps(method))

    def test_no_method_claims_a_verified_effective_setting(self):
        for method in self.registry.methods.values():
            for role in method['roles']:
                for field in ('model', 'reasoning'):
                    self.assertIsNone(role[field]['effective'])
                    self.assertFalse(role[field]['verified'])

    def test_budget_enforcement_labels_are_honest(self):
        for method in self.registry.methods.values():
            budgets = method['budgets']
            self.assertEqual(budgets['max_tokens']['enforcement'], 'unavailable')
            self.assertEqual(budgets['max_cost_usd']['enforcement'], 'unavailable')
            if method['adapter'] is None:
                for key in ('max_workers', 'max_attempts', 'max_minutes'):
                    self.assertEqual(budgets[key]['enforcement'], 'unenforced',
                                     f'{method["id"]}.{key} claims enforcement the bench cannot provide')

    def test_fixed_worker_arms_share_one_worker_placeholder(self):
        definition = self.registry.definition('fixed-worker')
        self.assertTrue(definition['controls']['fixed_worker'])
        shared = set()
        for method_id in definition['methods']:
            roles = {role['role']: role for role in self.registry.method(method_id)['roles']}
            self.assertIn('shared worker', roles, f'{method_id} has no shared worker role')
            shared.add((roles['shared worker']['model']['requested'],
                        roles['shared worker']['reasoning']['requested']))
        self.assertEqual(len(shared), 1,
                         'the shared worker must be one placeholder filled in once for every arm')

    def test_fixed_worker_covers_the_four_coordination_shapes(self):
        modes = {self.registry.method(m)['mode']
                 for m in self.registry.definition('fixed-worker')['methods']}
        self.assertEqual(len(modes), 4)

    def test_ablation_pairs_each_shape_with_and_without_the_same_reviewer(self):
        definition = self.registry.definition('internal-review-ablation')
        methods = [self.registry.method(m) for m in definition['methods']]
        by_mode = {}
        for method in methods:
            by_mode.setdefault(method['mode'], []).append(method)
        self.assertEqual(len(by_mode), 2)
        reviewers = set()
        for mode, arms in by_mode.items():
            enabled = sorted(bool(arm['internal_review']['enabled']) for arm in arms)
            self.assertEqual(enabled, [False, True], f'{mode} is not ablated')
            for arm in arms:
                if arm['internal_review']['enabled']:
                    role = next(r for r in arm['roles']
                                if r['role'] == arm['internal_review']['reviewer_role'])
                    reviewers.add(role['model']['requested'])
        self.assertEqual(len(reviewers), 1, 'both reviewed arms must use the identical reviewer')

    def test_practical_setups_covers_four_distinct_coordination_shapes(self):
        definition = self.registry.definition('practical-setups')
        modes = {self.registry.method(m)['mode'] for m in definition['methods']}
        self.assertEqual(len(modes), len(definition['methods']))
        self.assertTrue(definition['controls']['same_external_grading'])
        self.assertEqual(definition['controls']['repair_feedback'], 'identical')

    def test_every_definition_uses_the_same_scenarios_and_grading(self):
        scenarios = {definition_id: tuple(self.registry.definition(definition_id)['scenarios'])
                     for definition_id in SHIPPED}
        self.assertEqual(len(set(scenarios.values())), 1, scenarios)

    def test_start_is_blocked_for_every_shipped_definition(self):
        import tempfile
        for definition_id in SHIPPED:
            with self.subTest(definition=definition_id), \
                    tempfile.TemporaryDirectory(prefix='ob2-blocked-') as temp:
                definition = self.registry.definition(definition_id)
                stub = dict(definition, scenarios=definition['scenarios'][:1], repeats=1)
                exp = Path(temp) / 'exp'
                data = self._prepare_stub(stub, exp)
                with self.assertRaises(ValueError) as caught:
                    experiment.start(exp, data['runs'][0]['id'])
                self.assertIn('not ready', str(caught.exception))

    def _prepare_stub(self, stub, exp):
        """Prepare a one-scenario slice of a shipped definition into a temp directory."""
        temp_registry = registry.Registry(
            self.registry.root, self.registry.methods, self.registry.scenarios,
            dict(self.registry.definitions, **{stub['id']: stub}))
        return experiment.prepare(self.registry.root, stub['id'], exp, temp_registry)


if __name__ == '__main__':
    unittest.main()
