"""Normalized trace events, store and importer dispatch (contracts/CONTRACTS.md §8).

The store is append-only JSONL on disk, written atomically and always re-serialized in
the deterministic order `(timestamp, nodeId, attempt, eventId)` so that the file content
does not depend on arrival order.
"""
import importlib
import json
import pkgutil
from pathlib import Path

from bench_core.common import ROOT, canonical, digest, require, validate_measurement

SCHEMA = 'trace-event/1'

ROLES = ('planner', 'worker', 'reviewer', 'integrator', 'orchestrator', 'solo', 'tool')
TYPES = ('node_declared', 'node_started', 'node_completed', 'node_failed', 'node_canceled',
         'node_skipped', 'artifact', 'usage', 'intervention', 'fault', 'restart', 'note')
TERMINAL_TYPES = {'node_completed': 'completed', 'node_failed': 'failed',
                  'node_canceled': 'canceled', 'node_skipped': 'skipped'}
#: worst-first, so a node that both failed and completed is never reported as a success
TERMINAL_PRIORITY = ('failed', 'canceled', 'skipped', 'completed')
STATUSES = ('ok', 'error', 'unknown')
CLOCK_SOURCES = ('provider', 'bench', 'transcript', 'synthetic')
USAGE_KEYS = ('inputTokens', 'outputTokens', 'costUSD', 'durationSeconds')
REQUIRED = ('schema', 'eventId', 'runId', 'nodeId', 'attempt', 'role', 'type', 'timestamp', 'status')


class TraceConflict(Exception):
    """Two events share an eventId but disagree on their payload."""


class ImporterError(Exception):
    """Zero or several importers claimed a file, or an importer produced nothing usable."""


class JoinResult(dict):
    """`{nodeId: status}` mapping; `join_ok` is true only when every node completed or was skipped."""

    @property
    def join_ok(self):
        return bool(self) and all(v in ('completed', 'skipped') for v in self.values())


def blank_event():
    return {
        'schema': SCHEMA, 'eventId': None, 'experimentId': None, 'runId': None, 'nodeId': None,
        'attempt': 1, 'parentId': None, 'dependsOn': [], 'role': None, 'type': None,
        'timestamp': None, 'clock': {'source': None, 'uncertaintySeconds': None}, 'status': 'unknown',
        'model': {'requested': None, 'effective': None, 'verified': False},
        'settings': {'requested': {}, 'effective': None, 'verified': False},
        'session': {'id': None, 'contextId': None, 'fresh': None},
        'sourceRevision': None,
        'artifacts': {'inputs': [], 'outputs': []},
        'usage': {'inputTokens': None, 'outputTokens': None, 'costUSD': None,
                  'durationSeconds': None, 'scope': 'self'},
        'evidence': {'ref': None, 'sha256': None, 'importer': None, 'importerVersion': None},
        'synthetic': False,
        'payload': {},
    }


def normalize_event(raw):
    """Fill every contract key from a partial event without inventing values."""
    event = blank_event()
    for key, value in (raw or {}).items():
        if isinstance(event.get(key), dict) and isinstance(value, dict):
            merged = dict(event[key])
            merged.update(value)
            event[key] = merged
        else:
            event[key] = value
    return event


def validate_event(event):
    """Raise ValueError unless `event` satisfies trace-event/1. Returns the event."""
    require(isinstance(event, dict), 'A trace event must be an object')
    for key in REQUIRED:
        require(key in event and event[key] is not None, f'Trace event requires a non-null {key}')
    require(event['schema'] == SCHEMA, f'Unknown trace schema: {event["schema"]}')
    require(event['role'] in ROLES, f'Unknown role: {event["role"]}')
    require(event['type'] in TYPES, f'Unknown event type: {event["type"]}')
    require(event['status'] in STATUSES, f'Unknown status: {event["status"]}')
    require(isinstance(event['attempt'], int) and event['attempt'] >= 1, 'attempt is a positive integer')
    require(isinstance(event['timestamp'], str) and event['timestamp'].strip(), 'timestamp must be a string')
    require(isinstance(event.get('dependsOn'), list), 'dependsOn must be a list')

    clock = event.get('clock') or {}
    require(isinstance(clock, dict), 'clock must be an object')
    if clock.get('source') is not None:
        require(clock['source'] in CLOCK_SOURCES, f'Unknown clock source: {clock["source"]}')

    evidence = event.get('evidence') or {}
    require(isinstance(evidence, dict), 'evidence must be an object')
    for key in ('importer', 'importerVersion'):
        value = evidence.get(key)
        require(isinstance(value, str) and value.strip(), f'Trace event requires a non-null evidence.{key}')

    artifacts = event.get('artifacts') or {}
    require(isinstance(artifacts, dict), 'artifacts must be an object')
    for side in ('inputs', 'outputs'):
        items = artifacts.get(side, [])
        require(isinstance(items, list), f'artifacts.{side} must be a list')
        for item in items:
            require(isinstance(item, dict) and 'path' in item, f'artifacts.{side} entries need a path')

    usage = event.get('usage') or {}
    require(isinstance(usage, dict), 'usage must be an object')
    require(usage.get('scope', 'self') in ('self', 'inclusive'), f'Unknown usage scope: {usage.get("scope")}')
    for key in USAGE_KEYS:
        value = usage.get(key)
        if value is not None:
            require(isinstance(value, dict), f'usage.{key} must be a measurement object or null')
            validate_measurement(value)
    return event


def sort_key(event):
    return (event['timestamp'], event['nodeId'], event['attempt'], event['eventId'])


class TraceStore:
    """JSONL-backed event store with idempotent import and deterministic ordering."""

    def __init__(self, path):
        self.path = Path(path)
        self._events = {}
        if self.path.exists():
            for line in self.path.read_text().splitlines():
                if line.strip():
                    event = validate_event(normalize_event(json.loads(line)))
                    self._events[event['eventId']] = event

    # -- writing ---------------------------------------------------------
    def add(self, events):
        """Add events. Identical re-import is a no-op; a same-id conflict raises TraceConflict."""
        if isinstance(events, dict):
            events = [events]
        added = duplicates = 0
        staged = dict(self._events)
        for raw in events:
            event = validate_event(normalize_event(raw))
            existing = staged.get(event['eventId'])
            if existing is None:
                staged[event['eventId']] = event
                added += 1
            elif canonical(existing) == canonical(event):
                duplicates += 1
            else:
                raise TraceConflict(
                    f'Conflicting payload for eventId {event["eventId"]!r} '
                    f'(run {event["runId"]!r}, node {event["nodeId"]!r})')
        self._events = staged
        if added:
            self._flush()
        return {'added': added, 'duplicates': duplicates}

    def _flush(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        body = ''.join(canonical(e) + '\n' for e in self.events())
        temp = self.path.with_suffix(self.path.suffix + '.tmp')
        temp.write_text(body)
        temp.replace(self.path)

    # -- reading ---------------------------------------------------------
    def events(self, run_id=None):
        rows = sorted(self._events.values(), key=sort_key)
        return [e for e in rows if run_id is None or e['runId'] == run_id]

    def __len__(self):
        return len(self._events)

    def runs(self):
        return sorted({e['runId'] for e in self._events.values()})

    def synthetic(self, run_id=None):
        rows = self.events(run_id)
        return bool(rows) and any(e.get('synthetic') for e in rows)

    # -- graphs ----------------------------------------------------------
    @staticmethod
    def _graph(events):
        nodes, edges = {}, set()
        for event in events:
            node = nodes.setdefault(event['nodeId'], {
                'nodeId': event['nodeId'], 'role': None, 'parentId': None,
                'dependsOn': [], 'attempts': set()})
            node['attempts'].add(event['attempt'])
            if node['role'] is None:
                node['role'] = event['role']
            if node['parentId'] is None and event.get('parentId'):
                node['parentId'] = event['parentId']
            for dep in event.get('dependsOn') or []:
                if dep not in node['dependsOn']:
                    node['dependsOn'].append(dep)
        for node in nodes.values():
            node['attempts'] = sorted(node['attempts'])
            node['dependsOn'] = sorted(node['dependsOn'])
            if node['parentId']:
                edges.add((node['parentId'], node['nodeId']))
            for dep in node['dependsOn']:
                edges.add((dep, node['nodeId']))
        return {'nodes': {k: nodes[k] for k in sorted(nodes)},
                'edges': [list(e) for e in sorted(edges)]}

    def declared_graph(self, run_id=None):
        """The graph the candidate said it would run (`node_declared` events only)."""
        return self._graph([e for e in self.events(run_id) if e['type'] == 'node_declared'])

    def observed_graph(self, run_id=None):
        """The graph actually observed (start and terminal events only)."""
        wanted = {'node_started'} | set(TERMINAL_TYPES)
        return self._graph([e for e in self.events(run_id) if e['type'] in wanted])

    # -- join ------------------------------------------------------------
    def join(self, expected_node_ids, run_id=None):
        """Account for every expected node; a failed or missing node never becomes a success."""
        events = self.events(run_id)
        started, terminal = set(), {}
        for event in events:
            if event['type'] == 'node_started':
                started.add(event['nodeId'])
            status = TERMINAL_TYPES.get(event['type'])
            if status is None:
                continue
            per_node = terminal.setdefault(event['nodeId'], {})
            per_node.setdefault(event['attempt'], []).append(status)

        result = JoinResult()
        for node_id in expected_node_ids:
            attempts = terminal.get(node_id)
            if attempts:
                last = max(attempts)
                statuses = attempts[last]
                result[node_id] = next(s for s in TERMINAL_PRIORITY if s in statuses)
            elif node_id in started:
                result[node_id] = 'running'
            else:
                result[node_id] = 'missing'
        return result

    # -- lineage ---------------------------------------------------------
    def lineage(self, node_id, run_id=None):
        """Attempts for one node with source revisions and artifact hashes.

        Each entry carries `stale` (its sourceRevision differs from the latest attempt's)
        and `reusedArtifactHashes` (hashes this attempt shares with an earlier attempt),
        so stale verdicts and reused artifacts are identifiable.
        """
        events = [e for e in self.events(run_id) if e['nodeId'] == node_id]
        by_attempt = {}
        for event in events:
            entry = by_attempt.setdefault(event['attempt'], {
                'nodeId': node_id, 'attempt': event['attempt'], 'sourceRevision': None,
                'status': 'running', 'startedAt': None, 'endedAt': None,
                'inputs': [], 'outputs': [], 'events': 0,
                'stale': False, 'reusedArtifactHashes': []})
            entry['events'] += 1
            if entry['sourceRevision'] is None and event.get('sourceRevision'):
                entry['sourceRevision'] = event['sourceRevision']
            if event['type'] == 'node_started' and entry['startedAt'] is None:
                entry['startedAt'] = event['timestamp']
            if event['type'] in TERMINAL_TYPES:
                candidate = TERMINAL_TYPES[event['type']]
                current = entry['status']
                pool = [candidate] + ([current] if current in TERMINAL_PRIORITY else [])
                entry['status'] = next(s for s in TERMINAL_PRIORITY if s in pool)
                entry['endedAt'] = event['timestamp']
            for side in ('inputs', 'outputs'):
                for item in (event.get('artifacts') or {}).get(side) or []:
                    if item not in entry[side]:
                        entry[side].append(item)

        attempts = [by_attempt[a] for a in sorted(by_attempt)]
        if attempts:
            latest = attempts[-1]['sourceRevision']
            seen = set()
            for entry in attempts:
                entry['stale'] = (latest is not None and entry['sourceRevision'] is not None
                                  and entry['sourceRevision'] != latest)
                hashes = {i['sha256'] for i in entry['inputs'] + entry['outputs'] if i.get('sha256')}
                entry['reusedArtifactHashes'] = sorted(hashes & seen)
                seen |= hashes
        return attempts


# -- importer dispatch ---------------------------------------------------
def available_importers(package='adapters.trace_importers'):
    module = importlib.import_module(package)
    found = []
    for info in sorted(pkgutil.iter_modules(module.__path__), key=lambda i: i.name):
        if info.name.startswith('_'):
            continue
        found.append(importlib.import_module(f'{package}.{info.name}'))
    return found


def detect_importer(path, importers=None):
    """Return the single importer whose `detect` accepts `path`; zero or several is an error."""
    path = Path(path)
    require(path.is_file(), f'No such trace file: {path}')
    matches = []
    for importer in (importers if importers is not None else available_importers()):
        try:
            if importer.detect(path):
                matches.append(importer)
        except Exception:  # a detector must never decide by crashing
            continue
    if not matches:
        raise ImporterError(f'No importer recognized {path.name}; formats are detected, never guessed')
    if len(matches) > 1:
        names = ', '.join(sorted(i.NAME for i in matches))
        raise ImporterError(f'Several importers claim {path.name}: {names}')
    return matches[0]


def import_file(path, run_id, experiment_id=None, store=None, importers=None):
    """Detect the format of `path`, parse it and (optionally) add it to `store`.

    Returns `{"importer", "importerVersion", "path", "sha256", "events", "added", "duplicates"}`.
    `added`/`duplicates` are null when no store was supplied.
    """
    path = Path(path)
    importer = detect_importer(path, importers)
    events = [validate_event(normalize_event(e))
              for e in importer.parse(path, run_id, experiment_id)]
    result = {'importer': importer.NAME, 'importerVersion': importer.VERSION,
              'path': str(path), 'sha256': digest(path), 'events': events,
              'added': None, 'duplicates': None}
    if store is not None:
        result.update(store.add(events))
    return result


def evidence_ref(path, line_number):
    """A repo-relative `path#Ln` reference when possible, otherwise the file name."""
    path = Path(path)
    try:
        ref = str(path.resolve().relative_to(ROOT))
    except ValueError:
        ref = path.name
    return f'{ref}#L{line_number}'
