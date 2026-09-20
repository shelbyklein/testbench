#!/usr/bin/env python3
"""One offline validation command for Orchestration Bench v2.

    python3 validate.py            # everything
    python3 validate.py --skip-browser

Runs registry/scheduling, trace reconciliation, grader calibration, budgets/restarts, review
isolation and a complete SYNTHETIC lifecycle:
prepare -> configure -> start -> capture -> grade -> blind review -> repair -> compare -> export.

Nothing here invokes a model or opens a non-loopback connection. The synthetic executor is a
file copy; the lifecycle runs with outbound sockets and provider CLIs blocked to prove it.
All generated data lands under .runtime/validation/ and is labeled synthetic.
"""
import argparse
import copy
import hashlib
import json
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import bench  # noqa: E402
from bench_core import common, experiment, registry as registry_module, review_projection, traces  # noqa: E402

OUT = ROOT / '.runtime' / 'validation'
SUITES = ['integration', 'core', 'observation', 'scenarios', 'workflow', 'review', 'ui']
PROVIDER_BINARIES = {'claude', 'codex', 'openai', 'anthropic', 'gemini', 'ollama', 'curl', 'wget'}
V1_HASHES = {
    'orchestration-bench/bench.py': 'caeacdc3cdc2af40a36a98c4d72a39b33ad8b580c8f29305f2d3fe0d16b7902c',
    'orchestration-bench/experiments/pilot/experiment.json': '862c679557a91ef096cd23a5c548e76244adbdac797e1de4aad977a9dfaccd68',
    'orchestration-bench.zip': '6a8e0c3221978eff34c2f57763e96990dc0d307c98ca7be6834ff8501916c05b',
}


class Guard:
    """Fail loudly if the synthetic lifecycle tries to reach a provider."""

    def __enter__(self):
        self.connect, self.popen = socket.socket.connect, subprocess.Popen.__init__
        self.spawned = []
        guard = self

        def connect(sock, address):
            host = address[0] if isinstance(address, tuple) else address
            if host not in ('127.0.0.1', '::1', 'localhost'):
                raise AssertionError(f'Synthetic lifecycle attempted a non-loopback connection: {address}')
            return guard.connect(sock, address)

        def popen(process, args, *a, **kw):
            binary = Path(args if isinstance(args, str) else args[0]).name
            guard.spawned.append(binary)
            if binary in PROVIDER_BINARIES:
                raise AssertionError(f'Synthetic lifecycle attempted to run a provider/network binary: {binary}')
            return guard.popen(process, args, *a, **kw)

        socket.socket.connect, subprocess.Popen.__init__ = connect, popen
        return self

    def __exit__(self, *exc):
        socket.socket.connect, subprocess.Popen.__init__ = self.connect, self.popen


def synthetic_method(method_id, label):
    setting = lambda value: {'requested': value, 'effective': None, 'verified': False}
    limit = lambda value, how: {'limit': value, 'enforcement': how}
    return {'contract': 'method/1', 'id': method_id, 'version': '0.0.0-synthetic', 'label': label, 'mode': 'synthetic',
            'configured': False,
            'roles': [{'role': 'synthetic file-copy executor', 'model': setting('RECORD SYNTHETIC'), 'reasoning': setting('n/a')}],
            'transport': 'validate.py copies a fixture into the workspace; no model exists',
            'launch_template': 'methods/templates/solo.md', 'internal_review': {'enabled': False, 'reviewer_role': None},
            'adapter': None,
            'budgets': {'max_workers': limit(1, 'unenforced'), 'max_attempts': limit(None, 'unenforced'),
                        'max_minutes': limit(None, 'unenforced'), 'max_tokens': limit(None, 'unavailable'),
                        'max_cost_usd': limit(None, 'unavailable')},
            'notes': 'SYNTHETIC validation method. Not a candidate; results say nothing about any model.'}


def synthetic_executor(source, workspace):
    """The whole 'agent': copy a prepared fixture over the workspace. Provider-free by construction."""
    for path in sorted(Path(source).rglob('*')):
        if path.is_file():
            target = Path(workspace) / path.relative_to(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
    (Path(workspace) / 'SUBMISSION.md').write_text('Synthetic submission written by validate.py.\n')


def synthetic_trace(path, run_id, outcome):
    stamp = lambda second: f'2026-01-01T00:00:{second:02d}+00:00'
    base = {'schema': 'trace-event/1', 'runId': run_id, 'experimentId': 'synthetic-lifecycle', 'nodeId': 'solo', 'attempt': 1,
            'role': 'solo', 'status': 'ok', 'synthetic': True, 'clock': {'source': 'synthetic', 'uncertaintySeconds': None}}
    events = [dict(base, eventId=f'{run_id}-declared', type='node_declared', timestamp=stamp(0)),
              dict(base, eventId=f'{run_id}-started', type='node_started', timestamp=stamp(1)),
              dict(base, eventId=f'{run_id}-ended', type='node_completed' if outcome == 'ok' else 'node_failed',
                   status='ok' if outcome == 'ok' else 'error', timestamp=stamp(9))]
    Path(path).write_text(''.join(json.dumps(traces.normalize_event(e)) + '\n' for e in events))


def complete_review(template, defect=None):
    review = copy.deepcopy(template['blank']); review['reviewer'] = 'synthetic-reviewer'
    for score in review['scores'].values():
        score.update(value=2, evidence='Synthetic validation evidence')
    for item in review['manual']:
        item.update(status='pass', evidence='Synthetic validation evidence')
    if defect:
        review['defects'] = [{'severity': 'major', 'evidence': defect}]
    return review


def lifecycle():
    exp = OUT / 'synthetic-lifecycle'
    if exp.exists():
        shutil.rmtree(exp)
    registry = registry_module.load(ROOT)
    scenario = registry.scenario('S5')
    pack = ROOT / 'scenario_packs' / 'S5' / 'private'
    registry.methods.update({m['id']: m for m in (synthetic_method('syn-good', 'Synthetic A'), synthetic_method('syn-partial', 'Synthetic B'))})
    registry.definitions['synthetic-lifecycle'] = {
        'contract': 'experiment-definition/1', 'id': 'synthetic-lifecycle', 'title': 'SYNTHETIC lifecycle validation',
        'question': 'Does the bench lifecycle work offline?', 'establishes': 'Nothing about any model.',
        'methods': ['syn-good', 'syn-partial'], 'scenarios': ['S5'], 'repeats': 1, 'seed': 7, 'phases': ['first', 'repaired'],
        'environment': {'id': 'synthetic', 'notes': 'validate.py'}, 'controls': {}}
    steps = []
    with Guard() as guard:
        data = experiment.prepare(ROOT, 'synthetic-lifecycle', exp, registry)
        data['synthetic'] = True; experiment.save(exp, data); steps.append('prepare')
        first = data['runs'][0]['id']
        try:
            bench.start(exp, first); raise AssertionError('Unconfigured run was allowed to start')
        except ValueError:
            steps.append('start refused while unconfigured')
        for method in data['methods']:
            value = copy.deepcopy({k: v for k, v in method.items() if k != '_path'})
            value['configured'] = True; value['roles'][0]['model']['requested'] = 'none (synthetic file copy)'
            bench.configure(exp, method['id'], value)
        steps.append('configure')
        runs = {run['method']: run['id'] for run in bench.load(exp)['runs']}
        fixtures = {'syn-good': pack / 'reference', 'syn-partial': pack / 'known_bad' / 'partial-migration'}
        for method, rid in runs.items():
            bench.start(exp, rid); synthetic_executor(fixtures[method], exp / 'workspaces' / rid)
            bench.capture(exp, rid, 'first'); bench.evaluate(exp, rid, 'first')
            trace = OUT / f'{rid}.trace.jsonl'; synthetic_trace(trace, rid, 'ok')
            bench.import_trace(exp, rid, trace); bench.import_trace(exp, rid, trace)  # second import must add nothing
        steps += ['start', 'capture', 'grade', 'trace import (idempotent)']
        evaluations = {m: bench.load(exp)['runs'][i]['phases']['first']['evaluation'] for i, m in enumerate(r['method'] for r in bench.load(exp)['runs'])}
        assert evaluations['syn-good']['allPassed'] is True, 'Reference submission should pass the private grader'
        assert evaluations['syn-partial']['allPassed'] is False, 'Partial migration should fail the private grader'

        packages = review_projection.export(exp, 'first', exp / 'blind' / 'first')
        leaks = [l for l in review_projection.scan(exp / 'blind' / 'first', review_projection.forbidden_terms(exp)) if l['kind'] == 'leak']
        assert not leaks, f'Blind package leaks identity: {leaks[:3]}'
        for projection in review_projection.build(exp, 'first'):
            passed = projection['evaluation']['passed'] == projection['evaluation']['total']
            review_projection.accept_review(exp, projection['label'], 'first', projection['submissionHash'], projection['evaluatorVersion'],
                                            complete_review(projection['reviewTemplate'], None if passed else 'Synthetic: consumers left on the v1 contract'))
        stale = review_projection.build(exp, 'first')[0]
        try:
            review_projection.accept_review(exp, stale['label'], 'first', '0' * 64, stale['evaluatorVersion'], complete_review(stale['reviewTemplate']))
            raise AssertionError('Stale review was accepted')
        except review_projection.StaleReview:
            pass
        steps += [f'blind export ({len(packages)} packages, 0 identity leaks)', 'blind review', 'stale review rejected']

        rid = runs['syn-partial']
        bench.repair(exp, rid); synthetic_executor(pack / 'reference', exp / 'workspaces' / rid)
        bench.capture(exp, rid, 'repaired'); bench.evaluate(exp, rid, 'repaired'); steps.append('repair')
        first_snapshot = common.inventory(exp / 'snapshots' / rid / 'first')
        assert first_snapshot == common.read(exp / 'receipts' / rid / 'first.json')['hashes'], 'First submission changed during repair'

        comparison = bench.comparison(exp)
        assert comparison['winner'] is None and comparison['compositeScore'] is None, 'Comparison must not declare a winner'
        assert comparison['synthetic'] is True, 'Synthetic comparison must be labeled synthetic'
        bench.export(exp); steps += ['compare (no winner)', 'export']
        view = bench.view(exp)
        gates = {run['methodLabel']: {p: d['gate'] for p, d in run['phases'].items()} for run in view['runs']}
    assert not PROVIDER_BINARIES & set(guard.spawned), guard.spawned
    return {'experiment': str(exp.relative_to(ROOT)), 'steps': steps, 'gates': gates,
            'processesSpawned': sorted(set(guard.spawned)), 'nonLoopbackConnections': 0, 'synthetic': True}


def suite(name, skip_browser):
    folder = ROOT / 'tests' / name
    if not folder.is_dir():
        return {'suite': name, 'status': 'FAILED', 'summary': 'suite directory is missing', 'output': None}
    env = dict(__import__('os').environ, OB2_SKIP_BROWSER='1') if skip_browser else None
    started = time.time()
    result = subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', f'tests/{name}', '-t', '.', '-p', 'test_*.py'],
                            cwd=ROOT, capture_output=True, text=True, env=env)
    tail = result.stderr.strip().splitlines()[-3:]
    ran = next((line for line in tail if line.startswith('Ran ')), '')
    return {'suite': name, 'status': 'ok' if result.returncode == 0 else 'FAILED', 'summary': ran,
            'outcome': tail[-1] if tail else '', 'seconds': round(time.time() - started, 1),
            'output': None if result.returncode == 0 else result.stderr[-4000:]}


def v1_unchanged():
    repo = ROOT.parent
    found = {path: (hashlib.sha256((repo / path).read_bytes()).hexdigest() if (repo / path).exists() else None) for path in V1_HASHES}
    if all(value is None for value in found.values()):
        return {'status': 'not applicable', 'note': 'Frozen v1 is not present beside this folder (e.g. running from the v2 ZIP).'}
    return {'status': 'ok' if found == V1_HASHES else 'FAILED', 'hashes': found}


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--skip-browser', action='store_true')
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    report = {'synthetic': True, 'paidModelCalls': 0, 'python': sys.version.split()[0],
              'node': subprocess.run(['node', '--version'], capture_output=True, text=True).stdout.strip()}
    report['registryErrors'] = registry_module.validate(ROOT)
    registry = registry_module.load(ROOT, strict=False)
    report['readiness'] = {d['id']: experiment.readiness(d, registry)['ready'] for d in registry.definitions.values()}
    report['calibration'] = {sid: registry_module.calibrate(s, ROOT).get('status') for sid, s in sorted(registry.scenarios.items())}
    report['suites'] = [suite(name, args.skip_browser) for name in SUITES]
    try:
        report['lifecycle'] = dict(lifecycle(), status='ok')
    except Exception as error:  # report, then fail
        report['lifecycle'] = {'status': 'FAILED', 'error': f'{type(error).__name__}: {error}'}
    report['v1Unchanged'] = v1_unchanged()
    failed = (bool(report['registryErrors']) or any(s['status'] == 'FAILED' for s in report['suites'])
              or 'failed' in report['calibration'].values() or report['lifecycle']['status'] != 'ok'
              or report['v1Unchanged']['status'] == 'FAILED')
    report['result'] = 'FAILED' if failed else 'ok'
    common.write(OUT / 'validation-report.json', report)
    for item in report['suites']:
        print(f'tests/{item["suite"]:<12} {item["status"]:<7} {item.get("summary", "")}')
        if item.get('output'): print(item['output'])
    print('calibration  ', report['calibration'])
    print('readiness    ', report['readiness'], '(real experiments stay unready until model roles are recorded)')
    print('lifecycle    ', report['lifecycle']['status'], report['lifecycle'].get('error') or ' -> '.join(report['lifecycle']['steps']))
    print('v1 unchanged ', report['v1Unchanged']['status'])
    print(f'RESULT: {report["result"]}   report: {OUT / "validation-report.json"}   (synthetic; 0 paid model calls)')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
