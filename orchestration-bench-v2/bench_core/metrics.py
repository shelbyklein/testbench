"""Effort and recovery analysis over imported traces (contracts/CONTRACTS.md §8).

Two entry points:

* `analyze(store, run) -> report` — one run's effort, reconciled against an imported total.
* `compare(experiment, reports) -> comparison` — paired outcomes across runs.

Neither invents a cost, fills an unknown with zero, or declares a winner.
"""
from datetime import datetime

from bench_core import traces
from bench_core.common import measurement, total

REPORT_CONTRACT = 'metrics-report/1'
COMPARISON_CONTRACT = 'metrics-comparison/1'
ROLE_BUCKETS = ('planner', 'worker', 'reviewer', 'integrator', 'orchestrator', 'solo', 'retry')
SERIOUS = ('serious', 'critical', 'blocker', 'major')
USAGE_UNITS = {'inputTokens': 'tokens', 'outputTokens': 'tokens',
               'costUSD': 'usd', 'durationSeconds': 'seconds'}


# -- helpers -------------------------------------------------------------
def _parse_time(value):
    try:
        if isinstance(value, str) and value.endswith('Z'):
            value = value[:-1] + '+00:00'
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _union(intervals):
    """Union of [start, end] seconds; overlapping intervals are never added twice."""
    ordered = sorted(intervals)
    merged = []
    for start, end in ordered:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return merged


def _span(merged):
    return sum(end - start for start, end in merged)


def _aggregate(measurements, unit, source):
    """common.total, re-expressed so consumers always see incompleteness."""
    result = total(measurements)
    result['unit'] = unit
    result['source'] = source if result['value'] is not None else None
    return result


def _empty_usage(source):
    return {key: _aggregate([], USAGE_UNITS[key], source) for key in USAGE_UNITS}


def _ancestors(parent_of, node_id):
    seen, current = [], parent_of.get(node_id)
    while current and current not in seen:
        seen.append(current)
        current = parent_of.get(current)
    return seen


# -- analyze -------------------------------------------------------------
def analyze(store, run):
    """Per-run effort report. `run` is an `ob2-experiment/1` run dict (§7)."""
    run_id = run['id'] if isinstance(run, dict) else run
    run = run if isinstance(run, dict) else {'id': run_id}
    events = store.events(run_id)
    source = f'trace:{run_id}'
    issues = []       # trace defects: the record is incomplete or self-contradictory
    usage_notes = []  # correct-by-design exclusions, e.g. an inclusive parent covering its children

    parent_of = {}
    role_of = {}
    for event in events:
        if event.get('parentId') and event['nodeId'] not in parent_of:
            parent_of[event['nodeId']] = event['parentId']
        role_of.setdefault(event['nodeId'], event['role'])

    # -- usage, with inclusive parents never added to their children -----
    usage_events = [e for e in events if e['type'] == 'usage']
    run_totals = [e for e in usage_events if (e.get('payload') or {}).get('runTotal')]
    node_usage = [e for e in usage_events if e not in run_totals]
    inclusive_nodes = {e['nodeId'] for e in node_usage if (e.get('usage') or {}).get('scope') == 'inclusive'}

    buckets = {role: {key: [] for key in USAGE_UNITS} for role in ROLE_BUCKETS}
    bucket_nodes = {role: set() for role in ROLE_BUCKETS}
    counted = 0
    for event in node_usage:
        node_id = event['nodeId']
        covering = [a for a in _ancestors(parent_of, node_id) if a in inclusive_nodes]
        if covering:
            usage_notes.append(f'usage for {node_id} is already inside inclusive parent {covering[0]}')
            continue
        if node_id in inclusive_nodes and (event['usage'] or {}).get('scope') != 'inclusive':
            usage_notes.append(f'self usage for {node_id} dropped: an inclusive total exists for the same node')
            continue
        bucket = 'retry' if event['attempt'] > 1 else (event['role'] if event['role'] in buckets else 'worker')
        counted += 1
        bucket_nodes[bucket].add(node_id)
        for key in USAGE_UNITS:
            buckets[bucket][key].append((event['usage'] or {}).get(key))

    roles = {}
    for role in ROLE_BUCKETS:
        if not bucket_nodes[role]:
            continue
        roles[role] = {key: _aggregate(buckets[role][key], USAGE_UNITS[key], source) for key in USAGE_UNITS}
        roles[role]['nodes'] = sorted(bucket_nodes[role])
        roles[role]['events'] = len(buckets[role]['inputTokens'])

    role_sum = {key: _aggregate([m for role in ROLE_BUCKETS for m in buckets[role][key]],
                                USAGE_UNITS[key], source) for key in USAGE_UNITS} if counted else _empty_usage(source)

    reconciliation = _reconcile(run_totals, role_sum, source)

    # -- time ------------------------------------------------------------
    intervals, open_nodes, uncertainties, clock_sources = [], [], [], set()
    starts = {}
    for event in events:
        moment = _parse_time(event['timestamp'])
        clock = event.get('clock') or {}
        if clock.get('source'):
            clock_sources.add(clock['source'])
        if clock.get('uncertaintySeconds') is not None:
            uncertainties.append(clock['uncertaintySeconds'])
        if moment is None:
            issues.append(f'unparsable timestamp on event {event["eventId"]}')
            continue
        key = (event['nodeId'], event['attempt'])
        if event['type'] == 'node_started':
            starts.setdefault(key, (moment, event['role']))
        elif event['type'] in traces.TERMINAL_TYPES:
            if key in starts:
                begin, role = starts.pop(key)
                intervals.append((begin.timestamp(), moment.timestamp(), key[0], key[1], role))
            elif event['type'] != 'node_skipped':
                issues.append(f'{event["nodeId"]} attempt {event["attempt"]} ended without a start')
    for (node_id, attempt) in sorted(starts):
        open_nodes.append(node_id)
        issues.append(f'{node_id} attempt {attempt} started and never ended')

    merged = _union([(a, b) for a, b, *_ in intervals])
    wall_complete = bool(intervals) and not open_nodes
    wall_value = _span(merged) if wall_complete else None
    wall = {
        'seconds': measurement(wall_value, 'seconds', source=source) if wall_value is not None
        else measurement(None, 'seconds'),
        'method': 'interval-union',
        'sumOfDurationsSeconds': sum(b - a for a, b, *_ in intervals) if intervals else None,
        'intervals': len(intervals),
        'openIntervals': sorted(set(open_nodes)),
        'clockSources': sorted(clock_sources),
        'clockUncertaintySeconds': max(uncertainties) if uncertainties else None,
    }

    def bucket_seconds(predicate):
        chosen = [(a, b) for a, b, node, attempt, role in intervals if predicate(node, attempt, role)]
        if not chosen:
            return measurement(None, 'seconds')
        return measurement(_span(_union(chosen)), 'seconds', source=source)

    busy = _span(merged) if intervals else None
    outer = (min(a for a, b, *_ in intervals), max(b for a, b, *_ in intervals)) if intervals else None
    waiting = None if outer is None else max(0.0, (outer[1] - outer[0]) - busy)

    overhead = {
        'waitingSeconds': measurement(waiting, 'seconds', source=source) if waiting is not None
        else measurement(None, 'seconds'),
        'integrationSeconds': bucket_seconds(lambda n, a, r: r == 'integrator'),
        'retrySeconds': bucket_seconds(lambda n, a, r: a > 1),
        'measured': bool(intervals),
        'note': 'waiting = span between first start and last end not covered by any node interval',
    }

    # -- graphs, join, lineage ------------------------------------------
    declared = store.declared_graph(run_id)
    observed = store.observed_graph(run_id)
    expected = run.get('expectedNodes') or sorted(declared['nodes']) or sorted(observed['nodes'])
    joined = store.join(expected, run_id)
    declared_only = sorted(set(declared['nodes']) - set(observed['nodes']))
    observed_only = sorted(set(observed['nodes']) - set(declared['nodes']))
    edge_delta = sorted({tuple(e) for e in declared['edges']} ^ {tuple(e) for e in observed['edges']})

    retried = sorted({e['nodeId'] for e in events if e['attempt'] > 1})
    lineage = {node_id: store.lineage(node_id, run_id) for node_id in sorted(observed['nodes'])}
    stale = sorted({n for n, entries in lineage.items() if any(a['stale'] for a in entries)})
    reused = sorted({n for n, entries in lineage.items() if any(a['reusedArtifactHashes'] for a in entries)})

    missing = [n for n, s in joined.items() if s == 'missing']
    failed = [n for n, s in joined.items() if s == 'failed']
    if missing:
        issues.append(f'declared but never observed: {", ".join(missing)}')

    critical_path = _critical_path(declared, observed, intervals, joined, source)

    interventions = [e for e in events if e['type'] == 'intervention']
    faults = [e for e in events if e['type'] in ('fault', 'restart')]

    complete = bool(events) and not issues and reconciliation['status'] == 'matches' \
        and role_sum['inputTokens']['complete'] and wall_complete

    return {
        'contract': REPORT_CONTRACT,
        'runId': run_id,
        'scenario': run.get('scenario'),
        'scenarioVersion': run.get('scenarioVersion'),
        'method': run.get('method'),
        'repeat': run.get('repeat'),
        'pairKey': run.get('pairKey'),
        'synthetic': store.synthetic(run_id),
        'eventCount': len(events),
        'roles': roles,
        'usageTotals': role_sum,
        'reconciliation': reconciliation,
        'wallTime': wall,
        'overhead': overhead,
        'retries': {'nodes': retried, 'attempts': max([e['attempt'] for e in events], default=0)},
        'criticalPath': critical_path,
        'interventions': {'count': len(interventions),
                          'events': [{'nodeId': e['nodeId'], 'timestamp': e['timestamp'],
                                      'kind': (e.get('payload') or {}).get('kind')} for e in interventions]},
        'faults': {'count': len(faults),
                   'events': [{'nodeId': e['nodeId'], 'type': e['type'], 'timestamp': e['timestamp']}
                              for e in faults]},
        'join': {'expected': list(expected), 'status': dict(joined), 'joinOk': joined.join_ok,
                 'missing': missing, 'failed': failed,
                 'skipped': [n for n, s in joined.items() if s == 'skipped'],
                 'forcedSkips': list(joined.forced_skips),
                 'running': [n for n, s in joined.items() if s == 'running']},
        'graphs': {'declared': declared, 'observed': observed,
                   'declaredOnly': declared_only, 'observedOnly': observed_only,
                   'edgeDifferences': [list(e) for e in edge_delta],
                   'deviated': bool(declared_only or observed_only or edge_delta)},
        'lineage': lineage,
        'staleRevisionNodes': stale,
        'reusedArtifactNodes': reused,
        'trace': {'complete': not issues and bool(events), 'issues': issues, 'usageNotes': usage_notes},
        'complete': complete,
    }


def _reconcile(run_totals, role_sum, source):
    """Compare the sum of role usage with an imported run total."""
    if not run_totals:
        return {'status': 'unknown', 'imported': None, 'roleSum': role_sum,
                'differences': {}, 'detail': 'no imported run total event (payload.runTotal) in the trace'}
    if len(run_totals) > 1:
        return {'status': 'unknown', 'imported': None, 'roleSum': role_sum, 'differences': {},
                'detail': f'{len(run_totals)} conflicting run-total events; not reconciled'}

    imported = (run_totals[0].get('usage') or {})
    differences, statuses = {}, []
    for key in USAGE_UNITS:
        got = role_sum[key]
        want = imported.get(key) or {}
        if not got['complete'] or want.get('value') is None:
            differences[key] = None
            statuses.append('unknown')
            continue
        delta = round(got['value'] - want['value'], 9)
        differences[key] = delta
        statuses.append('matches' if delta == 0 else 'mismatch')
    status = 'mismatch' if 'mismatch' in statuses else ('unknown' if 'unknown' in statuses else 'matches')
    return {
        'status': status,
        'imported': {key: imported.get(key) for key in USAGE_UNITS},
        'importedScope': imported.get('scope'),
        'roleSum': role_sum,
        'differences': differences,
        'detail': {'matches': 'role usage sums to the imported run total',
                   'mismatch': 'role usage does not sum to the imported run total',
                   'unknown': 'reconciliation incomplete: an unknown measurement on one side'}[status],
    }


def _critical_path(declared, observed, intervals, joined, source):
    """Longest dependency path, only when the graph and every interval support it."""
    graph = declared if declared['nodes'] else observed
    if not graph['nodes']:
        return {'nodes': None, 'seconds': measurement(None, 'seconds'), 'supported': False,
                'reason': 'no declared or observed graph'}
    if not graph['edges']:
        return {'nodes': None, 'seconds': measurement(None, 'seconds'), 'supported': False,
                'reason': 'no dependency edges: a critical path would be invented'}

    duration = {}
    for start, end, node_id, _attempt, _role in intervals:
        duration[node_id] = duration.get(node_id, 0.0) + (end - start)
    unmeasured = sorted(set(graph['nodes']) - set(duration))
    if unmeasured:
        return {'nodes': None, 'seconds': measurement(None, 'seconds'), 'supported': False,
                'reason': f'no measured interval for: {", ".join(unmeasured)}'}
    unfinished = sorted(n for n, s in joined.items() if s in ('running', 'missing'))
    if unfinished:
        return {'nodes': None, 'seconds': measurement(None, 'seconds'), 'supported': False,
                'reason': f'unfinished nodes at the join: {", ".join(unfinished)}'}

    incoming = {node: [] for node in graph['nodes']}
    for a, b in graph['edges']:
        if a in incoming and b in incoming:
            incoming[b].append(a)

    best, path, visiting = {}, {}, set()

    def longest(node):
        if node in best:
            return best[node]
        if node in visiting:
            return None
        visiting.add(node)
        chosen, chosen_value = None, 0.0
        for pred in incoming[node]:
            value = longest(pred)
            if value is None:
                visiting.discard(node)
                return None
            if value > chosen_value or chosen is None:
                chosen, chosen_value = pred, value
        visiting.discard(node)
        best[node] = chosen_value + duration[node]
        path[node] = chosen
        return best[node]

    for node in graph['nodes']:
        if longest(node) is None:
            return {'nodes': None, 'seconds': measurement(None, 'seconds'), 'supported': False,
                    'reason': 'dependency cycle in the graph'}

    end_node = max(sorted(best), key=lambda n: best[n])
    chain, cursor = [], end_node
    while cursor is not None:
        chain.append(cursor)
        cursor = path.get(cursor)
    return {'nodes': list(reversed(chain)),
            'seconds': measurement(round(best[end_node], 6), 'seconds', source=source),
            'supported': True, 'reason': None}


# -- compare -------------------------------------------------------------
def _phase_outcome(run, phase):
    data = (run.get('phases') or {}).get(phase) or {}
    evaluation = data.get('evaluation')
    accepted = evaluation.get('allPassed') if isinstance(evaluation, dict) else None
    review = None if data.get('reviewCurrent') is False else data.get('review')  # stale reviews judged other code
    defects = ((review or {}).get('defects')) or []
    serious = [d for d in defects if str(d.get('severity', '')).lower() in SERIOUS]
    return {'accepted': accepted if isinstance(accepted, bool) else None,
            'evaluated': isinstance(evaluation, dict) and 'allPassed' in evaluation,
            'defects': len(defects), 'seriousDefects': len(serious),
            'reviewed': bool(review), 'staleReview': data.get('reviewCurrent') is False}


def compare(experiment, reports):
    """Paired outcomes and effort across an `ob2-experiment/1` experiment. Never picks a winner."""
    if isinstance(reports, dict):
        by_run = dict(reports)
    else:
        by_run = {r['runId']: r for r in (reports or [])}

    runs = list((experiment or {}).get('runs') or [])
    phases = list((experiment or {}).get('definition', {}).get('phases') or ['first', 'repaired'])
    methods = sorted({r.get('method') for r in runs if r.get('method')})

    rows, incomplete = [], []
    per_method = {m: {'runs': 0, 'phases': {}, 'usage': {k: [] for k in USAGE_UNITS},
                      'wallSeconds': [], 'interventions': 0, 'tracedRuns': 0,
                      'reconciliation': {'matches': 0, 'mismatch': 0, 'unknown': 0, 'absent': 0}}
                  for m in methods}

    for run in runs:
        method = run.get('method')
        report = by_run.get(run.get('id'))
        bucket = per_method.setdefault(method, {'runs': 0, 'phases': {}, 'usage': {k: [] for k in USAGE_UNITS},
                                                'wallSeconds': [], 'interventions': 0, 'tracedRuns': 0,
                                                'reconciliation': {'matches': 0, 'mismatch': 0,
                                                                   'unknown': 0, 'absent': 0}})
        bucket['runs'] += 1
        if report is None:
            bucket['reconciliation']['absent'] += 1
            incomplete.append({'runId': run.get('id'), 'reason': 'no imported trace'})
        else:
            bucket['tracedRuns'] += 1
            bucket['reconciliation'][report['reconciliation']['status']] += 1
            for key in USAGE_UNITS:
                aggregate = report['usageTotals'][key]
                bucket['usage'][key].append(aggregate['value'] if aggregate['complete'] else None)
            bucket['wallSeconds'].append(report['wallTime']['seconds']['value'])
            bucket['interventions'] += report['interventions']['count']
            if not report['complete']:
                incomplete.append({'runId': run.get('id'),
                                   'reason': '; '.join(report['trace']['issues'])
                                   or f'reconciliation {report["reconciliation"]["status"]}'})

        for phase in phases:
            outcome = _phase_outcome(run, phase)
            slot = bucket['phases'].setdefault(phase, {'runs': 0, 'evaluated': 0, 'accepted': 0,
                                                       'seriousDefects': 0, 'runsWithSeriousDefects': 0,
                                                       'reviewed': 0})
            slot['runs'] += 1
            slot['evaluated'] += int(outcome['evaluated'])
            slot['accepted'] += int(outcome['accepted'] is True)
            slot['seriousDefects'] += outcome['seriousDefects']
            slot['runsWithSeriousDefects'] += int(outcome['seriousDefects'] > 0)
            slot['reviewed'] += int(outcome['reviewed'])
            rows.append({
                'runId': run.get('id'), 'scenario': run.get('scenario'),
                'scenarioVersion': run.get('scenarioVersion'), 'method': method,
                'repeat': run.get('repeat'), 'pairKey': run.get('pairKey'), 'phase': phase,
                'accepted': outcome['accepted'], 'evaluated': outcome['evaluated'],
                'seriousDefects': outcome['seriousDefects'], 'defects': outcome['defects'],
                'wallSeconds': report['wallTime']['seconds']['value'] if report else None,
                'inputTokens': report['usageTotals']['inputTokens'] if report else None,
                'outputTokens': report['usageTotals']['outputTokens'] if report else None,
                'costUSD': report['usageTotals']['costUSD'] if report else None,
                'interventions': report['interventions']['count'] if report else None,
                'traceComplete': report['complete'] if report else False,
            })

    for method, bucket in per_method.items():
        source = f'runs:{method}'
        bucket['usage'] = {key: _aggregate(
            [measurement(v, USAGE_UNITS[key], source=source) if v is not None
             else measurement(None, USAGE_UNITS[key]) for v in bucket['usage'][key]],
            USAGE_UNITS[key], source) for key in USAGE_UNITS}
        bucket['wallTimeSeconds'] = _aggregate(
            [measurement(v, 'seconds', source=source) if v is not None else measurement(None, 'seconds')
             for v in bucket['wallSeconds']], 'seconds', source)
        bucket.pop('wallSeconds')
        bucket['complete'] = (bucket['tracedRuns'] == bucket['runs'] and bucket['runs'] > 0
                              and all(bucket['usage'][k]['complete'] for k in USAGE_UNITS)
                              and bucket['wallTimeSeconds']['complete'])

    paired = _pairs(runs, phases)
    variation = _variation(runs)

    return {
        'contract': COMPARISON_CONTRACT,
        'experimentId': (experiment or {}).get('definition', {}).get('id'),
        'format': (experiment or {}).get('format'),
        'synthetic': any(r.get('synthetic') for r in by_run.values()) if by_run else None,
        'phases': phases,
        'methods': per_method,
        'paired': paired['comparisons'],
        'pairedSummary': paired['summary'],
        'unpaired': paired['unpaired'],
        'rows': sorted(rows, key=lambda r: (r['scenario'] or '', r['repeat'] or 0,
                                            r['method'] or '', r['phase'])),
        'variation': variation,
        'incompleteTraces': incomplete,
        'complete': all(b['complete'] for b in per_method.values()) and bool(per_method) and not incomplete,
        'compositeScore': None,
        'winner': None,
        'winnerPolicy': 'not computed',
    }


def _pairs(runs, phases):
    """Paired wins/losses/ties by pairKey and phase; first and repaired stay separate."""
    groups = {}
    for run in runs:
        key = run.get('pairKey')
        if key is None:
            continue
        for phase in phases:
            groups.setdefault((key, phase), []).append(run)

    comparisons, unpaired = [], []
    summary = {}
    for (pair_key, phase) in sorted(groups):
        members = sorted(groups[(pair_key, phase)], key=lambda r: r.get('method') or '')
        outcomes = {r.get('method'): _phase_outcome(r, phase) for r in members}
        if len(members) < 2:
            unpaired.append({'pairKey': pair_key, 'phase': phase,
                             'methods': sorted(outcomes), 'reason': 'no partner run for this pairKey and phase'})
            continue
        for i, left in enumerate(members):
            for right in members[i + 1:]:
                a, b = left.get('method'), right.get('method')
                oa, ob = outcomes[a], outcomes[b]
                if oa['accepted'] is None or ob['accepted'] is None:
                    result, winner = 'incomplete', None
                elif oa['accepted'] == ob['accepted']:
                    result, winner = 'tie', None
                else:
                    result = 'win'
                    winner = a if oa['accepted'] else b
                comparisons.append({
                    'pairKey': pair_key, 'phase': phase, 'methods': [a, b],
                    'accepted': {a: oa['accepted'], b: ob['accepted']},
                    'seriousDefects': {a: oa['seriousDefects'], b: ob['seriousDefects']},
                    'result': result, 'acceptanceWinner': winner,
                    'basis': 'evaluation.allPassed for this phase',
                })
                for one, other in ((a, b), (b, a)):
                    slot = summary.setdefault(one, {}).setdefault(other, {
                        'wins': 0, 'losses': 0, 'ties': 0, 'incomplete': 0})
                    if result == 'tie':
                        slot['ties'] += 1
                    elif result == 'incomplete':
                        slot['incomplete'] += 1
                    elif winner == one:
                        slot['wins'] += 1
                    else:
                        slot['losses'] += 1
    return {'comparisons': comparisons, 'summary': summary, 'unpaired': unpaired}


def _variation(runs):
    """Task-level and repeat-level variation, kept apart on purpose."""
    scenarios = sorted({r.get('scenario') for r in runs if r.get('scenario')})
    repeats_by_scenario = {}
    for run in runs:
        if run.get('scenario'):
            repeats_by_scenario.setdefault(run['scenario'], set()).add(run.get('repeat'))
    return {
        'taskLevel': {'distinctTasks': len(scenarios), 'scenarios': scenarios,
                      'note': 'task diversity is the number of distinct scenarios'},
        'repeatLevel': {'repeatsByScenario': {k: len(v) for k, v in sorted(repeats_by_scenario.items())},
                        'totalRepeatRuns': len(runs),
                        'note': 'repeats of one task measure run-to-run variation, not task diversity'},
    }
