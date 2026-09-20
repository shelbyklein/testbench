"""Helpers for the scenarios lane tests: grading fixtures through the real registry."""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bench_core import registry  # noqa: E402
from bench_core.common import measurement  # noqa: E402

DATA_DIRS = ('methods', 'scenario_packs', 'experiments', 'scenarios', 'seed', 'evaluator')


def scenario(scenario_id):
    """The scenario entry as the registry loads it from the real root."""
    return registry.load(ROOT, strict=False).scenario(scenario_id)


def grade(scenario_id, candidate_dir):
    """Run a scenario's grader over a candidate directory; returns the report dict."""
    with tempfile.TemporaryDirectory(prefix='ob2-grade-') as temp:
        out = Path(temp) / 'report.json'
        report, _ = registry.run_grader(scenario(scenario_id), Path(candidate_dir), out, ROOT)
    return report


def failed_ids(report):
    return sorted(check['id'] for check in report['checks'] if check['status'] != 'pass')


def evidence(report, check_id):
    for check in report['checks']:
        if check['id'] == check_id:
            return check.get('evidence') or ''
    raise AssertionError(f'No check {check_id!r} in the report')


def submission(temp_dir, source, **files):
    """A candidate directory: a copy of ``source`` with extra files written over it."""
    target = Path(temp_dir) / 'candidate'
    if source is not None:
        shutil.copytree(source, target, ignore=shutil.ignore_patterns('.git', 'node_modules'))
    else:
        target.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        path = target / name.replace('__', '.')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content if isinstance(content, str) else json.dumps(content, indent=2))
    return target


def copy_registry_root(destination):
    """A writable data-only copy of the registry root (same shape the core lane tests use)."""
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    for name in DATA_DIRS:
        source = ROOT / name
        if source.is_dir():
            shutil.copytree(source, destination / name,
                            ignore=shutil.ignore_patterns('.git', 'node_modules', '__pycache__'))
    return destination


def unavailable(unit, reason):
    """An explicitly unknown measurement, carrying why it is unknown (contract §3)."""
    result = measurement(None, unit)
    result['reason'] = reason
    return result


def recovery_report(first, second, analysis):
    """Reuse / repeated-work / recovery-cost for one crash-and-restart pair.

    SYNTHETIC. Assembled from the offline adapter result and `metrics.analyze`. Every value
    is either observed in the trace or reported as unavailable **with a reason**; nothing is
    filled in with 0, and nothing is inferred from a count of agents or calls.
    """
    crash = first.get('crash') or {}
    effects = [entry['key'] for entry in second.get('effects', [])]
    reused = list(second.get('reusedNodes') or [])
    rerun = sorted(r['nodeId'] for r in second.get('replay', []) if not r['reused'])
    wall = (analysis.get('wallTime') or {}).get('seconds') or {}
    usage = (analysis.get('usageTotals') or {}).get('inputTokens') or {}

    return {
        'synthetic': True,
        'note': 'simulated worker recovery through the offline adapter; not a verified real '
                'coding-agent restart',
        'milestone': crash.get('milestone'),
        'interruptedNode': crash.get('nodeId'),
        'reusedNodes': reused,
        'reuseIdentityChecks': ['sourceRevision', 'artifactHash'],
        'repeatedWorkNodes': rerun,
        'duplicatedEffects': sorted({k for k in effects if effects.count(k) > 1}),
        'faults': (analysis.get('faults') or {}).get('count'),
        'retries': (analysis.get('retries') or {}).get('nodes'),
        # Observed: the restart run's own wall time, from the interval union.
        'restartWallSeconds': (dict(wall) if wall.get('value') is not None
                               else unavailable('seconds', (analysis.get('trace') or {})
                                                .get('issues') and 'the trace has open intervals'
                                                or 'no measured interval in the trace')),
        # Not observed: the fake executor reports no token usage at all.
        'recoveryTokens': unavailable(
            'tokens', 'the executor reports no token usage; '
                      f'{usage.get("unknownCount", 0)} unknown measurement(s) in the trace'),
        'recoveryCostUSD': unavailable(
            'usd', 'no cost is observable offline; a paid run was never made'),
        'criticalPathSeconds': ((analysis.get('criticalPath') or {}).get('seconds')
                                if (analysis.get('criticalPath') or {}).get('supported')
                                else unavailable('seconds',
                                                 (analysis.get('criticalPath') or {}).get('reason'))),
    }


def node_test(*relative_paths):
    """Run ``node --test`` over files in the repository; returns the CompletedProcess."""
    return subprocess.run(['node', '--test', *[str(ROOT / p) for p in relative_paths]],
                          cwd=str(ROOT), text=True, capture_output=True, timeout=180)
