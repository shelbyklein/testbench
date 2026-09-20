"""Importer for Claude Code session transcripts (`~/.claude/projects/<slug>/<session>.jsonl`).

The real transcript is one JSON object per line. Records carry `uuid`, `parentUuid`,
`timestamp`, `sessionId`, `cwd`, `version`, `gitBranch` and `type`; `assistant` records
carry `message.model`, `message.usage` and a `message.content` block list (`text`,
`thinking`, `tool_use`, `tool_result`, `image`); subagent turns carry `isSidechain: true`
and hang off the main chain through `parentUuid`. Housekeeping line types
(`file-history-snapshot`, `queue-operation`, `summary`, …) are ignored.

What is deliberately *not* imported: assistant `thinking`/reasoning text, `text` bodies,
tool inputs and tool results. Only structural metadata and token counts are kept, and
every retained string passes through redaction.
"""
import hashlib
import json
from pathlib import Path

from bench_core import traces
from bench_core.common import measurement
from adapters.trace_importers._redact import redact

NAME = 'claude_jsonl'
VERSION = '1.0.0'

TURN_TYPES = ('user', 'assistant')
MAIN_NODE = 'main'


def _records(path):
    with Path(path).open() as handle:
        for number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if isinstance(record, dict):
                yield number, record


def detect(path):
    """True for a Claude Code transcript: structural, not name-based."""
    turns = 0
    for _, record in _records(path):
        if record.get('schema') == traces.SCHEMA:
            return False  # already-normalized trace, not a transcript
        if record.get('type') in TURN_TYPES and isinstance(record.get('message'), dict):
            if record.get('uuid') and record.get('timestamp') and record.get('sessionId'):
                turns += 1
    return turns > 0


def _timestamp(value):
    """Transcripts use `...Z`; the normalized schema uses an explicit offset."""
    if isinstance(value, str) and value.endswith('Z'):
        return value[:-1] + '+00:00'
    return value


def _blocks(record):
    content = (record.get('message') or {}).get('content')
    return [b for b in content if isinstance(b, dict)] if isinstance(content, list) else []


def _tokens(usage, *keys):
    """Sum the given usage keys; unknown stays null, never 0."""
    if not isinstance(usage, dict):
        return None
    values = [usage.get(k) for k in keys]
    known = [v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]
    return sum(known) if known else None


def _node_ids(turns):
    """Map each turn uuid to a node: the main chain, or one node per sidechain root."""
    by_uuid = {r['uuid']: r for _, r in turns if r.get('uuid')}
    nodes = {}

    def resolve(uuid, seen=None):
        seen = seen or set()
        if uuid in nodes:
            return nodes[uuid]
        record = by_uuid.get(uuid)
        if record is None or not record.get('isSidechain'):
            return MAIN_NODE
        parent = record.get('parentUuid')
        if parent and parent in by_uuid and by_uuid[parent].get('isSidechain') and parent not in seen:
            node = resolve(parent, seen | {uuid})
        else:
            node = 'subagent-' + hashlib.sha256(uuid.encode()).hexdigest()[:8]
        nodes[uuid] = node
        return node

    return {uuid: resolve(uuid) for uuid in by_uuid}


def parse(path, run_id, experiment_id=None):
    path = Path(path)
    sha = traces.digest(path)
    # A real transcript re-emits some records for the same `uuid` with only incidental
    # metadata differing. One uuid is one turn: keep the first and never count it twice.
    turns, seen_uuids = [], set()
    for number, record in _records(path):
        if record.get('type') not in TURN_TYPES or not isinstance(record.get('message'), dict):
            continue
        uuid = record.get('uuid')
        if not uuid or uuid in seen_uuids:
            continue
        seen_uuids.add(uuid)
        turns.append((number, record))
    if not turns:
        return

    node_of = _node_ids(turns)
    has_subagents = any(node != MAIN_NODE for node in node_of.values())
    session_id = redact(str(turns[0][1].get('sessionId') or '')) or None
    prefix = f'{session_id[:8]}' if session_id else 'session'

    def base(number, record, node_id, suffix, event_type, role, status='ok'):
        event = traces.normalize_event({
            'eventId': f'{prefix}-{record["uuid"]}-{suffix}',
            'experimentId': experiment_id,
            'runId': run_id,
            'nodeId': node_id,
            'attempt': 1,
            'parentId': None if node_id == MAIN_NODE else MAIN_NODE,
            'role': role,
            'type': event_type,
            'timestamp': _timestamp(record.get('timestamp')),
            'clock': {'source': 'transcript', 'uncertaintySeconds': None},
            'status': status,
            'session': {'id': session_id, 'contextId': redact(str(record.get('sessionId') or '')) or None,
                        'fresh': None},
            'evidence': {'ref': traces.evidence_ref(path, number), 'sha256': sha,
                         'importer': NAME, 'importerVersion': VERSION},
            'synthetic': False,
            'payload': {},
        })
        return event

    # -- node spans ------------------------------------------------------
    spans = {}
    for number, record in turns:
        node_id = node_of[record['uuid']]
        span = spans.setdefault(node_id, {'first': (number, record), 'last': (number, record)})
        if record.get('timestamp', '') < span['first'][1].get('timestamp', ''):
            span['first'] = (number, record)
        if record.get('timestamp', '') >= span['last'][1].get('timestamp', ''):
            span['last'] = (number, record)

    for node_id in sorted(spans):
        role = 'worker' if node_id != MAIN_NODE else ('orchestrator' if has_subagents else 'solo')
        number, record = spans[node_id]['first']
        started = base(number, record, node_id, 'started', 'node_started', role)
        started['payload'] = {'branch': redact(record.get('gitBranch')) or None,
                              'cliVersion': redact(record.get('version')) or None,
                              'workspace': redact(record.get('cwd')) or None}
        yield started
        number, record = spans[node_id]['last']
        yield base(number, record, node_id, 'completed', 'node_completed', role)

    # -- per-turn events -------------------------------------------------
    totals = {'inputTokens': [], 'outputTokens': []}
    human_turns = 0
    for number, record in turns:
        node_id = node_of[record['uuid']]
        role = 'worker' if node_id != MAIN_NODE else ('orchestrator' if has_subagents else 'solo')
        blocks = _blocks(record)

        if record['type'] == 'assistant':
            usage = (record.get('message') or {}).get('usage')
            model = redact((record.get('message') or {}).get('model'))
            source = f'{NAME} {traces.evidence_ref(path, number)}'
            input_tokens = _tokens(usage, 'input_tokens', 'cache_read_input_tokens',
                                   'cache_creation_input_tokens')
            output_tokens = _tokens(usage, 'output_tokens')
            event = base(number, record, node_id, 'usage', 'usage', role)
            event['model'] = {'requested': None, 'effective': model or None,
                              'verified': bool(model)}
            event['usage'] = {
                'inputTokens': measurement(input_tokens, 'tokens', source=source) if input_tokens is not None
                else measurement(None, 'tokens'),
                'outputTokens': measurement(output_tokens, 'tokens', source=source) if output_tokens is not None
                else measurement(None, 'tokens'),
                # the transcript records no price and no per-turn wall clock
                'costUSD': measurement(None, 'usd'),
                'durationSeconds': measurement(None, 'seconds'),
                'scope': 'self'}
            totals['inputTokens'].append(input_tokens)
            totals['outputTokens'].append(output_tokens)
            yield event

            for index, block in enumerate(b for b in blocks if b.get('type') == 'tool_use'):
                note = base(number, record, node_id, f'tool{index}', 'note', 'tool')
                note['payload'] = {'tool': redact(block.get('name')), 'toolUseId': block.get('id')}
                yield note
            continue

        # user turns: a real human prompt, or a tool result echoed back
        if any(b.get('type') == 'tool_result' for b in blocks):
            continue
        if node_id != MAIN_NODE:
            continue  # a subagent's prompt is delegation, not a human intervention
        human_turns += 1
        if human_turns == 1:
            continue  # the opening prompt is the task, not an intervention
        event = base(number, record, node_id, 'intervention', 'intervention', role)
        event['payload'] = {'kind': 'human_prompt'}
        yield event

    # -- imported run total (inclusive; reconciliation compares role sums to it) --
    last_number, last_record = max(turns, key=lambda t: t[1].get('timestamp', ''))
    source = f'{NAME} {path.name}'

    def agg(values):
        known = [v for v in values if v is not None]
        if not known or len(known) != len(values):
            return measurement(None, 'tokens')
        return measurement(sum(known), 'tokens', source=source)

    total_event = base(last_number, last_record, '__run__', 'runtotal', 'usage', 'orchestrator')
    total_event['eventId'] = f'{prefix}-runtotal'
    total_event['parentId'] = None
    total_event['usage'] = {'inputTokens': agg(totals['inputTokens']),
                            'outputTokens': agg(totals['outputTokens']),
                            'costUSD': measurement(None, 'usd'),
                            'durationSeconds': measurement(None, 'seconds'),
                            'scope': 'inclusive'}
    total_event['payload'] = {'runTotal': True, 'turns': len(turns)}
    yield total_event
