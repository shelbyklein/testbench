"""Fixture experiment for the review lane.

The controller is not used: the tests build the captured-work layout on disk directly
(``snapshots/<run>/<phase>/``, ``receipts/<run>/<phase>.json``,
``results/<run>/<phase>/evaluation.json``) exactly as §7/§10 describe it, so a projection is
exercised against real files rather than against a controller run.

Every operator string in the fixture is deliberately distinctive ("Zebra-Method-Q7",
"ModelXYZ-9", "zebramode", run IDs) so that any leak into a payload or a package is detectable
by substring rather than by judgement.
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bench_core import common  # noqa: E402

SCENARIO_ID = 'SZ'
SCENARIO_VERSION = '1.4.0'
EVALUATOR_VERSION = '2.3.1'
PRIVATE_DIR = 'hiddengrader'
PHASES = ('first', 'repaired')

METHODS = [
    {'id': 'zebraflow', 'label': 'Zebra-Method-Q7', 'mode': 'zebramode',
     'model': 'ModelXYZ-9', 'reasoning': 'quasar-high'},
    {'id': 'yakflow', 'label': 'Yak-Method-R3', 'mode': 'yakmode',
     'model': 'ModelPQR-4', 'reasoning': 'quasar-low'},
    {'id': 'xerusflow', 'label': 'Xerus-Method-S5', 'mode': 'xerusmode',
     'model': 'ModelTUV-2', 'reasoning': 'quasar-mid'},
]
RUN_IDS = ['run-zz0001', 'run-zz0002', 'run-zz0003']

APP_SOURCE = """export function filterNotes(notes, query) {
  const needle = String(query || '').trim().toLowerCase();
  if (!needle) return notes;
  return notes.filter((note) => note.title.toLowerCase().includes(needle));
}
"""
# A deliberate residual cue: submitted source that names its own method mode. Blinding cannot
# remove this, so the scanner must report it as a cue and not as a metadata leak.
CUE_SOURCE = """// Written during the {mode} session; see the team notes.
export const VERSION = '1.0.0';
"""


def _method(entry):
    return {
        'contract': 'method/1', 'id': entry['id'], 'version': '1.0.0', 'label': entry['label'],
        'mode': entry['mode'], 'configured': True,
        'roles': [{'role': 'implementer',
                   'model': {'requested': entry['model'], 'effective': None, 'verified': False},
                   'reasoning': {'requested': entry['reasoning'], 'effective': None,
                                 'verified': False}}],
        'transport': 'single fresh agent session',
        'launch_template': 'methods/templates/zebraflow.md',
        'internal_review': {'enabled': False, 'reviewer_role': None},
        'adapter': None, 'budgets': {}, 'notes': 'fixture method',
    }


def scenario(version=SCENARIO_VERSION, evaluator_version=EVALUATOR_VERSION):
    return {
        'contract': 'scenario/1', 'id': SCENARIO_ID, 'version': version, 'slug': 'zebra-filtering',
        'title': 'Fixture scenario', 'kind': 'Contained bug', 'minutes': 30, 'repair': 15,
        'participant': {'source': 'seed', 'brief': 'scenarios/SZ.md'},
        'public_checks': [['node', '--test', 'tests/smoke.test.mjs']],
        'grader': {'argv': ['node', f'{PRIVATE_DIR}/grade.mjs'], 'version': evaluator_version,
                   'expected_check_ids': ['Z1', 'Z2'], 'timeout_seconds': 180},
        'private': [PRIVATE_DIR],
        'calibration': {'reference': None, 'known_bad': []},
        'manual_checks': [{'id': 'zm-keyboard', 'description': 'Keyboard focus order is sane.'},
                          {'id': 'zm-mobile', 'description': 'Layout holds at 390px.'}],
    }


def _write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def write_snapshot(exp_dir, run_id, phase, method, marker='v1'):
    """One immutable submission copy, with identity files, hidden grading assets and a symlink."""
    snapshot = Path(exp_dir) / 'snapshots' / run_id / phase
    _write(snapshot / 'src/app.mjs', APP_SOURCE + f"// build {marker}\n")
    _write(snapshot / 'src/cue.mjs', CUE_SOURCE.format(mode=method['mode']))
    _write(snapshot / 'README.md', '# Fieldnotes submission\n\nRun `node server.mjs`.\n')
    _write(snapshot / 'tests/smoke.test.mjs', "import test from 'node:test';\ntest('ok', () => {});\n")
    # Identity files: operator- or participant-authored, never shown to a reviewer.
    _write(snapshot / 'LAUNCH.md', f"Method {method['label']} · mode {method['mode']} · "
                                   f"model {method['model']} · run {run_id}\n")
    _write(snapshot / 'APPROACH.md', f"Planned as {method['label']}.\n")
    _write(snapshot / 'SUBMISSION.md', f"Completed by {method['label']} using {method['model']}.\n")
    _write(snapshot / 'HANDOFF.md', f"Handoff from {method['label']}.\n")
    _write(snapshot / 'AGENTS.md', 'Benchmark participant rules.\n')
    # Hidden grading asset that must never be projected.
    _write(snapshot / PRIVATE_DIR / 'expected.json', json.dumps({'answer': 'do not show'}))
    link = snapshot / 'src/link.mjs'
    if not link.exists():
        os.symlink('app.mjs', link)
    return snapshot


def write_receipt(exp_dir, run_id, phase):
    snapshot = Path(exp_dir) / 'snapshots' / run_id / phase
    common.write(Path(exp_dir) / 'receipts' / run_id / f'{phase}.json',
                 {'capturedAt': '2026-09-20T12:00:00+00:00', 'elapsedMinutes': 21.5,
                  'allowanceMinutes': 30, 'overBudget': False,
                  'hashes': common.inventory(snapshot), 'taskIntact': True})


def write_evaluation(exp_dir, run_id, phase, method, passed=1):
    """An evaluation that carries exactly the material a projection must drop."""
    snapshot = Path(exp_dir) / 'snapshots' / run_id / phase
    common.write(Path(exp_dir) / 'results' / run_id / phase / 'evaluation.json', {
        'checks': [
            {'id': 'Z1', 'description': 'Filter narrows by title', 'status': 'pass',
             'evidence': f'{snapshot}/src/app.mjs:2 assertion held'},
            {'id': 'Z2', 'description': 'Archived notes stay filtered',
             'status': 'pass' if passed > 1 else 'fail',
             'evidence': f'AssertionError at {snapshot}/tests/smoke.test.mjs:9'},
        ],
        'passed': passed, 'total': 2, 'allPassed': passed == 2,
        'scenario': SCENARIO_ID, 'scenarioVersion': SCENARIO_VERSION,
        'graderVersion': EVALUATOR_VERSION, 'status': 'complete',
        'runner': {'exitCode': 1, 'stdout': f'grading {run_id} ({method["label"]})',
                   'stderr': f'{Path(exp_dir)}/{PRIVATE_DIR}/grade.mjs warned'},
        'details': {'expectedAnswerPath': f'{Path(exp_dir)}/{PRIVATE_DIR}/expected.json'},
    })


def build_experiment(exp_dir, scenario_version=SCENARIO_VERSION,
                     evaluator_version=EVALUATOR_VERSION, repaired_runs=(0,)):
    """Create a v2 experiment with three methods x one scenario, captured and evaluated."""
    exp_dir = Path(exp_dir)
    exp_dir.mkdir(parents=True, exist_ok=True)
    frozen = scenario(scenario_version, evaluator_version)
    runs = []
    # Deliberate operator/schedule order: position 1 is the third method.
    order = [2, 0, 1]
    for position, index in enumerate(order, start=1):
        entry = METHODS[index]
        runs.append({
            'id': RUN_IDS[index], 'scenario': SCENARIO_ID, 'scenarioVersion': scenario_version,
            'method': entry['id'], 'methodVersion': '1.0.0', 'repeat': 1,
            'environment': 'local-default', 'block': 1, 'position': position, 'order': position,
            'pairKey': f'{SCENARIO_ID}@{scenario_version}|local-default|r1',
            'status': 'evaluated', 'phases': {}, 'metrics': {},
            'baselineCommit': 'abc123', 'initialHashes': {},
            'methodFrozen': _method(entry),
        })
    data = {'format': 'ob2-experiment/1', 'version': 2, 'createdAt': '2026-09-20T11:00:00+00:00',
            'synthetic': True,
            'definition': {'contract': 'experiment-definition/1', 'id': 'zebra-pilot',
                           'methods': [m['id'] for m in METHODS], 'scenarios': [SCENARIO_ID],
                           'repeats': 1, 'seed': 20260920, 'phases': list(PHASES),
                           'environment': {'id': 'local-default', 'notes': ''}},
            'root': str(ROOT), 'methods': [_method(m) for m in METHODS], 'scenarios': [frozen],
            'policyHashes': {}, 'schedule': {'algorithm': 'counterbalanced-rotation/1'},
            'runs': runs, 'pairs': [], 'reviews': []}
    common.write(exp_dir / 'experiment.json', data)

    for index, entry in enumerate(METHODS):
        run_id = RUN_IDS[index]
        write_snapshot(exp_dir, run_id, 'first', entry)
        write_receipt(exp_dir, run_id, 'first')
        write_evaluation(exp_dir, run_id, 'first', entry, passed=1 + (index % 2))
        if index in repaired_runs:
            write_snapshot(exp_dir, run_id, 'repaired', entry, marker='v2-repaired')
            write_receipt(exp_dir, run_id, 'repaired')
            write_evaluation(exp_dir, run_id, 'repaired', entry, passed=2)
    return data


def build_v1_experiment(exp_dir):
    exp_dir = Path(exp_dir)
    exp_dir.mkdir(parents=True, exist_ok=True)
    common.write(exp_dir / 'experiment.json',
                 {'version': 1, 'createdAt': '2026-01-01T00:00:00+00:00', 'runs': [], 'pairs': []})
    return exp_dir


def good_review():
    return {'reviewer': 'anon-7', 'notes': 'Reviewed the running app.',
            'scores': {key: {'value': 2, 'evidence': 'Exercised the filter in the browser.'}
                       for key in ('correctness', 'completeness', 'maintainability', 'ux',
                                   'evidence_quality')},
            'manual': [{'id': 'zm-keyboard', 'status': 'pass', 'evidence': 'Tab order verified.'},
                       {'id': 'zm-mobile', 'status': 'not_run', 'evidence': ''}],
            'defects': [{'severity': 'minor', 'evidence': 'Empty state flickers once.'}]}
