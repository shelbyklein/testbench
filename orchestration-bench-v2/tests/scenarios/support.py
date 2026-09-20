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


def node_test(*relative_paths):
    """Run ``node --test`` over files in the repository; returns the CompletedProcess."""
    return subprocess.run(['node', '--test', *[str(ROOT / p) for p in relative_paths]],
                          cwd=str(ROOT), text=True, capture_output=True, timeout=180)
