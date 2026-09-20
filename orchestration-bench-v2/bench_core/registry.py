"""Data-driven registries for methods, scenarios and experiment definitions.

Contracts: CONTRACTS.md §5 (scenario/1), §6 (method/1), §7 (experiment-definition/1).

Everything here is discovered by listing directories. No function in this module may
name a specific method ID, mode or scenario ID; adding a method or a scenario is a
data change (drop a JSON file in place), never a code change.
"""
import json
import subprocess
import tempfile
from pathlib import Path

from . import common

METHOD_CONTRACT = 'method/1'
SCENARIO_CONTRACT = 'scenario/1'
DEFINITION_CONTRACT = 'experiment-definition/1'

METHOD_DIR = 'methods'
SCENARIO_DIR = 'scenario_packs'
SCENARIO_FILE = 'scenario.json'
DEFINITION_DIR = 'experiments/definitions'

PLACEHOLDER = 'RECORD '
ENFORCEMENT = ('enforced', 'advisory', 'unenforced', 'unavailable')
BUDGET_KEYS = ('max_workers', 'max_attempts', 'max_minutes', 'max_tokens', 'max_cost_usd')


class Registry:
    """Loaded registry contents. Dicts keyed by declared ID."""

    def __init__(self, root, methods, scenarios, definitions, errors=()):
        self.root = Path(root)
        self.methods = methods
        self.scenarios = scenarios
        self.definitions = definitions
        self.errors = list(errors)

    def method(self, method_id):
        if method_id not in self.methods:
            raise ValueError(f'Unknown method ID: {method_id}')
        return self.methods[method_id]

    def scenario(self, scenario_id):
        if scenario_id not in self.scenarios:
            raise ValueError(f'Unknown scenario ID: {scenario_id}')
        return self.scenarios[scenario_id]

    def definition(self, definition_id):
        if definition_id not in self.definitions:
            raise ValueError(f'Unknown experiment definition ID: {definition_id}')
        return self.definitions[definition_id]


# ---------------------------------------------------------------- discovery

def _candidate_files(root):
    """Every JSON file the registry may consider, by directory listing only."""
    method_dir = Path(root) / METHOD_DIR
    definition_dir = Path(root) / DEFINITION_DIR
    scenario_dir = Path(root) / SCENARIO_DIR
    methods = sorted(p for p in method_dir.glob('*.json')) if method_dir.is_dir() else []
    definitions = sorted(p for p in definition_dir.glob('*.json')) if definition_dir.is_dir() else []
    scenarios = []
    if scenario_dir.is_dir():
        scenarios = sorted(p / SCENARIO_FILE for p in scenario_dir.iterdir()
                           if p.is_dir() and (p / SCENARIO_FILE).is_file())
    return methods, scenarios, definitions


def _read_entries(paths, expected_contract, errors):
    """Parse candidate files. Non-object JSON is a legacy carry-over and is ignored;
    an object with the wrong contract string is an error."""
    entries = {}
    for path in paths:
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError) as error:
            errors.append(f'{path}: unreadable JSON ({error})')
            continue
        if not isinstance(data, dict):
            continue  # v1 carry-over list files are not registry entries
        contract = data.get('contract')
        if contract != expected_contract:
            errors.append(f'{path}: incompatible contract {contract!r}; expected {expected_contract!r}')
            continue
        entry_id = data.get('id')
        if not isinstance(entry_id, str) or not entry_id.strip():
            errors.append(f'{path}: missing "id"')
            continue
        if entry_id in entries:
            errors.append(f'{path}: duplicate ID {entry_id!r} (also declared by {entries[entry_id]["_path"]})')
            continue
        data['_path'] = str(path)
        entries[entry_id] = data
    return entries


def load(root, strict=True):
    """Load every method, scenario and experiment definition under ``root``."""
    root = Path(root)
    errors = []
    method_paths, scenario_paths, definition_paths = _candidate_files(root)
    methods = _read_entries(method_paths, METHOD_CONTRACT, errors)
    scenarios = _read_entries(scenario_paths, SCENARIO_CONTRACT, errors)
    definitions = _read_entries(definition_paths, DEFINITION_CONTRACT, errors)
    registry = Registry(root, methods, scenarios, definitions, errors)
    errors.extend(_semantic_errors(registry))
    registry.errors = errors
    if strict and errors:
        raise ValueError('Registry is invalid:\n  ' + '\n  '.join(errors))
    return registry


def validate(root):
    """Return the list of registry errors (empty list means valid)."""
    return load(root, strict=False).errors


# ---------------------------------------------------------------- validation

def _exists(root, relative):
    return (Path(root) / relative).exists()


def _method_errors(root, method):
    errors = []
    where = method['_path']
    for key in ('label', 'mode', 'transport', 'launch_template'):
        if not isinstance(method.get(key), str) or not method[key].strip():
            errors.append(f'{where}: missing {key!r}')
    if not isinstance(method.get('version'), str) or not method['version'].strip():
        errors.append(f'{where}: missing "version"')
    if not isinstance(method.get('configured'), bool):
        errors.append(f'{where}: "configured" must be a boolean')
    roles = method.get('roles')
    if not isinstance(roles, list) or not roles:
        errors.append(f'{where}: at least one role is required')
        roles = []
    for role in roles:
        if not isinstance(role, dict) or not isinstance(role.get('role'), str) or not role['role'].strip():
            errors.append(f'{where}: every role needs a "role" name')
            continue
        for field in ('model', 'reasoning'):
            value = role.get(field)
            if not isinstance(value, dict) or set(value) < {'requested', 'effective', 'verified'}:
                errors.append(f'{where}: role {role["role"]!r} {field} needs requested/effective/verified')
                continue
            if value['effective'] is not None and not value['verified']:
                errors.append(f'{where}: role {role["role"]!r} {field} effective set without verification')
    review = method.get('internal_review')
    if not isinstance(review, dict) or not isinstance(review.get('enabled'), bool):
        errors.append(f'{where}: "internal_review" needs an "enabled" boolean')
    budgets = method.get('budgets')
    if not isinstance(budgets, dict):
        errors.append(f'{where}: "budgets" object is required')
    else:
        for key in BUDGET_KEYS:
            budget = budgets.get(key)
            if not isinstance(budget, dict) or 'limit' not in budget:
                errors.append(f'{where}: budget {key!r} needs a limit')
                continue
            if budget.get('enforcement') not in ENFORCEMENT:
                errors.append(f'{where}: budget {key!r} enforcement must be one of {ENFORCEMENT}')
    template = method.get('launch_template')
    if isinstance(template, str) and template.strip() and not _exists(root, template):
        errors.append(f'{where}: launch template not found: {template}')
    adapter = method.get('adapter')
    if adapter is not None and not isinstance(adapter, str):
        errors.append(f'{where}: "adapter" must be null or a module path string')
    errors.extend(configuration_errors(method))
    return errors


def configuration_errors(method):
    """Reasons a method claiming ``configured: true`` may not claim it."""
    if not method.get('configured'):
        return []
    where = method.get('_path', method.get('id'))
    errors = []
    body = json.dumps({k: v for k, v in method.items() if k != '_path'})
    if PLACEHOLDER in body:
        errors.append(f'{where}: configured method still contains {PLACEHOLDER.strip()!r} placeholders')
    for role in method.get('roles') or []:
        if not isinstance(role, dict):
            continue
        requested = (role.get('model') or {}).get('requested') if isinstance(role.get('model'), dict) else None
        if not isinstance(requested, str) or not requested.strip():
            errors.append(f'{where}: configured method role {role.get("role")!r} has no requested model')
    return errors


def _scenario_errors(root, scenario):
    errors = []
    where = scenario['_path']
    for key in ('version', 'slug', 'title', 'kind'):
        if not isinstance(scenario.get(key), str) or not scenario[key].strip():
            errors.append(f'{where}: missing {key!r}')
    for key in ('minutes', 'repair'):
        if not isinstance(scenario.get(key), int) or scenario[key] <= 0:
            errors.append(f'{where}: {key!r} must be a positive integer')
    participant = scenario.get('participant')
    if not isinstance(participant, dict):
        errors.append(f'{where}: "participant" object is required')
        participant = {}
    source = participant.get('source')
    brief = participant.get('brief')
    if not isinstance(source, str) or not (Path(root) / source).is_dir():
        errors.append(f'{where}: participant source directory not found: {source}')
    if not isinstance(brief, str) or not _exists(root, brief):
        errors.append(f'{where}: participant brief not found: {brief}')
    private = scenario.get('private')
    if not isinstance(private, list):
        errors.append(f'{where}: "private" must be a list of paths')
        private = []
    for path in private:
        if not isinstance(path, str) or not _exists(root, path):
            errors.append(f'{where}: private path not found: {path}')
    if isinstance(source, str):
        for path in private:
            if isinstance(path, str) and _overlaps(source, path):
                errors.append(f'{where}: participant source {source!r} overlaps private path {path!r}')
    grader = scenario.get('grader')
    if not isinstance(grader, dict):
        errors.append(f'{where}: "grader" object is required')
    else:
        argv = grader.get('argv')
        if not isinstance(argv, list) or not argv or not all(isinstance(a, str) for a in argv):
            errors.append(f'{where}: grader argv must be a non-empty list of strings')
            argv = []
        for token in argv[1:]:
            if '/' in token and not _exists(root, token):
                errors.append(f'{where}: grader file not found: {token}')
        ids = grader.get('expected_check_ids')
        if not isinstance(ids, list) or not ids or len(set(ids)) != len(ids):
            errors.append(f'{where}: grader expected_check_ids must be a list of unique IDs')
        if not isinstance(grader.get('version'), str) or not grader['version'].strip():
            errors.append(f'{where}: grader version is required')
        timeout = grader.get('timeout_seconds')
        if not isinstance(timeout, int) or timeout <= 0:
            errors.append(f'{where}: grader timeout_seconds must be a positive integer')
    for check in scenario.get('public_checks') or []:
        if not isinstance(check, list) or not check or not all(isinstance(a, str) for a in check):
            errors.append(f'{where}: every public check must be an argv list of strings')
    return errors


def _overlaps(first, second):
    a = Path(first).parts
    b = Path(second).parts
    shortest = min(len(a), len(b))
    return a[:shortest] == b[:shortest]


def _definition_errors(registry, definition):
    errors = []
    where = definition['_path']
    for key in ('title', 'question', 'establishes'):
        if not isinstance(definition.get(key), str) or not definition[key].strip():
            errors.append(f'{where}: missing {key!r}')
    for key, table in (('methods', registry.methods), ('scenarios', registry.scenarios)):
        values = definition.get(key)
        if not isinstance(values, list) or not values:
            errors.append(f'{where}: {key!r} must be a non-empty list')
            continue
        if len(set(values)) != len(values):
            errors.append(f'{where}: duplicate entries in {key!r}')
        for value in values:
            if value not in table:
                errors.append(f'{where}: {key[:-1]} {value!r} is not in the registry')
    if not isinstance(definition.get('repeats'), int) or definition['repeats'] < 1:
        errors.append(f'{where}: "repeats" must be a positive integer')
    if not isinstance(definition.get('seed'), int):
        errors.append(f'{where}: "seed" must be an integer')
    phases = definition.get('phases')
    if not isinstance(phases, list) or not phases or not all(isinstance(p, str) for p in phases):
        errors.append(f'{where}: "phases" must be a non-empty list of strings')
    environment = definition.get('environment')
    if not isinstance(environment, dict) or not isinstance(environment.get('id'), str):
        errors.append(f'{where}: "environment" needs an id')
    if not isinstance(definition.get('controls'), dict):
        errors.append(f'{where}: "controls" object is required')
    if 'ready' in definition:
        errors.append(f'{where}: readiness is computed, never stored')
    return errors


def _semantic_errors(registry):
    errors = []
    for method in registry.methods.values():
        errors.extend(_method_errors(registry.root, method))
    for scenario in registry.scenarios.values():
        errors.extend(_scenario_errors(registry.root, scenario))
    for definition in registry.definitions.values():
        errors.extend(_definition_errors(registry, definition))
    return errors


# ---------------------------------------------------------------- calibration

def run_grader(scenario, candidate_dir, out_json, root=None):
    """Run the scenario's grader CLI: ``<argv…> <candidate_dir> <output.json>``.

    Returns ``(report, process)``. Raises ValueError when the grader errors or when
    the reported check IDs do not match ``expected_check_ids``.
    """
    root = Path(root or common.ROOT)
    grader = scenario['grader']
    argv = [str((root / token)) if '/' in token else token for token in grader['argv']]
    argv = argv + [str(candidate_dir), str(out_json)]
    try:
        process = subprocess.run(argv, cwd=str(root), text=True, capture_output=True,
                                 timeout=grader.get('timeout_seconds', 180))
    except (subprocess.TimeoutExpired, OSError) as error:
        raise ValueError(f'Grader could not be run: {error}') from error
    if process.returncode not in (0, 1):
        raise ValueError(f'Grader error (exit {process.returncode}): {process.stderr[-2000:]}')
    out_json = Path(out_json)
    if not out_json.exists():
        raise ValueError('Grader produced no output file')
    report = common.read(out_json)
    expected = set(grader['expected_check_ids'])
    actual = {check.get('id') for check in report.get('checks', [])}
    if actual != expected:
        raise ValueError(f'Grader check IDs do not match the scenario contract. '
                         f'Missing: {sorted(expected - actual)}; unexpected: {sorted(actual - expected)}')
    statuses = [check.get('status') for check in report['checks']]
    if len(statuses) != len(expected):
        raise ValueError('Grader reported a check ID more than once')
    if any(status not in ('pass', 'fail') for status in statuses):
        raise ValueError(f'Grader reported a check status other than pass/fail: {sorted(set(map(str, statuses)))}')
    claimed = (report.get('passed'), report.get('total'), report.get('allPassed'))
    report['passed'] = sum(status == 'pass' for status in statuses)   # recomputed; the grader's own
    report['total'] = len(statuses)                                  # arithmetic is never trusted
    report['allPassed'] = report['passed'] == report['total'] and process.returncode == 0
    if claimed != (report['passed'], report['total'], report['passed'] == report['total']):
        report['arithmeticMismatch'] = {'claimed': list(claimed), 'note': 'Grader totals disagreed with its checks; recomputed.'}
    return report, {'exitCode': process.returncode, 'stdout': process.stdout[-20000:],
                    'stderr': process.stderr[-10000:]}


def calibrate(scenario, root=None):
    """Run the scenario's calibration fixtures: the reference must pass everything and
    each known-bad fixture must fail at least its declared check IDs."""
    root = Path(root or common.ROOT)
    calibration = scenario.get('calibration') or {}
    report = {'scenario': scenario['id'], 'scenarioVersion': scenario.get('version'),
              'status': 'unavailable', 'reference': None, 'known_bad': [], 'problems': []}
    reference = calibration.get('reference')
    known_bad = calibration.get('known_bad') or []
    if not reference and not known_bad:
        report['problems'].append('No calibration fixtures are declared for this scenario.')
        return report
    report['status'] = 'ok'
    with tempfile.TemporaryDirectory(prefix='ob2-calibrate-') as temp:
        if reference:
            out = Path(temp) / 'reference.json'
            result, _ = run_grader(scenario, root / reference, out, root)
            failed = sorted(c['id'] for c in result['checks'] if c.get('status') != 'pass')
            report['reference'] = {'path': reference, 'allPassed': bool(result.get('allPassed')),
                                   'failed': failed}
            if failed:
                report['status'] = 'failed'
                report['problems'].append(f'Reference fixture failed checks: {failed}')
        for index, fixture in enumerate(known_bad):
            out = Path(temp) / f'known-bad-{index}.json'
            result, _ = run_grader(scenario, root / fixture['path'], out, root)
            failed = {c['id'] for c in result['checks'] if c.get('status') != 'pass'}
            must_fail = set(fixture.get('must_fail') or [])
            missing = sorted(must_fail - failed)
            entry = {'id': fixture.get('id'), 'path': fixture['path'],
                     'failed': sorted(failed), 'mustFail': sorted(must_fail),
                     'detected': not missing,
                     'reasons': [c.get('evidence') for c in result['checks']
                                 if c.get('id') in must_fail and c.get('status') != 'pass']}
            report['known_bad'].append(entry)
            if missing:
                report['status'] = 'failed'
                report['problems'].append(
                    f'Known-bad fixture {fixture.get("id")!r} was not caught by checks {missing}')
    return report
