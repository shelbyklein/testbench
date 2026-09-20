#!/usr/bin/env python3
"""Orchestration Bench v2 controller. Python standard library only.

Setup, preflight, tests and both servers never invoke a model. Methods are launched by the
operator (or an explicitly configured adapter); this controller prepares, records and compares.
"""
import argparse
import copy
import csv
import datetime as dt
import functools
import http.server
import json
import math
import shutil
import subprocess
import sys
import tempfile
import threading
import webbrowser
import secrets
from pathlib import Path

from bench_core import common, experiment, metrics as metrics_module, registry as registry_module, traces
from bench_core.common import read, require, write

ROOT = Path(__file__).resolve().parent
LOCK = threading.RLock()
DIMENSIONS = ['correctness', 'completeness', 'maintainability', 'ux', 'evidence_quality']
PHASES = ['first', 'repaired']
DEFAULT_PORT = 4388
REVIEW_PORT = 4389
IDENTITY_FILES = ('LAUNCH.md', 'APPROACH.md', 'SUBMISSION.md', 'HANDOFF.md', 'AGENTS.md')


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def command(argv, cwd, timeout=30):
    try:
        result = subprocess.run(argv, cwd=cwd, text=True, capture_output=True, timeout=timeout)
        return {'exitCode': result.returncode, 'stdout': result.stdout[-20000:], 'stderr': result.stderr[-10000:]}
    except (subprocess.TimeoutExpired, OSError) as error:
        return {'exitCode': None, 'stdout': '', 'stderr': str(error), 'error': True}


def copy_source(source, destination, extra=()):
    source = Path(source)
    for p in source.rglob('*'):
        if any(x in common.EXCLUDED or x in extra for x in p.relative_to(source).parts):
            continue
        require(not p.is_symlink(), f'Source symlink cannot be captured reproducibly: {p}')
    shutil.copytree(source, destination,
                    ignore=lambda folder, names: [n for n in names if n in common.EXCLUDED or n in extra])


# ------------------------------------------------------------------ experiment access

def load(exp):
    return experiment.load(exp)[0]


def load_writable(exp):
    data, writable = experiment.load(exp)
    experiment.require_writable(data, writable)
    return data


def is_v1(data):
    return data.get('version') == 1 and data.get('format') is None


def root_for(data):
    return Path(data.get('root') or ROOT)


def ensure_policy(data):
    current = experiment.policy_hashes(root_for(data), data['methods'], data['scenarios'])
    require(data['policyHashes'] == current,
            'Bench files changed since preparation. Keep this experiment version fixed or prepare a new '
            'experiment; do not silently compare different tests.')


def run_by_id(data, rid):
    for run in data['runs']:
        if run['id'] == rid:
            return run
    raise ValueError('Unknown run ID')


def entry(entries, entry_id):
    for item in entries:
        if item['id'] == entry_id:
            return item
    raise ValueError(f'Unknown ID: {entry_id}')


def method_for(data, run):
    return run.get('methodFrozen') or entry(data['methods'], run['method'])


def scenario_for(data, run):
    return entry(data['scenarios'], run['scenario'])


def folder_for(exp, run):
    return exp / 'workspaces' / run['id']


def trace_store(exp):
    return traces.TraceStore(exp / 'traces' / 'events.jsonl')


# ------------------------------------------------------------------ review and gate

def manual_checks(data, scenario_id):
    if is_v1(data):
        return read(ROOT / 'evaluator/manual.json').get(scenario_id, [])
    return entry(data['scenarios'], scenario_id).get('manual_checks') or []


def blank_review(data, scenario_id):
    return {'reviewer': '', 'scores': {key: {'value': None, 'evidence': ''} for key in DIMENSIONS},
            'manual': [dict(item, status='not_run', evidence='') for item in manual_checks(data, scenario_id)],
            'defects': [], 'notes': ''}


def validate_review(value, data, scenario_id):
    require(isinstance(value, dict), 'Review must be an object')
    require(isinstance(value.get('reviewer'), str) and value['reviewer'].strip(),
            'Reviewer name or anonymous reviewer ID is required')
    require(isinstance(value.get('scores'), dict) and set(value['scores']) == set(DIMENSIONS),
            'Include all five rubric dimensions')
    for score in value['scores'].values():
        require(isinstance(score, dict), 'Score must contain value and evidence')
        n = score.get('value')
        require(n is None or (type(n) is int and 0 <= n <= 3), 'Scores must be integers 0–3 or null')
        require(isinstance(score.get('evidence'), str), 'Score evidence must be text')
        if n is not None:
            require(score['evidence'].strip(), 'Scored dimensions need evidence')
    manual = value.get('manual')
    require(isinstance(manual, list), 'Manual checks must be a list')
    expected = {i['id'] for i in manual_checks(data, scenario_id)}
    require(len(manual) == len(expected) and {i.get('id') for i in manual} == expected,
            'Manual check IDs must exactly match this scenario')
    for item in manual:
        require(item.get('status') in ['pass', 'fail', 'not_run'], 'Invalid manual status')
        require(isinstance(item.get('evidence'), str), 'Manual evidence must be text')
        if item['status'] != 'not_run':
            require(item['evidence'].strip(), 'Executed manual checks need evidence')
    require(isinstance(value.get('defects'), list), 'Defects must be a list')
    for defect in value['defects']:
        require(defect.get('severity') in ['critical', 'major', 'minor'], 'Defect severity must be critical/major/minor')
        require(isinstance(defect.get('evidence'), str) and defect['evidence'].strip(),
                'Each defect needs reproduction/evidence')
    return value


def gate(evaluation, review):
    if not evaluation: return 'Not evaluated'
    if evaluation.get('status') == 'error': return 'Evaluation error'
    if not evaluation.get('allPassed'): return 'Automated checks failed'
    if not review: return 'Manual review pending'
    if any(d['severity'] in ['critical', 'major'] for d in review['defects']): return 'Serious defect remains'
    if any(i['status'] == 'fail' for i in review['manual']): return 'Manual checks failed'
    if any(i['status'] == 'not_run' for i in review['manual']): return 'Manual review pending'
    if any(s['value'] is None for s in review['scores'].values()): return 'Rubric incomplete'
    if any(s['value'] < 2 for s in review['scores'].values()): return 'Quality bar not met'
    return 'Meets acceptance'


# ------------------------------------------------------------------ lifecycle

def prepare(exp, definition_id):
    registry = registry_module.load(ROOT)
    data = experiment.prepare(ROOT, definition_id, exp, registry)
    state = data['readinessAtPrepare']
    print(f'Prepared {len(data["runs"])} isolated repositories at {exp}\nNo agent runs have started.')
    if not state['ready']:
        print('This experiment is NOT ready to start. Blockers:\n  - ' + '\n  - '.join(state['blockers']))
    if not data['schedule']['complete']:
        print('Schedule is position-imbalanced (incomplete blocks); see schedule.imbalance.')
    print(f'Open the bench: python3 bench.py --experiment "{exp}" serve')


def configure(exp, mid, value):
    data = load_writable(exp); ensure_policy(data)
    require(not any(r['method'] == mid and r.get('startedAt') for r in data['runs']),
            'This method already has started runs. Prepare a new experiment to change its definition.')
    old = entry(data['methods'], mid)
    require(isinstance(value, dict) and value.get('id') == mid and value.get('mode') == old['mode']
            and value.get('contract') == old['contract'], 'Keep method contract, ID and mode unchanged')
    require(isinstance(value.get('configured'), bool), 'configured must be true or false')
    value = dict(value, _path=old.get('_path'))
    errors = registry_module._method_errors(root_for(data), value) + registry_module.configuration_errors(value)
    require(not errors, 'Invalid method definition:\n  - ' + '\n  - '.join(errors))
    for role in value['roles']:
        for field in ('model', 'reasoning'):
            setting = role.get(field) or {}
            require(setting.get('verified') is not True or setting.get('effective') is not None,
                    'A verified setting needs an observed effective value')
    data['methods'][data['methods'].index(old)] = value
    experiment.save(exp, data)
    for run in data['runs']:
        if run['method'] == mid:
            experiment.write_launch(root_for(data), exp, data, run)
    experiment.log(exp, 'method_configured', method=mid, definition={k: v for k, v in value.items() if k != '_path'})


def start(exp, rid):
    ensure_policy(load_writable(exp))
    run = experiment.start(exp, rid)
    print(f'Started {rid}. Paste {folder_for(exp, run) / "LAUNCH.md"} into the configured fresh session.')


def repair(exp, rid):
    data = load_writable(exp); ensure_policy(data); run = run_by_id(data, rid)
    require('first' in run['phases'], 'Capture first submission before repair')
    require('evaluation' in run['phases']['first'], 'Evaluate first submission before repair')
    require(not run.get('repairStartedAt'), 'Repair already started')
    run['repairStartedAt'] = now(); run['status'] = 'repairing'
    experiment.save(exp, data); experiment.log(exp, 'repair_started', run=rid)
    print(f'Repair clock started for {rid}. First submission remains preserved.')


def capture(exp, rid, phase):
    data = load_writable(exp); ensure_policy(data); run = run_by_id(data, rid)
    start_time = run.get('startedAt' if phase == 'first' else 'repairStartedAt')
    require(start_time, f'Start the {phase} phase before capture')
    require(phase not in run['phases'], 'This phase is already captured and cannot be overwritten')
    workspace = folder_for(exp, run); destination = exp / 'snapshots' / rid / phase
    require(not destination.exists(), 'Snapshot directory already exists; inspect state before retrying')
    scenario = scenario_for(data, run); skip = common.excluded_for(scenario)
    end = now(); pre = common.inventory(workspace, skip)
    destination.parent.mkdir(parents=True, exist_ok=True); copy_source(workspace, destination, extra=skip)
    hashes = common.inventory(destination, skip)
    require(pre == common.inventory(workspace, skip) == hashes,
            'Workspace changed during capture. Stop all agent writes; inspect this incomplete capture before retrying.')
    elapsed = (dt.datetime.fromisoformat(end) - dt.datetime.fromisoformat(start_time)).total_seconds() / 60
    limit = scenario['minutes' if phase == 'first' else 'repair']
    brief = root_for(data) / scenario['participant']['brief']
    intact = (workspace / 'TASK.md').exists() and common.digest(workspace / 'TASK.md') == common.digest(brief)
    receipt = {'capturedAt': end, 'elapsedMinutes': round(elapsed, 3), 'allowanceMinutes': limit,
               'overBudget': elapsed > limit, 'hashes': hashes, 'submissionHash': common.inventory_hash(hashes),
               'taskIntact': intact,
               'gitHead': command(['git', 'rev-parse', 'HEAD'], workspace),
               'gitStatus': command(['git', 'status', '--short'], workspace),
               'gitDiff': command(['git', 'diff', 'HEAD', '--'], workspace)}
    write(exp / 'receipts' / rid / f'{phase}.json', receipt)
    run['phases'][phase] = {'capturedAt': end, 'elapsedMinutes': receipt['elapsedMinutes'], 'allowanceMinutes': limit,
                            'overBudget': elapsed > limit, 'taskIntact': intact,
                            'submissionHash': receipt['submissionHash']}
    run['status'] = 'captured'; experiment.save(exp, data)
    experiment.log(exp, 'captured', run=rid, phase=phase, elapsedMinutes=receipt['elapsedMinutes'], overBudget=elapsed > limit)
    print(f'Captured {rid}/{phase}: {len(hashes)} files; {elapsed:.1f}/{limit} minutes. Next: evaluate {rid} --phase {phase}')


def evaluate(exp, rid, phase):
    data = load_writable(exp); ensure_policy(data); run = run_by_id(data, rid)
    require(phase in run['phases'], 'Capture before evaluating')
    require('evaluation' not in run['phases'][phase],
            'Evaluation already exists. Preserve this result; use a new phase/run for changes.')
    snapshot = exp / 'snapshots' / rid / phase; receipt = read(exp / 'receipts' / rid / f'{phase}.json')
    scenario = scenario_for(data, run); root = root_for(data)
    require(common.inventory(snapshot, common.excluded_for(scenario)) == receipt['hashes'], 'Snapshot integrity check failed; evaluation refused')
    with tempfile.TemporaryDirectory(prefix='ob2-eval-') as temp:
        candidate = Path(temp) / 'submission'; copy_source(snapshot, candidate)
        try:
            report = experiment.evaluate_with_grader(scenario, candidate, Path(temp) / 'evaluation.json', root)
        except (ValueError, OSError) as error:
            report = {'checks': [], 'passed': 0, 'total': 0, 'allPassed': False, 'status': 'error',
                      'error': str(error).replace(str(candidate), '<submission>'), 'evaluatedAt': now(),
                      'graderVersion': scenario['grader']['version']}
        public = []
        for argv in scenario.get('public_checks') or []:
            fresh = Path(temp) / f'public-{len(public)}'; copy_source(snapshot, fresh)
            original = root / scenario['participant']['source']
            for part in [a for a in argv if '/' in a and (original / a).is_file()]:
                (fresh / part).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(original / part, fresh / part)  # baseline smoke comes from the frozen fixture
            public.append(dict(command(argv, fresh, 60), argv=argv))
    report['publicChecks'] = public
    report['snapshotVerified'] = True
    report['submissionHash'] = receipt.get('submissionHash')
    gating = bool(scenario.get('baseline_regression_gate'))  # v1 meaning for S1–S3; a migration may rewrite its smoke test
    report['publicChecksGate'] = gating
    report['allPassed'] = (bool(report.get('allPassed')) and receipt['taskIntact']
                           and (not gating or all(item['exitCode'] == 0 for item in public)))
    if not receipt['taskIntact']:
        report['integrityNote'] = 'Participant changed or removed TASK.md'
    write(exp / 'results' / rid / phase / 'evaluation.json', report)
    run['phases'][phase]['evaluation'] = report; experiment.save(exp, data)
    experiment.log(exp, 'evaluated', run=rid, phase=phase, status=report['status'], passed=report['passed'], total=report['total'])
    print(f'{rid}/{phase}: {report["passed"]}/{report["total"]} checks; {gate(report, None)}')


def save_review(exp, rid, phase, value):
    data = load_writable(exp); run = run_by_id(data, rid)
    require(phase in run['phases'], 'Capture before reviewing'); validate_review(value, data, run['scenario'])
    details = run['phases'][phase]
    value = dict(value, binding={'submissionHash': details.get('submissionHash'),
                                 'evaluatorVersion': (details.get('evaluation') or {}).get('graderVersion'),
                                 'savedAt': now(), 'channel': 'operator'})
    dest = exp / 'results' / rid / phase / 'review.json'
    if dest.exists():
        history = dest.parent / 'review-history'; history.mkdir(exist_ok=True)
        shutil.copyfile(dest, history / f'{dt.datetime.now().timestamp():.6f}.json')
    write(dest, value); details['review'] = value; experiment.save(exp, data)
    experiment.log(exp, 'review_saved', run=rid, phase=phase)


def sync_reviews(exp, data):
    """Blind reviews are written by the separate review server; mirror them into the view."""
    for run in data['runs']:
        for phase, details in run['phases'].items():
            path = exp / 'results' / run['id'] / phase / 'review.json'
            if path.exists():
                details['review'] = read(path)
    return data


def review_is_current(exp, data, run, phase):
    """None = no review; False = the review judged a different submission or evaluator version."""
    details = run['phases'][phase]; review = details.get('review')
    if not review: return None
    version = scenario_for(data, run)['grader']['version']
    if review.get('label'):  # blind review: bound to the reviewer-visible inventory
        from bench_core import review_projection
        return (review.get('submissionHash') == review_projection.submission_hash(exp, run['id'], phase)
                and review.get('evaluatorVersion') == version)
    binding = review.get('binding') or {}
    return (binding.get('submissionHash') == details.get('submissionHash')
            and binding.get('evaluatorVersion') in (None, version))


def record_metrics(exp, rid, phase, value):
    data = load_writable(exp); run = run_by_id(data, rid)
    require(isinstance(value, dict), 'Metrics must be an object')
    allowed = {'costUSD', 'inputTokens', 'outputTokens', 'humanMinutes', 'interventions', 'notes', 'source'}
    require(set(value) <= allowed, 'Unknown metric field')
    for key in allowed - {'notes', 'source'}:
        n = value.get(key)
        require(n is None or (type(n) in [int, float] and math.isfinite(n) and n >= 0), f'{key} must be nonnegative or null')
        if key in ['inputTokens', 'outputTokens', 'interventions'] and n is not None:
            require(type(n) is int, f'{key} must be an integer')
    for key in ['notes', 'source']:
        require(isinstance(value.get(key, ''), str), f'{key} must be text')
    if any(value.get(k) is not None for k in allowed - {'notes', 'source'}):
        require(value.get('source', '').strip(), 'Record measurement source (provider usage/export, stopwatch, etc.)')
    run['metrics'][phase] = value; experiment.save(exp, data)
    experiment.log(exp, 'metrics_saved', run=rid, phase=phase, metrics=value)


def import_trace(exp, rid, path):
    data = load_writable(exp); run_by_id(data, rid)
    result = traces.import_file(path, rid, data['definition']['id'], store=trace_store(exp))
    experiment.log(exp, 'trace_imported', run=rid, importer=result['importer'], importerVersion=result['importerVersion'],
                   sha256=result['sha256'], added=result['added'], duplicates=result['duplicates'])
    print(f'{rid}: importer {result["importer"]} {result["importerVersion"]}; '
          f'added {result["added"]}, duplicates ignored {result["duplicates"]}')


def pair(exp, a, b, phase, preference, evidence, reviewer):
    data = load_writable(exp); ra = run_by_id(data, a); rb = run_by_id(data, b)
    require(a != b and ra['pairKey'] == rb['pairKey'], 'Compare different runs that share a pair key')
    sync_reviews(exp, data)
    require(all(phase in r['phases'] and r['phases'][phase].get('review') for r in [ra, rb]), 'Save both individual reviews first')
    require(preference in ['a', 'b', 'tie', 'incomparable'], 'Invalid preference')
    require(isinstance(evidence, str) and evidence.strip() and isinstance(reviewer, str) and reviewer.strip(),
            'Pairwise judgment needs evidence and reviewer')
    data.setdefault('pairJudgments', []).append({'a': a, 'b': b, 'pairKey': ra['pairKey'], 'phase': phase,
                                                 'preference': preference, 'evidence': evidence,
                                                 'reviewer': reviewer, 'at': now()})
    experiment.save(exp, data); experiment.log(exp, 'pair_reviewed', a=a, b=b, phase=phase)


# ------------------------------------------------------------------ views

def view(exp):
    data, writable = experiment.load(exp)
    result = copy.deepcopy(data)
    for key in ('policyHashes', 'seedHashes'):
        result.pop(key, None)
    result['readOnly'] = not writable
    result['experimentPath'] = str(exp); result['controllerPath'] = str(ROOT / 'bench.py')
    if is_v1(data):
        result['legacy'] = 'v1 experiment: read-only; hashes, scores and report format are never rewritten.'
        for run in result['runs']:
            run.pop('initialHashes', None)
            run['methodLabel'] = next((m['label'] for m in data['methods'] if m['id'] == run['method']), run['method'])
            for details in run['phases'].values():
                details['gate'] = gate(details.get('evaluation'), details.get('review'))
        return result
    sync_reviews(exp, result)
    for item in result['methods'] + result['scenarios']:
        item.pop('_path', None)
    root = root_for(data)
    result['integrityOK'] = data['policyHashes'] == experiment.policy_hashes(root, data['methods'], data['scenarios'])
    result['readiness'] = experiment.readiness(data['definition'], experiment.frozen_registry(root, data))
    store = trace_store(exp); traced = set(store.runs())
    for run in result['runs']:
        run.pop('initialHashes', None)
        run['workspace'] = str(folder_for(exp, run))
        run['methodLabel'] = method_for(data, run)['label']
        launch = folder_for(exp, run) / 'LAUNCH.md'
        run['launch'] = launch.read_text() if launch.exists() else None
        run['reviewTemplate'] = blank_review(data, run['scenario'])
        run['hasTrace'] = run['id'] in traced
        for phase, details in run['phases'].items():
            current = review_is_current(exp, result, run, phase)
            details['reviewCurrent'] = current
            details['gate'] = ('Review is stale' if current is False
                               else gate(details.get('evaluation'), details.get('review')))
    return result


def trace_view(exp, rid):
    data = load(exp); run = run_by_id(data, rid); store = trace_store(exp)
    events = store.events(rid)
    report = metrics_module.analyze(store, run) if events else None
    return {'runId': rid, 'hasTrace': bool(events), 'synthetic': store.synthetic(rid) if events else None,
            'declared': store.declared_graph(rid), 'observed': store.observed_graph(rid),
            'join': report['join'] if report else None, 'lineage': report['lineage'] if report else {},
            'timeline': events, 'report': report}


def comparison(exp):
    data = sync_reviews(exp, load(exp)); store = trace_store(exp); traced = set(store.runs())
    if not is_v1(data):
        for run in data['runs']:
            for phase, details in run['phases'].items():
                details['reviewCurrent'] = review_is_current(exp, data, run, phase)
    reports = {run['id']: metrics_module.analyze(store, run) for run in data['runs'] if run['id'] in traced}
    result = metrics_module.compare(data, reports)
    result['operatorMetrics'] = {run['id']: run.get('metrics') or {} for run in data['runs']}
    result['pairJudgments'] = data.get('pairJudgments', [])
    return result


def export(exp, out=None):
    data = view(exp)
    out = Path(out) if out else exp / 'exports'
    require(not data['readOnly'] or out.resolve() != (exp / 'exports').resolve() and exp.resolve() not in out.resolve().parents,
            'v1 experiments are read-only; pass --out pointing outside the v1 experiment directory')
    out.mkdir(parents=True, exist_ok=True); write(out / 'results.json', data)
    if not is_v1(data):
        write(out / 'comparison.json', comparison(exp))
    fields = (['run', 'pairKey', 'scenario', 'repeat', 'method', 'phase', 'gate', 'passed', 'total', 'elapsedMinutes',
               'overBudget', 'critical', 'major', 'minor'] + DIMENSIONS
              + ['costUSD', 'humanMinutes', 'interventions', 'inputTokens', 'outputTokens'])
    with (out / 'results.csv').open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields); writer.writeheader()
        for run in data['runs']:
            for phase in PHASES:
                details = run['phases'].get(phase, {}); ev = details.get('evaluation', {})
                review = details.get('review'); m = run['metrics'].get(phase, {})
                row = {'run': run['id'], 'pairKey': run.get('pairKey'), 'scenario': run['scenario'], 'repeat': run['repeat'],
                       'method': run['methodLabel'], 'phase': phase, 'gate': details.get('gate', 'Not captured'),
                       'passed': ev.get('passed'), 'total': ev.get('total'),
                       'elapsedMinutes': details.get('elapsedMinutes'), 'overBudget': details.get('overBudget')}
                for severity in ['critical', 'major', 'minor']:
                    row[severity] = sum(d['severity'] == severity for d in review['defects']) if review else None
                for dimension in DIMENSIONS:
                    row[dimension] = review['scores'][dimension]['value'] if review else None
                for key in ['costUSD', 'humanMinutes', 'interventions', 'inputTokens', 'outputTokens']:
                    row[key] = m.get(key)
                writer.writerow(row)
    print(f'Exported {out / "results.csv"} and results.json. Missing values remain blank; no automatic winner.')


# ------------------------------------------------------------------ operator server

def make_server(exp, port):
    token = secrets.token_urlsafe(24)

    class Handler(http.server.BaseHTTPRequestHandler):
        def send(self, status, value, ctype='application/json'):
            body = (json.dumps(value) if ctype == 'application/json' else value).encode()
            self.send_response(status); self.send_header('Content-Type', ctype)
            self.send_header('Cache-Control', 'no-store'); self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)

        def valid_host(self):
            actual = self.server.server_address[1]
            return self.headers.get('Host', '') in [f'127.0.0.1:{actual}', f'localhost:{actual}']

        def do_GET(self):
            if not self.valid_host(): return self.send(403, {'error': 'Local host required'})
            try:
                with LOCK:
                    if self.path == '/':
                        page = (ROOT / 'bench/dashboard.html').read_text().replace('__BENCH_TOKEN__', token)
                        return self.send(200, page, 'text/html; charset=utf-8')
                    if self.path == '/api/data': return self.send(200, view(exp))
                    if self.path == '/api/metrics': return self.send(200, comparison(exp))
                    if self.path.startswith('/api/trace/'): return self.send(200, trace_view(exp, self.path.split('/')[3]))
                    asset = (ROOT / 'bench/assets' / self.path[len('/assets/'):]).resolve() if self.path.startswith('/assets/') else None
                    if asset and (ROOT / 'bench/assets').resolve() in asset.parents and asset.is_file():
                        kind = {'.js': 'text/javascript', '.mjs': 'text/javascript', '.css': 'text/css',
                                '.svg': 'image/svg+xml', '.json': 'application/json'}.get(asset.suffix, 'text/plain')
                        return self.send(200, asset.read_text(), kind + '; charset=utf-8')
                self.send(404, {'error': 'Not found'})
            except Exception as e:
                self.send(400, {'error': str(e)})

        def do_POST(self):
            if not self.valid_host() or self.headers.get('X-Bench-Token') != token:
                return self.send(403, {'error': 'Use this local bench page'})
            try:
                length = int(self.headers.get('Content-Length', '0')); require(0 < length <= 500000, 'Invalid body length')
                body = json.loads(self.rfile.read(length))
                with LOCK:
                    if self.path in ('/api/review', '/api/metrics', '/api/pair'):
                        require(body['phase'] in PHASES, 'Invalid phase')
                    if self.path == '/api/review': save_review(exp, body['run'], body['phase'], body['review'])
                    elif self.path == '/api/metrics': record_metrics(exp, body['run'], body['phase'], body['metrics'])
                    elif self.path == '/api/configure': configure(exp, body['method'], body['definition'])
                    elif self.path == '/api/pair':
                        pair(exp, body['a'], body['b'], body['phase'], body['preference'], body['evidence'], body['reviewer'])
                    else: return self.send(404, {'error': 'Not found'})
                self.send(200, {'ok': True})
            except Exception as e:
                self.send(400, {'error': str(e)})

        def log_message(self, *args): pass

    server = http.server.ThreadingHTTPServer(('127.0.0.1', port), Handler)
    server.bench_token = token
    return server


def serve(exp, port, open_browser):
    server = make_server(exp, port)  # a busy port raises; an unowned server is never terminated
    url = f'http://127.0.0.1:{server.server_address[1]}'
    print(f'Bench available at {url}\nExperiment: {exp}\nNo model is launched by this server. Ctrl-C stops the bench.', flush=True)
    if open_browser: webbrowser.open(url)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()


# Serialize mutations across Terminal commands and the dashboard server.
def locked(function):
    @functools.wraps(function)
    def call(exp, *args, **kwargs):
        with LOCK, common.experiment_lock(exp):
            return function(exp, *args, **kwargs)
    return call


for _name in ['configure', 'start', 'repair', 'capture', 'evaluate', 'save_review', 'record_metrics', 'import_trace', 'pair']:
    globals()[_name] = locked(globals()[_name])


def print_status(exp):
    data = view(exp)
    if data['readOnly']: print('v1 experiment (read-only)')
    for r in data['runs']:
        print(f'{r["order"]:2} {r["id"]} {r["scenario"]} r{r["repeat"]} {r["methodLabel"]:38} {r["status"]}')
    if 'readiness' in data and not data['readiness']['ready']:
        print('NOT READY:\n  - ' + '\n  - '.join(data['readiness']['blockers']))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--experiment', type=Path, default=ROOT / '.runtime/experiment')
    sub = parser.add_subparsers(dest='cmd', required=True)
    sub.add_parser('registry', help='validate method, scenario and experiment definitions')
    p = sub.add_parser('calibrate', help='grade each scenario reference and known-bad submission'); p.add_argument('scenario', nargs='*')
    p = sub.add_parser('prepare'); p.add_argument('--definition', required=True)
    sub.add_parser('status'); sub.add_parser('readiness')
    p = sub.add_parser('configure'); p.add_argument('method'); p.add_argument('--file', type=Path, required=True)
    for name in ['start', 'repair']:
        p = sub.add_parser(name); p.add_argument('run')
    for name in ['capture', 'evaluate', 'metrics']:
        p = sub.add_parser(name); p.add_argument('run'); p.add_argument('--phase', choices=PHASES, default='first')
        if name == 'metrics': p.add_argument('--file', type=Path, required=True)
    p = sub.add_parser('trace-import'); p.add_argument('run'); p.add_argument('--file', type=Path, required=True)
    p = sub.add_parser('analyze'); p.add_argument('run', nargs='?')
    p = sub.add_parser('review'); p.add_argument('--run', required=True)
    p.add_argument('--phase', choices=PHASES, default='first'); p.add_argument('--file', type=Path, required=True)
    p = sub.add_parser('blind', help='export sanitized reviewer packages'); p.add_argument('--phase', choices=PHASES, default='first')
    p.add_argument('--out', type=Path)
    p = sub.add_parser('export'); p.add_argument('--out', type=Path)
    p = sub.add_parser('serve'); p.add_argument('--port', type=int, default=DEFAULT_PORT); p.add_argument('--open', action='store_true')
    p = sub.add_parser('serve-review', help='separate blind-review server; has no operator routes')
    p.add_argument('--port', type=int, default=REVIEW_PORT); p.add_argument('--open', action='store_true')
    args = parser.parse_args(argv); exp = args.experiment.expanduser().resolve()
    try:
        if args.cmd == 'registry':
            errors = registry_module.validate(ROOT); registry = registry_module.load(ROOT, strict=False)
            print(f'{len(registry.methods)} methods, {len(registry.scenarios)} scenarios, {len(registry.definitions)} experiment definitions')
            for definition in registry.definitions.values():
                state = experiment.readiness(definition, registry)
                print(f'  {definition["id"]}: {"ready" if state["ready"] else "NOT ready (" + str(len(state["blockers"])) + " blockers)"}')
            for error in errors: print(f'ERROR {error}', file=sys.stderr)
            return 1 if errors else 0
        if args.cmd == 'calibrate':
            registry = registry_module.load(ROOT); failed = False
            for sid in args.scenario or sorted(registry.scenarios):
                report = registry_module.calibrate(registry.scenario(sid), ROOT)
                print(f'{sid}: {report.get("status")}'); failed |= report.get('status') == 'failed'
            return 1 if failed else 0
        if args.cmd == 'prepare': return prepare(exp, args.definition)
        require((exp / 'experiment.json').exists(), 'Experiment missing; run prepare first')
        if args.cmd == 'status': print_status(exp)
        elif args.cmd == 'readiness': print(json.dumps(view(exp).get('readiness', {'note': 'v1 experiment'}), indent=2))
        elif args.cmd == 'configure': configure(exp, args.method, read(args.file))
        elif args.cmd == 'start': start(exp, args.run)
        elif args.cmd == 'repair': repair(exp, args.run)
        elif args.cmd == 'capture': capture(exp, args.run, args.phase)
        elif args.cmd == 'evaluate': evaluate(exp, args.run, args.phase)
        elif args.cmd == 'metrics': record_metrics(exp, args.run, args.phase, read(args.file))
        elif args.cmd == 'trace-import': import_trace(exp, args.run, args.file)
        elif args.cmd == 'analyze':
            print(json.dumps(trace_view(exp, args.run)['report'] if args.run else comparison(exp), indent=2))
        elif args.cmd == 'review': save_review(exp, args.run, args.phase, read(args.file))
        elif args.cmd == 'blind':
            from bench_core import review_projection
            load_writable(exp); out = args.out or exp / 'blind' / args.phase
            review_projection.export(exp, args.phase, out)
            found = review_projection.scan(out, review_projection.forbidden_terms(exp))
            leaks = [item for item in found if item['kind'] == 'leak']
            for item in found:
                print(f'{item["kind"].upper()}: {item["term"]!r} in {item["where"]}', file=sys.stderr)
            require(not leaks, f'{len(leaks)} identity leak(s) in {out}. Do not hand these packages to a reviewer.')
            print(f'Sanitized reviewer packages: {out} (identity scan: 0 leaks, {len(found)} residual cue(s) in submitted source)')
        elif args.cmd == 'export': export(exp, args.out)
        elif args.cmd == 'serve': serve(exp, args.port, args.open)
        elif args.cmd == 'serve-review':
            from bench_core import review_server
            review_server.serve(exp, args.port, args.open)
    except (ValueError, KeyError, TypeError, json.JSONDecodeError, OSError) as error:
        print(f'Error: {error}', file=sys.stderr); return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
