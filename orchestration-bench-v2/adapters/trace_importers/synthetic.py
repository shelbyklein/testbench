"""Importer for already-normalized `trace-event/1` JSONL fixtures.

Detection requires every non-empty line to be a trace-event/1 object, so this importer
never claims a provider transcript.
"""
import json
from pathlib import Path

from bench_core import traces
from adapters.trace_importers._redact import redact

NAME = 'synthetic'
VERSION = '1.0.0'


def _lines(path):
    with Path(path).open() as handle:
        for number, line in enumerate(handle, start=1):
            if line.strip():
                yield number, line


def detect(path):
    seen = 0
    for _, line in _lines(path):
        try:
            record = json.loads(line)
        except ValueError:
            return False
        if not isinstance(record, dict) or record.get('schema') != traces.SCHEMA:
            return False
        seen += 1
        if seen >= 200:
            break
    return seen > 0


def parse(path, run_id, experiment_id=None):
    path = Path(path)
    sha = traces.digest(path)
    # Reference the first line carrying each eventId, so a repeated line stays an exact
    # duplicate instead of becoming a false conflict on its position.
    first_line = {}
    for number, line in _lines(path):
        event_id = json.loads(line).get('eventId')
        first_line.setdefault(event_id, number)

    for number, line in _lines(path):
        event = traces.normalize_event(redact(json.loads(line)))
        event['runId'] = run_id or event['runId']
        if experiment_id is not None:
            event['experimentId'] = experiment_id
        event['synthetic'] = True
        evidence = dict(event.get('evidence') or {})
        evidence['ref'] = evidence.get('ref') or traces.evidence_ref(
            path, first_line.get(event['eventId'], number))
        evidence['sha256'] = sha
        evidence['importer'] = NAME
        evidence['importerVersion'] = VERSION
        event['evidence'] = evidence
        yield event
