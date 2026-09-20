"""Deterministic counterbalanced scheduling (CONTRACTS.md §7).

One block is one (scenario, repeat). Over every complete set of ``len(methods)``
consecutive blocks each method occupies each position exactly once. The base
permutation and the block order are seed-randomised; nothing here reads the clock
and nothing names a specific method or scenario.
"""
import hashlib
import random

ALGORITHM = 'counterbalanced-rotation/1'
MAX_METHODS = 5


def run_id(seed, scenario_id, repeat, method_id):
    """Deterministic run ID from (seed, scenario, repeat, method)."""
    key = f'{seed}|{scenario_id}|{repeat}|{method_id}'
    return 'run-' + hashlib.sha256(key.encode()).hexdigest()[:6]


def build(method_ids, scenario_ids, repeats, seed):
    method_ids = list(method_ids)
    scenario_ids = list(scenario_ids)
    if not method_ids:
        raise ValueError('At least one method is required')
    if len(set(method_ids)) != len(method_ids):
        raise ValueError('Duplicate method IDs in the schedule request')
    if len(method_ids) > MAX_METHODS:
        raise ValueError(f'At most {MAX_METHODS} methods are supported per schedule')
    if not scenario_ids:
        raise ValueError('At least one scenario is required')
    if len(set(scenario_ids)) != len(scenario_ids):
        raise ValueError('Duplicate scenario IDs in the schedule request')
    if not isinstance(repeats, int) or repeats < 1:
        raise ValueError('Repeats must be a positive integer')
    if not isinstance(seed, int):
        raise ValueError('Seed must be an integer')

    width = len(method_ids)
    rng = random.Random(seed)
    base = list(method_ids)
    rng.shuffle(base)

    units = [(scenario, repeat) for repeat in range(1, repeats + 1) for scenario in scenario_ids]
    rng.shuffle(units)

    blocks = []
    for index, (scenario, repeat) in enumerate(units):
        offset = index % width
        order = base[offset:] + base[:offset]
        blocks.append({'block': index + 1, 'scenario': scenario, 'repeat': repeat, 'order': list(order)})

    balance = {method: {str(position): 0 for position in range(1, width + 1)} for method in method_ids}
    for block in blocks:
        for position, method in enumerate(block['order'], start=1):
            balance[method][str(position)] += 1

    complete = len(blocks) % width == 0
    imbalance = []
    if not complete:
        expected = len(blocks) / width
        for method in method_ids:
            for position in range(1, width + 1):
                deviation = balance[method][str(position)] - expected
                if deviation:
                    imbalance.append({'method': method, 'position': position,
                                      'count': balance[method][str(position)],
                                      'expected': expected, 'deviation': deviation})

    return {'algorithm': ALGORITHM, 'seed': seed, 'methods': list(method_ids),
            'scenarios': list(scenario_ids), 'repeats': repeats,
            'blocks': blocks, 'balance': balance, 'complete': complete, 'imbalance': imbalance,
            'note': ('Positions are balanced over complete blocks.' if complete else
                     'Incomplete final block set: position counts are uneven; see "imbalance". '
                     'Do not read position effects as method effects.')}


def runs(schedule, environment_id):
    """Flatten a schedule into ordered run stubs with deterministic IDs and pair keys."""
    order = 0
    result = []
    for block in schedule['blocks']:
        for position, method in enumerate(block['order'], start=1):
            order += 1
            result.append({'id': run_id(schedule['seed'], block['scenario'], block['repeat'], method),
                           'scenario': block['scenario'], 'method': method,
                           'repeat': block['repeat'], 'block': block['block'],
                           'position': position, 'order': order, 'environment': environment_id})
    return result


def pair_key(scenario_id, scenario_version, environment_id, repeat):
    return f'{scenario_id}@{scenario_version}|{environment_id}|r{repeat}'
