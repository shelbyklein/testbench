"""A synthetic demo experiment for exercising the operator dashboard and the review page.

Nothing here is a measurement of anything: every method label, model name and number is
invented, the experiment carries ``"synthetic": true``, and every imported trace comes from
the observation lane's synthetic fixtures. The UI must display all of it as synthetic.

The captured-work layout (``snapshots/``, ``receipts/``, ``results/``) is written directly on
disk, reusing :mod:`tests.review.support` (imported, never edited). What this module adds on
top of that fixture is what the UI lane needs and the review lane did not:

* a self-contained bench ``root`` on disk, so ``readiness`` and ``policyHashes`` compute for
  real instead of being stubbed (one method is deliberately left unconfigured, so the
  dashboard has genuine blockers to list);
* real imported traces (solo, handoff and an "active" trace with a failed node, a node that
  was declared and never observed, a skipped node, a retry, a fault and an intervention);
* operator metrics with real unknowns, and blind reviews in three states: absent, current and
  stale.

Distinctive identity strings ("Zebra-Method-Q7", "ModelXYZ-9", ``run-zz0001``) come from the
review fixture on purpose: the browser checks assert that none of them reaches the review page.
"""
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bench_core import common, experiment as experiment_module, review_projection, traces  # noqa: E402
from tests.review import support  # noqa: E402

FIXTURES = ROOT / 'tests' / 'observation' / 'fixtures'
ENVIRONMENT = 'local-default'
DEFINITION_ID = 'zebra-pilot'
#: method id -> observation fixture imported for that method's run
TRACE_FIXTURES = {'zebraflow': 'active.jsonl', 'yakflow': 'handoff.jsonl',
                  'xerusflow': 'unknown_usage.jsonl'}
#: the fourth method is prepared but never configured and never run
PENDING_METHOD = {'id': 'wombatflow', 'label': 'Wombat-Method-T9', 'mode': 'wombatmode',
                  'model': 'RECORD exact model identifier', 'reasoning': 'RECORD reasoning effort'}
PENDING_RUN_ID = 'run-zz0004'

LAUNCH_TEMPLATE = """# Launch — ${run_id}

Scenario ${scenario_id}, repeat ${repeat}. Allowance ${minutes} minutes, repair ${repair} minutes.
Work only in ${workspace}. Stop and report when the task is done.

Recorded method:

```json
${method_json}
```
"""

BRIEF = """# Fixture task

Fix the note filter so archived notes stay hidden, and keep the smoke test passing.
"""

GRADER = """// Demo grader placeholder. The demo experiment is evaluated on disk, never by running this.
process.exit(0);
"""

SEED_FILES = {
    'package.json': '{\n  "name": "demo-seed",\n  "type": "module"\n}\n',
    'src/app.mjs': "export const notes = [];\n",
    'tests/smoke.test.mjs': "import test from 'node:test';\ntest('ok', () => {});\n",
}


# ---------------------------------------------------------------- bench root

def build_root(root):
    """A minimal but real bench root: templates, brief, grader and participant seed."""
    root = Path(root)
    (root / 'methods' / 'templates').mkdir(parents=True, exist_ok=True)
    (root / 'methods' / 'templates' / 'zebraflow.md').write_text(LAUNCH_TEMPLATE)
    (root / 'scenarios').mkdir(parents=True, exist_ok=True)
    (root / 'scenarios' / f'{support.SCENARIO_ID}.md').write_text(BRIEF)
    (root / support.PRIVATE_DIR).mkdir(parents=True, exist_ok=True)
    (root / support.PRIVATE_DIR / 'grade.mjs').write_text(GRADER)
    for relative, text in SEED_FILES.items():
        target = root / 'seed' / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    pack = root / 'scenario_packs' / support.SCENARIO_ID / 'scenario.json'
    pack.parent.mkdir(parents=True, exist_ok=True)
    scenario = support.scenario()
    common.write(pack, scenario)
    scenario['_path'] = str(pack)
    return scenario


def _methods(root):
    """The three configured fixture methods plus one still-unconfigured method."""
    methods = []
    for entry in support.METHODS:
        method = support._method(entry)
        method.pop('_path', None)
        method['budgets'] = {
            'max_workers': {'limit': 3, 'enforcement': 'unenforced'},
            'max_attempts': {'limit': None, 'enforcement': 'unenforced'},
            'max_minutes': {'limit': 30, 'enforcement': 'advisory'},
            'max_tokens': {'limit': None, 'enforcement': 'unavailable'},
            'max_cost_usd': {'limit': None, 'enforcement': 'unavailable'},
        }
        methods.append(method)
    pending = support._method(PENDING_METHOD)
    pending.pop('_path', None)
    pending['configured'] = False
    pending['budgets'] = dict(methods[0]['budgets'])
    pending['notes'] = 'Roles and runtime are not recorded yet; this method cannot start.'
    methods.append(pending)
    return methods


def _run(run_id, method, position, scenario, status='evaluated'):
    return {
        'id': run_id, 'scenario': scenario['id'], 'scenarioVersion': scenario['version'],
        'method': method['id'], 'methodVersion': method['version'], 'repeat': 1,
        'environment': ENVIRONMENT, 'block': 1, 'position': position, 'order': position,
        'pairKey': f'{scenario["id"]}@{scenario["version"]}|{ENVIRONMENT}|r1',
        'status': status, 'phases': {}, 'metrics': {},
        'baselineCommit': 'a86b0947f1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6', 'initialHashes': {},
        'methodFrozen': method,
    }


# ---------------------------------------------------------------- experiment

def build(base_dir):
    """Create ``<base>/root`` and ``<base>/experiment``; return a description dict."""
    base = Path(base_dir)
    root = base / 'root'
    exp = base / 'experiment'
    scenario = build_root(root)
    methods = _methods(root)
    exp.mkdir(parents=True, exist_ok=True)

    # Deliberate schedule order: position 1 is not the first method in the list.
    order = [2, 0, 1]
    runs = []
    for position, index in enumerate(order, start=1):
        runs.append(_run(support.RUN_IDS[index], methods[index], position, scenario))
    runs.append(_run(PENDING_RUN_ID, methods[3], 4, scenario, status='prepared'))

    data = {
        'format': experiment_module.FORMAT, 'version': experiment_module.VERSION,
        'createdAt': '2026-09-20T11:00:00+00:00', 'synthetic': True,
        'definition': {
            'contract': 'experiment-definition/1', 'id': DEFINITION_ID,
            'title': 'Demo pilot (synthetic)',
            'question': 'Does the extra coordination change what the user can accept?',
            'establishes': 'Nothing yet: this experiment is a synthetic demonstration of the bench.',
            'methods': [m['id'] for m in methods], 'scenarios': [scenario['id']],
            'repeats': 1, 'seed': 20260920, 'phases': ['first', 'repaired'],
            'environment': {'id': ENVIRONMENT, 'notes': 'Demo machine, offline.'},
            'controls': {'same_external_grading': True, 'repair_feedback': 'identical',
                         'fixed_worker': None, 'internal_reviewer': None},
        },
        'root': str(root), 'methods': methods, 'scenarios': [scenario],
        'policyHashes': experiment_module.policy_hashes(root, methods, [scenario]),
        'schedule': {
            'algorithm': 'counterbalanced-rotation/1', 'seed': 20260920,
            'blocks': [{'block': 1, 'scenario': scenario['id'], 'repeat': 1,
                        'order': [methods[i]['id'] for i in order] + [methods[3]['id']]}],
            'balance': {m['id']: {'1': 0, '2': 0, '3': 0, '4': 0} for m in methods},
            'complete': False,
            'imbalance': [f'{m["id"]}: one block only; positions are not counterbalanced yet'
                          for m in methods],
        },
        'runs': runs, 'pairs': [runs[0]['pairKey']], 'reviews': [],
    }
    for position, index in enumerate(order, start=1):
        data['schedule']['balance'][methods[index]['id']][str(position)] = 1
    data['schedule']['balance'][methods[3]['id']]['4'] = 1
    common.write(exp / 'experiment.json', data)

    # -- captured work, from the review lane's fixture builder -------------
    for index in range(3):
        entry = support.METHODS[index]
        run_id = support.RUN_IDS[index]
        support.write_snapshot(exp, run_id, 'first', entry)
        support.write_receipt(exp, run_id, 'first')
        support.write_evaluation(exp, run_id, 'first', entry, passed=1 + (index % 2))
        if index == 0:
            support.write_snapshot(exp, run_id, 'repaired', entry, marker='v2-repaired')
            support.write_receipt(exp, run_id, 'repaired')
            support.write_evaluation(exp, run_id, 'repaired', entry, passed=2)

    # Mirror the captures into the run records, as capture/evaluate would have.
    for run in data['runs']:
        for phase in ('first', 'repaired'):
            receipt_path = exp / 'receipts' / run['id'] / f'{phase}.json'
            if not receipt_path.is_file():
                continue
            receipt = common.read(receipt_path)
            evaluation = common.read(exp / 'results' / run['id'] / phase / 'evaluation.json')
            run['phases'][phase] = {
                'capturedAt': receipt['capturedAt'], 'elapsedMinutes': receipt['elapsedMinutes'],
                'allowanceMinutes': receipt['allowanceMinutes'], 'overBudget': receipt['overBudget'],
                'taskIntact': receipt['taskIntact'], 'submissionHash': common.inventory_hash(receipt['hashes']),
                'evaluation': evaluation,
            }
        run['startedAt'] = '2026-09-20T11:05:00+00:00' if run['phases'] else None

    # -- workspaces and launch text ---------------------------------------
    for run in data['runs']:
        workspace = experiment_module.workspace_for(exp, run)
        workspace.mkdir(parents=True, exist_ok=True)
        (workspace / 'TASK.md').write_text(BRIEF)
        experiment_module.write_launch(root, exp, data, run)

    # -- operator metrics, with real unknowns ------------------------------
    data['runs'][_index_of(data, support.RUN_IDS[0])]['metrics']['first'] = {
        'costUSD': None, 'humanMinutes': 12.5, 'interventions': 2,
        'inputTokens': None, 'outputTokens': None,
        'source': 'stopwatch; provider export has no per-session cost',
        'notes': 'Cost is unavailable for this export. Two interventions unblocked a stuck worker.'}
    data['runs'][_index_of(data, support.RUN_IDS[1])]['metrics']['first'] = {
        'costUSD': 0.42, 'humanMinutes': 4, 'interventions': 0,
        'inputTokens': 41000, 'outputTokens': 5200,
        'source': 'provider usage export', 'notes': ''}
    common.write(exp / 'experiment.json', data)

    # -- traces ------------------------------------------------------------
    store = traces.TraceStore(exp / 'traces' / 'events.jsonl')
    imported = {}
    for index, entry in enumerate(support.METHODS):
        fixture = TRACE_FIXTURES.get(entry['id'])
        if not fixture:
            continue
        result = traces.import_file(FIXTURES / fixture, support.RUN_IDS[index],
                                    DEFINITION_ID, store=store)
        imported[support.RUN_IDS[index]] = {'fixture': fixture, 'added': result['added']}

    # One deliberately *estimated* measurement, so the UI has a measured/estimated pair to
    # distinguish. It is an operator estimate, not a provider number, and says so in its source.
    store.add([{
        'schema': traces.SCHEMA, 'eventId': 'u-usage-operator-estimate',
        'experimentId': DEFINITION_ID, 'runId': support.RUN_IDS[2], 'nodeId': 'solo-1',
        'attempt': 1, 'role': 'solo', 'type': 'usage', 'status': 'ok',
        'timestamp': '2026-09-20T12:09:30+00:00',
        'clock': {'source': 'synthetic', 'uncertaintySeconds': None},
        'usage': {'inputTokens': None, 'outputTokens': None, 'durationSeconds': None,
                  'costUSD': common.measurement(0.08, 'usd', 'estimated',
                                                'operator estimate from token counts'),
                  'scope': 'self'},
        'evidence': {'ref': 'tests/ui/demo.py', 'sha256': None,
                     'importer': 'synthetic', 'importerVersion': '1.0.0'},
        'synthetic': True,
    }])

    # -- blind reviews: current, stale, and absent --------------------------
    labels = {p['label']: p for p in review_projection.build(exp, 'first')}
    by_run = {review_projection.resolve_label(exp, label)['run']: label for label in labels}
    repaired_labels = {review_projection.resolve_label(exp, p['label'])['run']: p['label']
                       for p in review_projection.build(exp, 'repaired')}

    current_label = by_run[support.RUN_IDS[1]]
    review_projection.accept_review(exp, current_label, 'first',
                                    labels[current_label]['submissionHash'],
                                    labels[current_label]['evaluatorVersion'],
                                    support.good_review())

    stale_label = by_run[support.RUN_IDS[2]]
    review_projection.accept_review(exp, stale_label, 'first',
                                    labels[stale_label]['submissionHash'],
                                    labels[stale_label]['evaluatorVersion'],
                                    support.good_review())
    # Move the submission under the saved review: the dashboard must now show it as stale.
    staled = exp / 'snapshots' / support.RUN_IDS[2] / 'first' / 'README.md'
    staled.write_text(staled.read_text() + '\nAmended after the review was saved.\n')

    # The browser checks need a label whose snapshot they can move between load and submit.
    stale_target = by_run[support.RUN_IDS[0]]
    description = {
        'experiment': str(exp),
        'root': str(root),
        'synthetic': True,
        'imported': imported,
        'reviewedLabel': current_label,
        'staleLabel': stale_label,
        'staleTarget': {'label': stale_target, 'phase': 'first',
                        'file': str(exp / 'snapshots' / support.RUN_IDS[0] / 'first' / 'README.md')},
        'submitTarget': {'label': repaired_labels[support.RUN_IDS[0]], 'phase': 'repaired'},
        'identityStrings': sorted(
            {m['label'] for m in support.METHODS} | {m['mode'] for m in support.METHODS}
            | {m['model'] for m in support.METHODS} | set(support.RUN_IDS)
            | {PENDING_METHOD['label']}),
    }
    common.write(base / 'demo.json', description)
    return description


def _index_of(data, run_id):
    for index, run in enumerate(data['runs']):
        if run['id'] == run_id:
            return index
    raise KeyError(run_id)


def main(argv=None):
    """``python3 -m tests.ui.demo <dir>`` — build a demo experiment for manual inspection."""
    argv = list(sys.argv[1:] if argv is None else argv)
    base = Path(argv[0]).expanduser().resolve() if argv else ROOT / '.runtime' / 'ui-demo'
    if base.exists():
        shutil.rmtree(base)
    base.mkdir(parents=True)
    description = build(base)
    print(json.dumps(description, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
