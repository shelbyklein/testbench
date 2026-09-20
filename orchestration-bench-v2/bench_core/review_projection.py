"""Isolated blind review projections (CONTRACTS.md §10).

A projection is built **field by field** from the immutable capture on disk. It is never a
filtered copy of operator state: this module reads the experiment only to find which runs
have an evaluated snapshot, and copies nothing from a run record into the reviewer payload
except the scenario ID/version, repeat and phase that the contract explicitly allows.

Blinding is best effort. Metadata (labels, projection JSON, file names, review packages) is
held to a strict standard and must contain no operator term. Submitted source *content* can
always reveal its own author — a comment, a commit message, a README voice — so
``scan`` reports a term found inside submitted content as a ``residualCue`` rather than a
leak, and every projection carries the same warning in ``residualCues``.
"""
import json
import re
import secrets
import shutil
import time
from pathlib import Path

from . import common, experiment as experiment_module

CONTRACT = 'review-projection/1'
DIMENSIONS = ['correctness', 'completeness', 'maintainability', 'ux', 'evidence_quality']
SEVERITIES = ['critical', 'major', 'minor']
MANUAL_STATUS = ['pass', 'fail', 'not_run']
LABEL_PREFIX = 'B-'
MAP_FILE = 'review-map.json'
HISTORY_DIR = 'review-history'
#: Operator-authored or method-revealing files that never reach a reviewer.
IDENTITY_FILES = {'LAUNCH.md', 'APPROACH.md', 'SUBMISSION.md', 'HANDOFF.md', 'AGENTS.md'}
EXCLUDED_PARTS = set(common.EXCLUDED) | {'.git'}
RESIDUAL_CUES = ('Submitted source may itself reveal its author (comments, commit messages, '
                 'report voice); anonymity is best-effort, not guaranteed.')
MIN_TERM_LENGTH = 3
#: Contract vocabulary that operator state happens to contain but that is also ordinary
#: reviewer-facing English (role names from §8, phase names, the word "review" itself).
#: Treating these as identity terms would flag the rubric and the reviewer prompt, so they are
#: excluded from the derived term set. Identity lives in method IDs, labels, modes and models.
GENERIC_TERMS = {'planner', 'worker', 'reviewer', 'integrator', 'orchestrator', 'tool',
                 'implementer', 'evaluator', 'grader', 'private', 'review', 'submission',
                 'first', 'repaired', 'none', 'null'}


class StaleReview(Exception):
    """The submission or the evaluator moved under the reviewer; the review is refused."""


class ReviewError(Exception):
    """The reviewer payload is not acceptable (validation, unknown label, unknown phase)."""


# ---------------------------------------------------------------- experiment access

def _experiment(exp_dir):
    data, writable = experiment_module.load(Path(exp_dir))
    return data, writable


def _require_writable(exp_dir):
    data, writable = _experiment(exp_dir)
    if not writable:
        raise ReviewError('This experiment is read-only (v1 or unknown format); '
                          'review projections are only assigned and stored for v2 experiments.')
    return data


def _scenario_of(data, run):
    for scenario in data.get('scenarios') or []:
        if scenario.get('id') == run.get('scenario'):
            return scenario
    raise ReviewError('The experiment has no frozen scenario for this submission.')


def _private_prefixes(scenario):
    """Snapshot-relative prefixes that must never appear in a review package."""
    prefixes = []
    for entry in scenario.get('private') or []:
        parts = Path(entry).parts
        if parts:
            prefixes.append(parts)
            prefixes.append(parts[-1:])
    return prefixes


# ---------------------------------------------------------------- labels

def _map_path(exp_dir):
    return Path(exp_dir) / MAP_FILE


def _read_map(exp_dir):
    path = _map_path(exp_dir)
    if not path.exists():
        return {'contract': CONTRACT, 'note': 'Operator-only mapping. Never serve or export this file.',
                'labels': {}, 'byLabel': {}}
    return common.read(path)


def _key(run_id, phase):
    return f'{run_id}|{phase}'


def label_for(exp_dir, run_id, phase, assign=True):
    """Return the stable blind label for one (run, phase); assign a fresh one on first use."""
    mapping = _read_map(exp_dir)
    key = _key(run_id, phase)
    existing = mapping['labels'].get(key)
    if existing or not assign:
        return existing
    used = set(mapping['byLabel'])
    label = LABEL_PREFIX + secrets.token_hex(3).upper()
    while label in used:
        label = LABEL_PREFIX + secrets.token_hex(3).upper()
    mapping['labels'][key] = label
    mapping['byLabel'][label] = {'run': run_id, 'phase': phase}
    common.write(_map_path(exp_dir), mapping)
    return label


def resolve_label(exp_dir, label):
    """Operator-side resolution label -> {run, phase}. Never exposed over the review server."""
    entry = _read_map(exp_dir)['byLabel'].get(label)
    if not entry:
        raise ReviewError('Unknown review label.')
    return entry


# ---------------------------------------------------------------- reviewer-visible files

def _visible_files(snapshot, scenario):
    """Allow-listed inventory of the immutable snapshot, sorted by path.

    Symlinks are dropped rather than followed: a snapshot symlink cannot be served safely and
    is not reproducible evidence.
    """
    snapshot = Path(snapshot)
    private = _private_prefixes(scenario)
    files = []
    for item in sorted(snapshot.rglob('*')):
        if item.is_symlink() or not item.is_file():
            continue
        relative = item.relative_to(snapshot)
        parts = relative.parts
        if any(part in EXCLUDED_PARTS for part in parts):
            continue
        if relative.name in IDENTITY_FILES:
            continue
        if any(parts[:len(prefix)] == prefix for prefix in private):
            continue
        files.append({'path': relative.as_posix(), 'sha256': common.digest(item)})
    return files


def _inventory(files):
    return {entry['path']: entry['sha256'] for entry in files}


def submission_hash(exp_dir, run_id, phase, scenario=None, data=None):
    """Hash of the reviewer-visible inventory of the immutable snapshot, recomputed now."""
    if scenario is None:
        data = data or _experiment(exp_dir)[0]
        scenario = _scenario_of(data, _run(data, run_id))
    snapshot = Path(exp_dir) / 'snapshots' / run_id / phase
    if not snapshot.is_dir():
        raise ReviewError('No captured submission for this label and phase.')
    return common.inventory_hash(_inventory(_visible_files(snapshot, scenario)))


def _run(data, run_id):
    for run in data.get('runs') or []:
        if run.get('id') == run_id:
            return run
    raise ReviewError('Unknown submission.')


# ---------------------------------------------------------------- review template

def manual_checks(scenario):
    """Normalise the scenario's manual checklist to ``{id, description}``."""
    checks = []
    for item in scenario.get('manual_checks') or []:
        checks.append({'id': item.get('id'),
                       'description': item.get('description') or item.get('instruction') or ''})
    return checks


def blank_review(scenario):
    return {'reviewer': '',
            'scores': {key: {'value': None, 'evidence': ''} for key in DIMENSIONS},
            'manual': [dict(check, status='not_run', evidence='') for check in manual_checks(scenario)],
            'defects': [],
            'notes': ''}


def review_template(scenario):
    return {'dimensions': list(DIMENSIONS),
            'scoreRange': [0, 3],
            'severities': list(SEVERITIES),
            'manualStatus': list(MANUAL_STATUS),
            'manualChecks': manual_checks(scenario),
            'blank': blank_review(scenario)}


def validate_review(value, scenario):
    """v1 ``validate_review`` semantics, driven by the scenario's own manual checklist."""
    def need(condition, message):
        if not condition:
            raise ReviewError(message)

    need(isinstance(value, dict), 'Review must be an object')
    need(isinstance(value.get('reviewer'), str) and value['reviewer'].strip(),
         'Reviewer name or anonymous reviewer ID is required')
    need(isinstance(value.get('scores'), dict) and set(value['scores']) == set(DIMENSIONS),
         'Include all five rubric dimensions')
    for score in value['scores'].values():
        need(isinstance(score, dict), 'Score must contain value and evidence')
        number = score.get('value')
        need(number is None or (type(number) is int and 0 <= number <= 3),
             'Scores must be integers 0-3 or null')
        need(isinstance(score.get('evidence'), str), 'Score evidence must be text')
        if number is not None:
            need(score['evidence'].strip(), 'Scored dimensions need evidence')
    manual = value.get('manual')
    need(isinstance(manual, list), 'Manual checks must be a list')
    expected = {check['id'] for check in manual_checks(scenario)}
    need(len(manual) == len(expected) and {item.get('id') for item in manual} == expected,
         'Manual check IDs must exactly match this scenario')
    for item in manual:
        need(item.get('status') in MANUAL_STATUS, 'Invalid manual status')
        need(isinstance(item.get('evidence'), str), 'Manual evidence must be text')
        if item['status'] != 'not_run':
            need(item['evidence'].strip(), 'Executed manual checks need evidence')
    need(isinstance(value.get('defects'), list), 'Defects must be a list')
    for defect in value['defects']:
        need(defect.get('severity') in SEVERITIES, 'Defect severity must be critical/major/minor')
        need(isinstance(defect.get('evidence'), str) and defect['evidence'].strip(),
             'Each defect needs reproduction/evidence')
    need(isinstance(value.get('notes', ''), str), 'Notes must be text')
    return value


# ---------------------------------------------------------------- evaluation reduction

def _reduce_evaluation(report):
    """Keep ``{id, description, status}`` per check plus passed/total.

    Evidence strings, runner stdout/stderr, smoke output, grader paths and ``details`` are
    hidden grading data and are dropped rather than filtered.
    """
    checks = []
    for check in report.get('checks') or []:
        checks.append({'id': check.get('id'),
                       'description': check.get('description') or '',
                       'status': 'pass' if check.get('status') == 'pass' else 'fail'})
    passed = report.get('passed')
    total = report.get('total')
    return {'checks': checks,
            'passed': passed if isinstance(passed, int) else sum(c['status'] == 'pass' for c in checks),
            'total': total if isinstance(total, int) else len(checks)}


# ---------------------------------------------------------------- build

def _evaluation_path(exp_dir, run_id, phase):
    return Path(exp_dir) / 'results' / run_id / phase / 'evaluation.json'


def build(exp_dir, phase):
    """Projections for every evaluated submission of ``phase``, sorted by blind label.

    The order is the label order only: it carries no schedule position, no method order and
    no run ID ordering.
    """
    exp_dir = Path(exp_dir)
    data = _require_writable(exp_dir)
    projections = []
    for run in data.get('runs') or []:
        run_id = run.get('id')
        snapshot = exp_dir / 'snapshots' / run_id / phase
        evaluation_file = _evaluation_path(exp_dir, run_id, phase)
        if not snapshot.is_dir() or not evaluation_file.is_file():
            continue
        scenario = _scenario_of(data, run)
        files = _visible_files(snapshot, scenario)
        label = label_for(exp_dir, run_id, phase)
        projections.append({
            'contract': CONTRACT,
            'label': label,
            'scenario': scenario.get('id'),
            'scenarioVersion': scenario.get('version'),
            'repeat': run.get('repeat'),
            'phase': phase,
            'submissionHash': common.inventory_hash(_inventory(files)),
            'evaluatorVersion': (scenario.get('grader') or {}).get('version'),
            'files': files,
            'evaluation': _reduce_evaluation(common.read(evaluation_file)),
            'reviewTemplate': review_template(scenario),
            'residualCues': RESIDUAL_CUES,
        })
    return sorted(projections, key=lambda p: p['label'])


def summary(projection):
    """The listing row: everything in the projection except the file list and the template."""
    return {'contract': CONTRACT,
            'label': projection['label'],
            'scenario': projection['scenario'],
            'scenarioVersion': projection['scenarioVersion'],
            'repeat': projection['repeat'],
            'phase': projection['phase'],
            'submissionHash': projection['submissionHash'],
            'evaluatorVersion': projection['evaluatorVersion'],
            'fileCount': len(projection['files']),
            'evaluation': {'passed': projection['evaluation']['passed'],
                           'total': projection['evaluation']['total']},
            'residualCues': projection['residualCues']}


def find(exp_dir, phase, label):
    for projection in build(exp_dir, phase):
        if projection['label'] == label:
            return projection
    raise ReviewError('Unknown review label for this phase.')


# ---------------------------------------------------------------- export

def _docs_root(data):
    root = Path(data.get('root') or common.ROOT)
    return root if (root / 'docs').is_dir() else common.ROOT


def review_markdown(projection, docs_root):
    header = (f'# {projection["label"]} · {projection["scenario"]} '
              f'· repeat {projection["repeat"]} · {projection["phase"]}\n\n'
              'Run the app in submission/. Use a fresh data file and a unique port. '
              'Complete review.json; never edit submitted code.\n\n'
              f'Residual cues: {projection["residualCues"]}\n\n')
    parts = [header]
    for name in ('REVIEWER_PROMPT.md', 'RUBRIC.md'):
        path = Path(docs_root) / 'docs' / name
        if path.is_file():
            parts.append(path.read_text())
    return '\n'.join(parts)


def export(exp_dir, phase, out_dir):
    """Write one sanitized package per projection. Returns the written package paths."""
    exp_dir = Path(exp_dir)
    out_dir = Path(out_dir)
    data = _require_writable(exp_dir)
    docs_root = _docs_root(data)
    written = []
    for projection in build(exp_dir, phase):
        package = out_dir / projection['label']
        snapshot = exp_dir / 'snapshots' / _run_id_for_label(exp_dir, projection['label']) / phase
        (package / 'submission').mkdir(parents=True, exist_ok=True)
        for entry in projection['files']:
            target = package / 'submission' / entry['path']
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(snapshot / entry['path'], target)
        common.write(package / 'projection.json', projection)
        common.write(package / 'review.json', blank_review({'manual_checks': [
            {'id': check['id'], 'description': check['description']}
            for check in projection['reviewTemplate']['manualChecks']]}))
        (package / 'REVIEW.md').write_text(review_markdown(projection, docs_root))
        written.append(package)
    return written


def _run_id_for_label(exp_dir, label):
    return resolve_label(exp_dir, label)['run']


# ---------------------------------------------------------------- leak scanning

def forbidden_terms(exp_dir):
    """Operator terms that must not appear in reviewer metadata.

    Derived from operator state, not from a hand-written list: run IDs, method IDs/labels/modes,
    role names, requested and effective model/reasoning strings, transports, the absolute
    experiment path, every workspace path, the user's home directory and every private path.
    Terms shorter than ``MIN_TERM_LENGTH`` are dropped as unusably common.
    """
    exp_dir = Path(exp_dir)
    data, _ = _experiment(exp_dir)
    terms = set()

    def add(value):
        if not isinstance(value, str):
            return
        value = value.strip()
        if len(value) >= MIN_TERM_LENGTH and value.lower() not in GENERIC_TERMS:
            terms.add(value)

    root = Path(data.get('root') or common.ROOT)
    add(str(exp_dir.resolve()))
    add(str(exp_dir))
    add(str(root))
    add(str(Path.home()))
    for method in data.get('methods') or []:
        for key in ('id', 'label', 'mode', 'transport', 'launch_template', 'adapter'):
            add(method.get(key))
        for role in method.get('roles') or []:
            add(role.get('role'))
            for field in ('model', 'reasoning'):
                value = role.get(field) or {}
                if isinstance(value, dict):
                    add(value.get('requested'))
                    add(value.get('effective'))
        internal = method.get('internal_review') or {}
        add(internal.get('reviewer_role'))
    for scenario in data.get('scenarios') or []:
        for entry in scenario.get('private') or []:
            # Path-shaped so a bare English word ("evaluator") in reviewer prose is not a hit,
            # while a leaked private file path ("evaluator/checks.mjs") still is.
            add(entry.rstrip('/') + '/')
            add(str(root / entry))
        for token in (scenario.get('grader') or {}).get('argv') or []:
            if '/' in str(token):
                add(token)
                add(str(root / str(token)))
    for run in data.get('runs') or []:
        add(run.get('id'))
        add(str(experiment_module.workspace_for(exp_dir, run)))
        method = run.get('methodFrozen') or {}
        add(method.get('label'))
        add(method.get('mode'))
    return sorted(terms)


def _matches(text, terms):
    found = []
    for term in terms:
        pattern = re.compile(rf'(?<![\w/-]){re.escape(term)}(?![\w-])') if term.isidentifier() \
            else re.compile(re.escape(term))
        if pattern.search(text):
            found.append(term)
    return found


def _kind(location):
    """Submitted source content is a residual cue; everything else is a hard leak."""
    parts = Path(location).parts
    return 'residualCue' if 'submission' in parts or 'snapshots' in parts else 'leak'


def scan(path_or_obj, forbidden):
    """Report operator terms found in a payload, an exported file or an exported directory.

    Returns ``[{where, term, kind}]``. ``kind`` is ``leak`` for metadata (JSON payloads, file
    and directory names, review packaging) and ``residualCue`` for a match inside submitted
    source content, which blinding cannot remove. Callers fail on ``leak`` and record
    ``residualCue``.
    """
    forbidden = [t for t in forbidden if isinstance(t, str) and len(t) >= MIN_TERM_LENGTH]
    leaks = []
    if isinstance(path_or_obj, (bytes, bytearray)):
        for term in _matches(path_or_obj.decode('utf-8', 'replace'), forbidden):
            leaks.append({'where': '<bytes>', 'term': term, 'kind': 'leak'})
        return leaks
    if isinstance(path_or_obj, (dict, list)):
        for term in _matches(json.dumps(path_or_obj, ensure_ascii=False), forbidden):
            leaks.append({'where': '<object>', 'term': term, 'kind': 'leak'})
        return leaks
    path = Path(path_or_obj)
    if path.is_dir():
        for item in sorted(path.rglob('*')):
            if item.is_file() and not item.is_symlink():
                leaks.extend(scan(item, forbidden))
            for term in _matches(item.relative_to(path).as_posix(), forbidden):
                leaks.append({'where': str(item), 'term': term, 'kind': 'leak'})
        return leaks
    if path.is_file():
        try:
            text = path.read_text()
        except (UnicodeDecodeError, OSError):
            return leaks
        kind = _kind(path)
        for term in _matches(text, forbidden):
            leaks.append({'where': str(path), 'term': term, 'kind': kind})
        return leaks
    for term in _matches(str(path_or_obj), forbidden):
        leaks.append({'where': '<text>', 'term': term, 'kind': 'leak'})
    return leaks


# ---------------------------------------------------------------- accepting a review

def accept_review(exp_dir, label, phase, submitted_hash, evaluator_version, review):
    with common.experiment_lock(exp_dir):
        return _accept_review(exp_dir, label, phase, submitted_hash, evaluator_version, review)


def _accept_review(exp_dir, label, phase, submitted_hash, evaluator_version, review):
    """Bind a review to the exact submission it judged, or refuse it as stale.

    Refuses a v1 (read-only) experiment. Resolves the label operator-side, recomputes the
    current snapshot hash and compares both the hash and the evaluator version before any
    validation or write.
    """
    exp_dir = Path(exp_dir)
    data = _require_writable(exp_dir)
    entry = resolve_label(exp_dir, label)
    if entry['phase'] != phase:
        raise ReviewError('This label belongs to a different phase.')
    run = _run(data, entry['run'])
    scenario = _scenario_of(data, run)
    if not _evaluation_path(exp_dir, run['id'], phase).is_file():
        raise ReviewError('This submission has not been evaluated.')
    current_hash = submission_hash(exp_dir, run['id'], phase, scenario=scenario)
    current_version = (scenario.get('grader') or {}).get('version')
    if submitted_hash != current_hash:
        raise StaleReview('The submission changed after this review package was built. '
                          'Rebuild the review package and review the current submission.')
    if evaluator_version != current_version:
        raise StaleReview('The evaluator version changed after this review package was built. '
                          'Rebuild the review package and review against the current evaluator.')
    validate_review(review, scenario)
    record = dict(review)
    record.update({'label': label, 'phase': phase, 'submissionHash': current_hash,
                   'evaluatorVersion': current_version, 'reviewer': review['reviewer'],
                   'savedAt': experiment_module.now()})
    destination = exp_dir / 'results' / run['id'] / phase / 'review.json'
    if destination.exists():
        history = destination.parent / HISTORY_DIR
        history.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(destination, history / f'{time.time_ns()}.json')
    common.write(destination, record)
    run.setdefault('phases', {}).setdefault(phase, {})['review'] = record
    experiment_module.save(exp_dir, data)
    experiment_module.log(exp_dir, 'review_saved', run=run['id'], phase=phase, label=label)
    return record
