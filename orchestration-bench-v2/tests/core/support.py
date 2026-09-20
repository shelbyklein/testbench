"""Helpers for the core lane tests: temp copies of the registry root and data-only fixtures."""
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATA_DIRS = ('methods', 'scenario_packs', 'experiments', 'scenarios', 'seed', 'evaluator')

GRADER = '''import fs from 'node:fs';
import path from 'node:path';

const [candidate, out] = process.argv.slice(2);
const answer = path.join(candidate, 'answer.txt');
const text = fs.existsSync(answer) ? fs.readFileSync(answer, 'utf8') : '';
const scrub = (value) => String(value).split(path.resolve(candidate)).join('<submission>');
const checks = [
  { id: 'X1', description: 'An answer file exists', status: text.trim() ? 'pass' : 'fail',
    evidence: scrub(answer) },
  { id: 'X2', description: 'The answer mentions the widget', status: /widget/.test(text) ? 'pass' : 'fail',
    evidence: scrub(text.slice(0, 120)) },
];
const passed = checks.filter((c) => c.status === 'pass').length;
const report = { checks, passed, total: checks.length, allPassed: passed === checks.length };
fs.writeFileSync(out, JSON.stringify(report, null, 2));
process.exit(report.allPassed ? 0 : 1);
'''


def copy_registry_root(destination):
    """A writable copy of the real registry root. Data only: no bench_core code is copied."""
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    for name in DATA_DIRS:
        source = ROOT / name
        if source.is_dir():
            shutil.copytree(source, destination / name,
                            ignore=shutil.ignore_patterns('.git', 'node_modules', '__pycache__'))
    return destination


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + '\n')


def add_fixture_scenario(root, scenario_id='FX1', calibrated=True):
    """Add an extra scenario purely by writing files. No bench code is touched."""
    root = Path(root)
    pack = root / 'scenario_packs' / scenario_id
    (pack / 'participant').mkdir(parents=True, exist_ok=True)
    (pack / 'participant' / 'TASK.md').write_text(
        f'# {scenario_id}\n\nWrite answer.txt describing the widget.\n')
    (pack / 'participant' / 'README.md').write_text('Fixture participant source.\n')
    private = pack / 'private'
    private.mkdir(parents=True, exist_ok=True)
    (private / 'grade.mjs').write_text(GRADER)
    calibration = {'reference': None, 'known_bad': []}
    if calibrated:
        (private / 'reference').mkdir(parents=True, exist_ok=True)
        (private / 'reference' / 'answer.txt').write_text('The widget is described here.\n')
        bad = private / 'known_bad' / 'no-widget'
        bad.mkdir(parents=True, exist_ok=True)
        (bad / 'answer.txt').write_text('Nothing relevant.\n')
        calibration = {
            'reference': f'scenario_packs/{scenario_id}/private/reference',
            'known_bad': [{'id': 'no-widget',
                           'path': f'scenario_packs/{scenario_id}/private/known_bad/no-widget',
                           'must_fail': ['X2']}]}
    write_json(pack / 'scenario.json', {
        'contract': 'scenario/1', 'id': scenario_id, 'version': '1.0.0', 'slug': 'fixture',
        'title': 'Fixture scenario added as data', 'kind': 'Fixture',
        'minutes': 10, 'repair': 5,
        'participant': {'source': f'scenario_packs/{scenario_id}/participant',
                        'brief': f'scenario_packs/{scenario_id}/participant/TASK.md'},
        'public_checks': [],
        'grader': {'argv': ['node', f'scenario_packs/{scenario_id}/private/grade.mjs'],
                   'version': '1.0.0', 'expected_check_ids': ['X1', 'X2'], 'timeout_seconds': 60},
        'private': [f'scenario_packs/{scenario_id}/private'],
        'calibration': calibration,
        'manual_checks': []})
    return pack


def add_method(root, method_id, configured=False, **overrides):
    """Add an extra method purely by writing files."""
    root = Path(root)
    template = f'methods/templates/{method_id}.md'
    (root / template).parent.mkdir(parents=True, exist_ok=True)
    (root / template).write_text(
        'Run ${run_id} on ${scenario_id} repeat ${repeat} in ${workspace}\n\n'
        '```json\n${method_json}\n```\n\nAllowance ${minutes} minutes, repair ${repair} minutes.\n')
    budget = {'limit': None, 'enforcement': 'unenforced'}
    unavailable = {'limit': None, 'enforcement': 'unavailable'}
    data = {
        'contract': 'method/1', 'id': method_id, 'version': '1.0.0',
        'label': f'Fixture method {method_id}', 'mode': 'fixture-mode',
        'configured': configured,
        'roles': [{'role': 'worker',
                   'model': {'requested': 'Fixture Model' if configured else 'RECORD WORKER MODEL',
                             'effective': None, 'verified': False},
                   'reasoning': {'requested': 'medium', 'effective': None, 'verified': False}}],
        'transport': 'fixture transport', 'launch_template': template,
        'internal_review': {'enabled': False, 'reviewer_role': None}, 'adapter': None,
        'budgets': {'max_workers': dict(budget), 'max_attempts': dict(budget),
                    'max_minutes': dict(budget), 'max_tokens': dict(unavailable),
                    'max_cost_usd': dict(unavailable)},
        'notes': 'Added by a test as data only.'}
    data.update(overrides)
    write_json(root / 'methods' / f'{method_id}.json', data)
    return data


def add_definition(root, definition_id, methods, scenarios, repeats=1, seed=1234, **overrides):
    data = {'contract': 'experiment-definition/1', 'id': definition_id,
            'title': f'Fixture {definition_id}', 'question': 'Fixture question?',
            'establishes': 'Fixture comparison only.',
            'methods': list(methods), 'scenarios': list(scenarios),
            'repeats': repeats, 'seed': seed, 'phases': ['first'],
            'environment': {'id': 'fixture-env', 'notes': 'Fixture environment.'},
            'controls': {'same_external_grading': True, 'repair_feedback': 'identical',
                         'fixed_worker': None, 'internal_reviewer': None}}
    data.update(overrides)
    write_json(Path(root) / 'experiments' / 'definitions' / f'{definition_id}.json', data)
    return data
