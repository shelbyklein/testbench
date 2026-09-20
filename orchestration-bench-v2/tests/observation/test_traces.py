"""Behavior of the trace store and the importers (contracts/CONTRACTS.md §8)."""
import json
import random
import tempfile
import unittest
from pathlib import Path

from adapters.trace_importers import claude_jsonl, synthetic
from adapters.trace_importers._redact import redact
from bench_core import traces

FIXTURES = Path(__file__).resolve().parent / 'fixtures'


class TraceTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store_path = Path(self.tmp.name) / 'trace.jsonl'

    def store(self):
        return traces.TraceStore(self.store_path)

    def load(self, name, run_id, store=None):
        return traces.import_file(FIXTURES / name, run_id, 'exp-demo',
                                  self.store() if store is None else store)


class ValidationTests(TraceTestCase):
    def minimal(self, **kw):
        event = traces.normalize_event({
            'eventId': 'e1', 'runId': 'run-1', 'nodeId': 'n1', 'role': 'worker',
            'type': 'node_started', 'timestamp': '2026-09-20T12:00:00+00:00', 'status': 'ok',
            'evidence': {'importer': 'synthetic', 'importerVersion': '1.0.0'}})
        event.update(kw)
        return event

    def test_accepts_a_minimal_event(self):
        event = self.minimal()
        self.assertIs(traces.validate_event(event), event)

    def test_rejects_missing_required_field(self):
        for field in ('eventId', 'runId', 'nodeId', 'role', 'type', 'timestamp', 'status'):
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    traces.validate_event(self.minimal(**{field: None}))

    def test_rejects_unknown_enums_and_bad_importer_stamp(self):
        with self.assertRaises(ValueError):
            traces.validate_event(self.minimal(role='chef'))
        with self.assertRaises(ValueError):
            traces.validate_event(self.minimal(type='node_vibed'))
        with self.assertRaises(ValueError):
            traces.validate_event(self.minimal(evidence={'importer': 'x', 'importerVersion': None}))

    def test_rejects_zero_dressed_up_as_unknown(self):
        bad = self.minimal(type='usage', usage={
            'inputTokens': {'value': None, 'unit': 'tokens', 'provenance': 'measured', 'source': 'x'},
            'outputTokens': None, 'costUSD': None, 'durationSeconds': None, 'scope': 'self'})
        with self.assertRaises(ValueError):
            traces.validate_event(bad)


class ImportTests(TraceTestCase):
    def test_import_is_idempotent(self):
        store = self.store()
        first = self.load('active.jsonl', 'run-act001', store)
        self.assertGreater(first['added'], 0)
        second = traces.import_file(FIXTURES / 'active.jsonl', 'run-act001', 'exp-demo', store)
        self.assertEqual(second['added'], 0)
        self.assertEqual(second['duplicates'], len(second['events']))
        self.assertEqual(len(store.events('run-act001')), first['added'])

    def test_exact_duplicate_line_counts_once(self):
        store = self.store()
        result = self.load('active.jsonl', 'run-act001', store)
        # the fixture repeats one line verbatim
        self.assertGreater(len(result['events']), result['added'])
        self.assertEqual(result['duplicates'], len(result['events']) - result['added'])

    def test_conflicting_duplicate_identity_raises(self):
        store = self.store()
        self.load('active.jsonl', 'run-act001', store)
        with self.assertRaises(traces.TraceConflict):
            traces.import_file(FIXTURES / 'active_conflict.jsonl', 'run-act001', 'exp-demo', store)

    def test_conflict_leaves_the_store_untouched(self):
        store = self.store()
        self.load('active.jsonl', 'run-act001', store)
        before = [traces.canonical(e) for e in store.events()]
        with self.assertRaises(traces.TraceConflict):
            traces.import_file(FIXTURES / 'active_conflict.jsonl', 'run-act001', 'exp-demo', store)
        self.assertEqual(before, [traces.canonical(e) for e in store.events()])
        self.assertEqual(before, [traces.canonical(e) for e in traces.TraceStore(self.store_path).events()])

    def test_shuffled_arrival_yields_identical_events(self):
        reference = self.load('active.jsonl', 'run-act001')['events']
        baseline = traces.TraceStore(Path(self.tmp.name) / 'a.jsonl')
        baseline.add(reference)

        for seed in (1, 2, 3):
            shuffled = list(reference)
            random.Random(seed).shuffle(shuffled)
            other = traces.TraceStore(Path(self.tmp.name) / f'b{seed}.jsonl')
            other.add(shuffled)
            with self.subTest(seed=seed):
                self.assertEqual([traces.canonical(e) for e in baseline.events()],
                                 [traces.canonical(e) for e in other.events()])
                self.assertEqual((Path(self.tmp.name) / 'a.jsonl').read_text(),
                                 (Path(self.tmp.name) / f'b{seed}.jsonl').read_text())

    def test_persistence_round_trips(self):
        store = self.store()
        self.load('handoff.jsonl', 'run-hand01', store)
        reopened = traces.TraceStore(self.store_path)
        self.assertEqual([traces.canonical(e) for e in store.events()],
                         [traces.canonical(e) for e in reopened.events()])

    def test_events_are_ordered_by_the_contract_key(self):
        store = self.store()
        self.load('active.jsonl', 'run-act001', store)
        rows = store.events('run-act001')
        keys = [(e['timestamp'], e['nodeId'], e['attempt'], e['eventId']) for e in rows]
        self.assertEqual(keys, sorted(keys))


class ImporterDispatchTests(TraceTestCase):
    def test_no_matching_importer_is_an_error(self):
        path = Path(self.tmp.name) / 'mystery.jsonl'
        path.write_text('{"hello": "world"}\n')
        with self.assertRaises(traces.ImporterError):
            traces.import_file(path, 'run-x')

    def test_multiple_matching_importers_is_an_error(self):
        class Always:
            NAME, VERSION = 'always', '1.0.0'
            detect = staticmethod(lambda path: True)
            parse = staticmethod(lambda path, run, exp=None: [])

        with self.assertRaises(traces.ImporterError):
            traces.import_file(FIXTURES / 'solo.jsonl', 'run-solo01',
                               importers=[synthetic, Always, Always])

    def test_detection_is_structural_not_name_based(self):
        renamed = Path(self.tmp.name) / 'definitely_a_claude_session.jsonl'
        renamed.write_bytes((FIXTURES / 'solo.jsonl').read_bytes())
        self.assertEqual(traces.detect_importer(renamed).NAME, 'synthetic')

        renamed2 = Path(self.tmp.name) / 'synthetic.jsonl'
        renamed2.write_bytes((FIXTURES / 'claude_session.jsonl').read_bytes())
        self.assertEqual(traces.detect_importer(renamed2).NAME, 'claude_jsonl')

    def test_shipped_importers_are_discovered(self):
        names = {i.NAME for i in traces.available_importers()}
        self.assertLessEqual({'synthetic', 'claude_jsonl'}, names)

    def test_every_event_records_its_provenance(self):
        for name, run in (('solo.jsonl', 'run-solo01'), ('claude_session.jsonl', 'run-cc001')):
            with self.subTest(name=name):
                result = traces.import_file(FIXTURES / name, run, 'exp-demo')
                self.assertTrue(result['events'])
                for event in result['events']:
                    evidence = event['evidence']
                    self.assertEqual(evidence['importer'], result['importer'])
                    self.assertEqual(evidence['importerVersion'], result['importerVersion'])
                    self.assertEqual(evidence['sha256'], result['sha256'])
                    self.assertTrue(evidence['ref'])

    def test_synthetic_importer_stamps_synthetic(self):
        result = traces.import_file(FIXTURES / 'solo.jsonl', 'run-solo01', 'exp-demo')
        self.assertTrue(all(e['synthetic'] for e in result['events']))


class ClaudeTranscriptTests(TraceTestCase):
    def setUp(self):
        super().setUp()
        self.result = traces.import_file(FIXTURES / 'claude_session.jsonl', 'run-cc001', 'exp-demo')
        self.events = self.result['events']
        self.blob = json.dumps(self.events)

    def test_subagent_becomes_its_own_node_under_the_main_node(self):
        nodes = {e['nodeId'] for e in self.events}
        subagents = sorted(n for n in nodes if n.startswith('subagent-'))
        self.assertEqual(len(subagents), 1)
        self.assertIn('main', nodes)
        sub_events = [e for e in self.events if e['nodeId'] == subagents[0] and e['type'] != 'note']
        self.assertTrue(all(e['parentId'] == 'main' for e in sub_events))
        self.assertTrue(all(e['role'] == 'worker' for e in sub_events))

    def test_main_node_is_orchestrator_when_it_delegates(self):
        main = [e for e in self.events if e['nodeId'] == 'main' and e['type'] != 'note']
        self.assertTrue(main)
        self.assertTrue(all(e['role'] == 'orchestrator' for e in main))

    def test_no_reasoning_text_is_imported(self):
        self.assertNotIn('REDACTION CANARY', self.blob)
        self.assertNotIn('thinking', self.blob)
        self.assertNotIn('escape embedded commas', self.blob)

    def test_home_paths_are_redacted(self):
        self.assertNotIn('/Users/', self.blob)
        started = [e for e in self.events if e['type'] == 'node_started' and e['nodeId'] == 'main'][0]
        self.assertEqual(started['payload']['workspace'], '~/projects/demo-bench')

    def test_redactor_covers_credentials_and_addresses(self):
        dirty = {'a': 'reach me at person@example.com', 'b': ['sk-abcdefgh12345678', 'ghp_ABCDEFGH12345678'],
                 'c': 'Authorization: Bearer abcdefgh12345678', 'd': '/Users/jdoe/x', 'e': 'api_key: hunter2hunter2'}
        clean = json.dumps(redact(dirty))
        for leak in ('person@example.com', 'sk-abcdefgh12345678', 'ghp_ABCDEFGH12345678',
                     'abcdefgh12345678', '/Users/jdoe', 'hunter2hunter2'):
            self.assertNotIn(leak, clean)
        self.assertIn('~/x', clean)

    def test_effective_model_is_observed_not_requested(self):
        usage = [e for e in self.events if e['type'] == 'usage' and e['nodeId'] == 'main']
        self.assertTrue(usage)
        for event in usage:
            self.assertIsNone(event['model']['requested'])
            self.assertEqual(event['model']['effective'], 'fabricated-model-a')
            self.assertTrue(event['model']['verified'])

    def test_input_tokens_sum_the_cache_fields(self):
        first = [e for e in self.events if e['type'] == 'usage' and e['nodeId'] == 'main'][0]
        self.assertEqual(first['usage']['inputTokens']['value'], 1200 + 400 + 8000)
        self.assertEqual(first['usage']['inputTokens']['provenance'], 'measured')

    def test_unknown_usage_stays_null_never_zero(self):
        last = [e for e in self.events if e['type'] == 'usage' and e['nodeId'] == 'main'][-1]
        self.assertIsNone(last['usage']['outputTokens']['value'])
        self.assertEqual(last['usage']['outputTokens']['provenance'], 'unavailable')
        for event in self.events:
            if event['type'] == 'usage':
                self.assertIsNone(event['usage']['costUSD']['value'])

    def test_run_total_is_unknown_when_a_turn_is_unknown(self):
        total = [e for e in self.events if (e['payload'] or {}).get('runTotal')][0]
        self.assertEqual(total['usage']['scope'], 'inclusive')
        self.assertIsNone(total['usage']['outputTokens']['value'])
        self.assertEqual(total['usage']['inputTokens']['value'], 9600 + 11000 + 500 + 13400)

    def test_human_follow_up_is_an_intervention_and_the_first_prompt_is_not(self):
        interventions = [e for e in self.events if e['type'] == 'intervention']
        self.assertEqual(len(interventions), 1)
        self.assertEqual(interventions[0]['payload'], {'kind': 'human_prompt'})

    def test_tool_use_is_recorded_without_its_input(self):
        notes = [e for e in self.events if e['type'] == 'note']
        self.assertEqual(sorted(n['payload']['tool'] for n in notes), ['Read', 'Task', 'Write'])
        self.assertTrue(all('input' not in n['payload'] for n in notes))

    def test_events_validate_and_store(self):
        store = self.store()
        added = store.add(self.events)
        self.assertEqual(added['added'], len(self.events))
        self.assertEqual(store.add(self.events), {'added': 0, 'duplicates': len(self.events)})

    def test_a_re_emitted_turn_is_one_turn(self):
        """Real transcripts repeat a uuid with incidental metadata changed."""
        lines = (FIXTURES / 'claude_session.jsonl').read_text().splitlines()
        assistant = [ln for ln in lines if '"msg_fixture_01"' in ln][0]
        rewritten = json.loads(assistant)
        rewritten['slug'] = 're-emitted-with-a-new-incidental-field'
        noisy = Path(self.tmp.name) / 'noisy.jsonl'
        noisy.write_text('\n'.join(lines + [json.dumps(rewritten)]) + '\n')

        events = traces.import_file(noisy, 'run-cc001', 'exp-demo')['events']
        self.assertEqual(len(events), len(self.events))
        store = self.store()
        self.assertEqual(store.add(events)['added'], len(events))

    def test_synthetic_importer_refuses_a_transcript(self):
        self.assertFalse(synthetic.detect(FIXTURES / 'claude_session.jsonl'))
        self.assertFalse(claude_jsonl.detect(FIXTURES / 'solo.jsonl'))


class GraphJoinLineageTests(TraceTestCase):
    def setUp(self):
        super().setUp()
        self.s = self.store()
        self.load('active.jsonl', 'run-act001', self.s)

    def test_declared_and_observed_graphs_differ_where_the_candidate_deviated(self):
        declared = self.s.declared_graph('run-act001')
        observed = self.s.observed_graph('run-act001')
        self.assertIn('worker-d', declared['nodes'])
        self.assertNotIn('worker-d', observed['nodes'])
        self.assertNotEqual(declared['edges'], observed['edges'])

    def test_join_accounts_for_every_expected_node(self):
        expected = sorted(self.s.declared_graph('run-act001')['nodes'])
        joined = self.s.join(expected, 'run-act001')
        self.assertEqual(sorted(joined), expected)
        self.assertEqual(joined['worker-a'], 'completed')   # retry succeeded
        self.assertEqual(joined['worker-b'], 'completed')
        self.assertEqual(joined['worker-c'], 'failed')
        self.assertEqual(joined['worker-d'], 'missing')
        self.assertEqual(joined['reviewer'], 'skipped')
        self.assertFalse(joined.join_ok)

    def test_failed_and_missing_never_become_empty_success(self):
        joined = self.s.join(['worker-c', 'worker-d', 'ghost'], 'run-act001')
        self.assertNotIn('completed', set(joined.values()))
        self.assertEqual(joined['ghost'], 'missing')

    def test_join_ok_only_when_everything_completed_or_was_skipped(self):
        self.assertTrue(self.s.join(['worker-a', 'worker-b', 'reviewer'], 'run-act001').join_ok)
        self.assertFalse(self.s.join(['worker-a', 'worker-c'], 'run-act001').join_ok)

    def test_lineage_exposes_stale_revisions_and_reused_artifacts(self):
        lineage = self.s.lineage('worker-a', 'run-act001')
        self.assertEqual([a['attempt'] for a in lineage], [1, 2])
        self.assertEqual([a['sourceRevision'] for a in lineage], ['rev-1', 'rev-2'])
        self.assertEqual([a['status'] for a in lineage], ['failed', 'completed'])
        self.assertTrue(lineage[0]['stale'])
        self.assertFalse(lineage[1]['stale'])
        self.assertEqual(lineage[1]['reusedArtifactHashes'], ['1' * 64])

    def test_run_scoping_keeps_runs_apart(self):
        self.load('solo.jsonl', 'run-solo01', self.s)
        self.assertEqual(self.s.runs(), ['run-act001', 'run-solo01'])
        self.assertTrue(all(e['runId'] == 'run-solo01' for e in self.s.events('run-solo01')))


if __name__ == '__main__':
    unittest.main()
