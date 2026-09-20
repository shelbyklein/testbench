"""Prepared experiments (CONTRACTS.md §4, §7).

``prepare`` materialises one isolated workspace per run from the scenario pack's
participant source; it never copies a private path or a ``scenario.json``. Launch text
comes from the method's template through ``string.Template`` — there are no per-mode
branches in this module, and no method ID, mode or scenario ID appears in the source.
"""
import copy
import datetime as dt
import json
import shutil
import string
import subprocess
import tempfile
from pathlib import Path

from . import common, registry as registry_module, schedule as schedule_module
from .registry import Registry

FORMAT = 'ob2-experiment/1'
VERSION = 2
V1_VERSION = 1
PARTICIPANT_RULES = (
    '# Benchmark participant rules\n\n'
    'Read TASK.md and LAUNCH.md. Work only in this assigned repository; do not inspect evaluator '
    'internals or sibling runs. Follow the run method recorded by the operator. Stop after reporting '
    'completion so the operator can capture the first submission. Do not deploy, publish, or use real '
    'user data.\n'
)
BASELINE_MESSAGE = 'Starting fixture'
NEVER_COPY = {registry_module.SCENARIO_FILE}


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


# ---------------------------------------------------------------- readiness

def readiness(definition, registry):
    """Compute readiness. Never stored as true; always recomputed from current data."""
    blockers = []
    methods = list(definition.get('methods') or [])
    scenarios = list(definition.get('scenarios') or [])
    if not methods:
        blockers.append('Definition lists no methods.')
    if not scenarios:
        blockers.append('Definition lists no scenarios.')
    for label, values in (('method', methods), ('scenario', scenarios)):
        duplicates = sorted({v for v in values if values.count(v) > 1})
        for value in duplicates:
            blockers.append(f'Duplicate {label} ID in the definition: {value}.')
    for method_id in methods:
        method = registry.methods.get(method_id)
        if method is None:
            blockers.append(f'Method {method_id!r} is not in the registry.')
            continue
        if method.get('contract') != registry_module.METHOD_CONTRACT:
            blockers.append(f'Method {method_id!r} has incompatible contract {method.get("contract")!r}.')
        if not method.get('configured'):
            blockers.append(f'Method {method_id!r} is not configured: {_unresolved(method)}')
        blockers.extend(registry_module.configuration_errors(method))
        template = method.get('launch_template')
        if not template or not (registry.root / template).exists():
            blockers.append(f'Method {method_id!r} launch template is missing: {template}.')
        adapter = method.get('adapter')
        if adapter and not (registry.root / adapter).exists():
            blockers.append(f'Method {method_id!r} declares adapter {adapter!r}, which is not present.')
    for scenario_id in scenarios:
        scenario = registry.scenarios.get(scenario_id)
        if scenario is None:
            blockers.append(f'Scenario {scenario_id!r} is not in the registry.')
            continue
        if scenario.get('contract') != registry_module.SCENARIO_CONTRACT:
            blockers.append(f'Scenario {scenario_id!r} has incompatible contract {scenario.get("contract")!r}.')
        blockers.extend(registry_module._scenario_errors(registry.root, scenario))
    return {'ready': not blockers, 'blockers': blockers,
            'computedAt': now(),
            'note': 'Readiness is computed from the current registry; it is never stored as true.'}


def _unresolved(method):
    """Human-readable list of what still has to be filled in for this method."""
    pending = []
    for role in method.get('roles') or []:
        if not isinstance(role, dict):
            continue
        for field in ('model', 'reasoning'):
            value = role.get(field)
            requested = value.get('requested') if isinstance(value, dict) else None
            if requested is None or (isinstance(requested, str)
                                     and requested.startswith(registry_module.PLACEHOLDER.strip())):
                pending.append(f'{role.get("role")}.{field}')
    body = json.dumps({k: v for k, v in method.items() if k != '_path'})
    if registry_module.PLACEHOLDER in body and not pending:
        pending.append('unresolved RECORD placeholder')
    return ', '.join(pending) if pending else 'operator must record the exact setup'


# ---------------------------------------------------------------- load / write

def load(path):
    """Return ``(data, writable)``. v1 experiments load read-only; unknown formats are rejected."""
    path = Path(path)
    if path.is_dir():
        path = path / 'experiment.json'
    data = common.read(path)
    version = data.get('version')
    fmt = data.get('format')
    if version == V1_VERSION and fmt is None:
        return data, False
    if version == VERSION and fmt == FORMAT:
        return data, True
    raise ValueError(f'Incompatible experiment format/version: format={fmt!r} version={version!r}. '
                     f'Expected {FORMAT!r}/{VERSION} or a v1 experiment (version 1).')


def require_writable(data, writable=None):
    if writable is None:
        writable = data.get('format') == FORMAT and data.get('version') == VERSION
    if not writable:
        raise ValueError('This experiment is read-only (v1 or unknown format). '
                         'v2 never writes into a v1 experiment directory.')
    return data


def save(exp_dir, data):
    common.write(Path(exp_dir) / 'experiment.json', data)


def log(exp_dir, event, **fields):
    with (Path(exp_dir) / 'events.jsonl').open('a') as handle:
        handle.write(json.dumps({'time': now(), 'event': event, **fields}) + '\n')


# ---------------------------------------------------------------- preparation

def _private_parts(root, scenario):
    return [Path(p).parts for p in (scenario.get('private') or [])]


def _copy_participant(root, scenario, destination):
    """Copy the participant source, refusing symlinks and never copying private material."""
    source = Path(root) / scenario['participant']['source']
    private = _private_parts(root, scenario)
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    for item in sorted(source.rglob('*')):
        relative = item.relative_to(source)
        parts = relative.parts
        if any(part in common.EXCLUDED for part in parts):
            continue
        if relative.name in NEVER_COPY:
            continue
        absolute_parts = Path(scenario['participant']['source']).parts + parts
        if any(absolute_parts[:len(p)] == p for p in private):
            continue
        common.require(not item.is_symlink(),
                       f'Source symlink cannot be captured reproducibly: {item}')
        target = destination / relative
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif item.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(item, target)


def _git(argv, cwd):
    result = subprocess.run(['git'] + argv, cwd=str(cwd), text=True, capture_output=True, timeout=60)
    return result


def _baseline_commit(workspace):
    for argv in (['init', '-q'], ['add', '.'],
                 ['-c', 'user.name=Benchmark Fixture', '-c', 'user.email=fixture@localhost',
                  'commit', '-qm', BASELINE_MESSAGE]):
        result = _git(argv, workspace)
        common.require(result.returncode == 0, f'git {argv[0]} failed: {result.stderr}')
    head = _git(['rev-parse', 'HEAD'], workspace)
    common.require(head.returncode == 0, f'git rev-parse failed: {head.stderr}')
    return head.stdout.strip()


def policy_hashes(root, methods, scenarios):
    """Hash every file this experiment's comparison depends on."""
    root = Path(root)
    files = set()
    for method in methods:
        for key in ('_path', 'launch_template'):
            value = method.get(key)
            if value:
                files.add(Path(value) if Path(value).is_absolute() else root / value)
    for scenario in scenarios:
        files.add(Path(scenario['_path']))
        files.add(root / scenario['participant']['brief'])
        for token in scenario['grader']['argv'][1:]:
            candidate = root / token
            if candidate.is_file():
                files.add(candidate)
        for private in scenario.get('private') or []:
            folder = root / private
            files.update(p for p in folder.rglob('*')
                         if p.is_file() and not any(x in common.EXCLUDED for x in p.relative_to(folder).parts))
        source = root / scenario['participant']['source']
        files.update(p for p in source.rglob('*')
                     if p.is_file() and not any(x in common.EXCLUDED for x in p.relative_to(source).parts))
    return {str(Path(p).resolve().relative_to(root.resolve())): common.digest(p)
            for p in sorted(files) if Path(p).is_file()}


def launch_text(method, context):
    """Render the method's launch template. No per-mode branch lives in this module."""
    template = string.Template(Path(context['template_path']).read_text())
    return template.substitute(
        run_id=context['run_id'], scenario_id=context['scenario_id'], repeat=context['repeat'],
        workspace=context['workspace'], method_json=json.dumps(
            {k: v for k, v in method.items() if k != '_path'}, indent=2),
        minutes=context['minutes'], repair=context['repair'])


def workspace_for(exp_dir, run):
    return Path(exp_dir) / 'workspaces' / run['id']


def write_launch(root, exp_dir, data, run):
    method = run.get('methodFrozen') or _frozen(data['methods'], run['method'])
    scenario = _frozen(data['scenarios'], run['scenario'])
    workspace = workspace_for(exp_dir, run)
    text = launch_text(method, {
        'template_path': Path(root) / method['launch_template'],
        'run_id': run['id'], 'scenario_id': run['scenario'], 'repeat': run['repeat'],
        'workspace': str(workspace), 'minutes': scenario['minutes'], 'repair': scenario['repair']})
    (workspace / 'LAUNCH.md').write_text(text)
    return text


def _frozen(entries, entry_id):
    for entry in entries:
        if entry['id'] == entry_id:
            return entry
    raise ValueError(f'Unknown ID in frozen experiment data: {entry_id}')


def frozen_registry(root, data):
    """A Registry view over an experiment's frozen method/scenario definitions."""
    return Registry(root,
                    {m['id']: m for m in data['methods']},
                    {s['id']: s for s in data['scenarios']},
                    {data['definition']['id']: data['definition']})


def prepare(root, definition_id, exp_dir, registry=None):
    """Create an ``ob2-experiment/1`` experiment. Allowed for unready definitions."""
    root = Path(root)
    exp_dir = Path(exp_dir)
    common.require(not exp_dir.exists(), f'Experiment already exists: {exp_dir}')
    registry = registry or registry_module.load(root)
    definition = registry.definition(definition_id)
    methods = [copy.deepcopy(registry.method(m)) for m in definition['methods']]
    scenarios = [copy.deepcopy(registry.scenario(s)) for s in definition['scenarios']]
    state = readiness(definition, registry)

    plan = schedule_module.build(definition['methods'], definition['scenarios'],
                                 definition['repeats'], definition['seed'])
    environment_id = definition['environment']['id']
    stubs = schedule_module.runs(plan, environment_id)

    exp_dir.mkdir(parents=True)
    data = {'format': FORMAT, 'version': VERSION, 'createdAt': now(), 'synthetic': False,
            'definition': {k: v for k, v in definition.items() if k != '_path'},
            'root': str(root), 'methods': methods, 'scenarios': scenarios,
            'policyHashes': policy_hashes(root, methods, scenarios),
            'schedule': plan, 'readinessAtPrepare': state, 'runs': [], 'pairs': [], 'reviews': []}

    for stub in stubs:
        scenario = _frozen(scenarios, stub['scenario'])
        run = dict(stub)
        run.update({'scenarioVersion': scenario['version'],
                    'methodVersion': _frozen(methods, stub['method'])['version'],
                    'pairKey': schedule_module.pair_key(scenario['id'], scenario['version'],
                                                        environment_id, stub['repeat']),
                    'status': 'prepared', 'phases': {}, 'metrics': {},
                    'baselineCommit': None, 'initialHashes': {}})
        workspace = workspace_for(exp_dir, run)
        _copy_participant(root, scenario, workspace)
        shutil.copyfile(root / scenario['participant']['brief'], workspace / 'TASK.md')
        (workspace / 'AGENTS.md').write_text(PARTICIPANT_RULES)
        run['baselineCommit'] = _baseline_commit(workspace)
        run['initialHashes'] = common.inventory(workspace)
        data['runs'].append(run)

    data['pairs'] = sorted({run['pairKey'] for run in data['runs']})
    save(exp_dir, data)
    for run in data['runs']:
        write_launch(root, exp_dir, data, run)
    log(exp_dir, 'prepared', definition=definition_id, runs=len(data['runs']),
        ready=state['ready'], blockers=state['blockers'])
    return data


# ---------------------------------------------------------------- start

def start(exp_dir, run_id):
    """Refuse to start an unconfigured or unready run; freeze the method otherwise."""
    exp_dir = Path(exp_dir)
    data, writable = load(exp_dir)
    require_writable(data, writable)
    run = _frozen(data['runs'], run_id)
    common.require(not run.get('startedAt'), 'Run already started')
    root = Path(data['root'])
    registry = frozen_registry(root, data)
    state = readiness(data['definition'], registry)
    common.require(state['ready'],
                   'This experiment is not ready to start. Resolve every blocker first:\n  - '
                   + '\n  - '.join(state['blockers']))
    method = registry.method(run['method'])
    common.require(method.get('configured'),
                   f'Method {run["method"]!r} is not configured; record the exact setup first.')
    actual = common.inventory(workspace_for(exp_dir, run))
    actual.pop('LAUNCH.md', None)
    expected = dict(run['initialHashes'])
    expected.pop('LAUNCH.md', None)
    common.require(actual == expected,
                   'Workspace differs from its starting fixture. Prepare a fresh experiment '
                   'instead of starting after edits.')
    run['methodFrozen'] = copy.deepcopy(method)
    run['startedAt'] = now()
    run['status'] = 'running'
    write_launch(root, exp_dir, data, run)
    save(exp_dir, data)
    log(exp_dir, 'started', run=run_id, method=run['method'])
    return run


# ---------------------------------------------------------------- evaluation

def evaluate_with_grader(scenario, candidate_dir, out_json, root=None):
    """Run the generic grader CLI contract and validate the expected check IDs."""
    root = Path(root or common.ROOT)
    out_json = Path(out_json)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='ob2-grade-') as temp:
        raw = Path(temp) / 'checks.json'
        report, process = registry_module.run_grader(scenario, candidate_dir, raw, root)
    report.update({'scenario': scenario['id'], 'scenarioVersion': scenario['version'],
                   'graderVersion': scenario['grader']['version'], 'runner': process,
                   'evaluatedAt': now(), 'status': 'complete'})
    report['allPassed'] = bool(report.get('allPassed')) and process['exitCode'] == 0
    common.write(out_json, report)
    return report
