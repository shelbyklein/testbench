"""Scheduling behaviour: determinism, counterbalancing and honest imbalance disclosure."""
import sys
import unittest
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402,F401

from bench_core import schedule  # noqa: E402

SCENARIOS = ['s-alpha', 's-beta', 's-gamma', 's-delta']


def methods(count):
    return [f'm{index}' for index in range(1, count + 1)]


class Determinism(unittest.TestCase):
    def test_same_seed_produces_an_identical_schedule(self):
        first = schedule.build(methods(3), SCENARIOS[:3], 2, 4242)
        second = schedule.build(methods(3), SCENARIOS[:3], 2, 4242)
        self.assertEqual(first, second)

    def test_a_different_seed_produces_a_different_schedule(self):
        first = schedule.build(methods(4), SCENARIOS, 2, 1)
        second = schedule.build(methods(4), SCENARIOS, 2, 2)
        self.assertNotEqual([b['order'] for b in first['blocks']],
                            [b['order'] for b in second['blocks']])

    def test_run_ids_are_deterministic_and_unique(self):
        plan = schedule.build(methods(3), SCENARIOS[:3], 2, 99)
        runs = schedule.runs(plan, 'env')
        again = schedule.runs(schedule.build(methods(3), SCENARIOS[:3], 2, 99), 'env')
        self.assertEqual([r['id'] for r in runs], [r['id'] for r in again])
        self.assertEqual(len({r['id'] for r in runs}), len(runs))
        for run in runs:
            self.assertEqual(run['id'],
                             schedule.run_id(99, run['scenario'], run['repeat'], run['method']))

    def test_no_wall_clock_or_system_entropy_is_used(self):
        source = (support.ROOT / 'bench_core' / 'schedule.py').read_text()
        for forbidden in ('SystemRandom', 'time.time', 'datetime', 'secrets', 'uuid', 'os.urandom'):
            self.assertNotIn(forbidden, source)


class Counterbalancing(unittest.TestCase):
    def test_one_through_five_methods_are_supported(self):
        for count in range(1, 6):
            plan = schedule.build(methods(count), SCENARIOS[:2], count, 7)
            self.assertEqual(len(plan['blocks']), 2 * count)
            for block in plan['blocks']:
                self.assertEqual(sorted(block['order']), sorted(methods(count)))

    def test_six_methods_is_refused(self):
        with self.assertRaises(ValueError):
            schedule.build(methods(6), SCENARIOS, 1, 7)

    def test_every_method_hits_every_position_equally_over_complete_blocks(self):
        for count in range(1, 6):
            for seed in (3, 20260920):
                plan = schedule.build(methods(count), SCENARIOS[:2], count, seed)
                self.assertTrue(plan['complete'])
                self.assertEqual(plan['imbalance'], [])
                expected = len(plan['blocks']) // count
                for method, positions in plan['balance'].items():
                    self.assertEqual(set(positions.values()), {expected},
                                     f'{method} is not position-balanced at {count} methods')

    def test_each_complete_window_of_consecutive_blocks_is_a_latin_square(self):
        count = 4
        plan = schedule.build(methods(count), SCENARIOS, 2, 31)
        orders = [block['order'] for block in plan['blocks']]
        for start in range(0, len(orders) - count + 1, count):
            window = orders[start:start + count]
            for position in range(count):
                column = [order[position] for order in window]
                self.assertEqual(sorted(column), sorted(methods(count)))

    def test_incomplete_blocks_disclose_imbalance(self):
        plan = schedule.build(methods(4), SCENARIOS[:3], 1, 5)
        self.assertFalse(plan['complete'])
        self.assertTrue(plan['imbalance'])
        self.assertIn('imbalance', plan['note'])
        deviations = Counter()
        for entry in plan['imbalance']:
            deviations[entry['method']] += entry['deviation']
            self.assertIn('expected', entry)
        self.assertTrue(all(abs(value) < 1e-9 for value in deviations.values()),
                        'per-method deviations must sum to zero across positions')

    def test_single_method_schedule_is_trivially_complete(self):
        plan = schedule.build(methods(1), SCENARIOS, 3, 11)
        self.assertTrue(plan['complete'])
        self.assertEqual(plan['balance']['m1'], {'1': 12})


class Pairing(unittest.TestCase):
    def test_pair_key_groups_the_same_scenario_environment_and_repeat(self):
        key = schedule.pair_key('s-alpha', '1.0.0', 'env', 2)
        self.assertEqual(key, 's-alpha@1.0.0|env|r2')
        self.assertNotEqual(key, schedule.pair_key('s-alpha', '1.0.1', 'env', 2))
        self.assertNotEqual(key, schedule.pair_key('s-alpha', '1.0.0', 'other', 2))
        self.assertNotEqual(key, schedule.pair_key('s-alpha', '1.0.0', 'env', 1))


class Rejection(unittest.TestCase):
    def test_invalid_inputs_are_refused(self):
        cases = [
            ([], SCENARIOS, 1, 1),
            (methods(2), [], 1, 1),
            (['m1', 'm1'], SCENARIOS, 1, 1),
            (methods(2), ['s-alpha', 's-alpha'], 1, 1),
            (methods(2), SCENARIOS, 0, 1),
            (methods(2), SCENARIOS, 1, 'seed'),
        ]
        for case in cases:
            with self.subTest(case=case), self.assertRaises(ValueError):
                schedule.build(*case)


if __name__ == '__main__':
    unittest.main()
