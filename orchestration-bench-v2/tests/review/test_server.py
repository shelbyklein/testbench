"""Real HTTP against the reviewer server: payload bytes, route surface and traversal."""
import http.client
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support  # noqa: E402

from bench_core import common, review_projection, review_server  # noqa: E402

OPERATOR_ROUTES = ['/api/data', '/api/trace/run-zz0001', '/api/metrics', '/api/review',
                   '/api/configure', '/api/pair', '/experiment.json', '/review-map.json',
                   '/snapshots/run-zz0001/first/LAUNCH.md', '/review/api/', '/review/api/file/',
                   '/review/api/submissions']  # the last one only without a valid phase


class ServerTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ob2-review-')
        self.addCleanup(self.temp.cleanup)
        self.exp = Path(self.temp.name) / 'experiment'
        support.build_experiment(self.exp)
        self.terms = review_projection.forbidden_terms(self.exp)
        self.server = review_server.make_server(self.exp, 0)
        self.port = self.server.review_port
        self.token = self.server.review_token
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 5)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.projections = review_projection.build(self.exp, 'first')
        self.label = self.projections[0]['label']

    # ------------------------------------------------------------ helpers
    def request(self, method, path, body=None, headers=None, host=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=10)
        try:
            all_headers = dict(headers or {})
            if host:
                all_headers['Host'] = host
            payload = json.dumps(body).encode() if body is not None else None
            if payload is not None:
                all_headers['Content-Type'] = 'application/json'
            connection.request(method, path, body=payload, headers=all_headers)
            response = connection.getresponse()
            return response.status, response.read()
        finally:
            connection.close()

    def get(self, path, **kwargs):
        return self.request('GET', path, **kwargs)

    def assert_clean(self, raw, where):
        leaks = review_projection.scan(bytes(raw), self.terms)
        self.assertEqual(leaks, [], f'{where} leaked: {leaks}')
        self.assertNotIn(str(self.exp).encode(), raw)
        self.assertNotIn(str(Path.home()).encode(), raw)

    # ------------------------------------------------------------ page
    def test_root_serves_a_review_page_with_the_token_injected(self):
        status, raw = self.get('/')
        self.assertEqual(status, 200)
        self.assertIn(b'<html', raw.lower())
        self.assertIn(self.token.encode(), raw)
        self.assertNotIn(review_server.TOKEN_MARKER.encode(), raw)
        self.assert_clean(raw, 'GET /')

    def test_host_header_must_be_local(self):
        status, _ = self.get('/', host='example.com')
        self.assertEqual(status, 403)

    # ------------------------------------------------------------ listing
    def test_submissions_listing_bytes_are_clean_and_label_ordered(self):
        status, raw = self.get('/review/api/submissions?phase=first')
        self.assertEqual(status, 200)
        self.assert_clean(raw, 'GET /review/api/submissions')
        payload = json.loads(raw)
        self.assertEqual(payload['contract'], 'review-projection/1')
        labels = [row['label'] for row in payload['submissions']]
        self.assertEqual(labels, sorted(labels))
        self.assertEqual(set(labels), {p['label'] for p in self.projections})
        for row in payload['submissions']:
            self.assertEqual(set(row), {'contract', 'label', 'scenario', 'scenarioVersion',
                                        'repeat', 'phase', 'submissionHash', 'evaluatorVersion',
                                        'fileCount', 'evaluation', 'residualCues'})

    def test_repaired_listing_is_a_separate_package_set(self):
        status, raw = self.get('/review/api/submissions?phase=repaired')
        self.assertEqual(status, 200)
        self.assert_clean(raw, 'GET /review/api/submissions?phase=repaired')
        repaired = {row['label'] for row in json.loads(raw)['submissions']}
        self.assertEqual(len(repaired), 1)
        self.assertFalse(repaired & {p['label'] for p in self.projections})

    def test_invalid_phase_is_not_found(self):
        for path in ('/review/api/submissions', '/review/api/submissions?phase=../../etc',
                     '/review/api/submissions?phase=OPERATOR'):
            with self.subTest(path=path):
                self.assertEqual(self.get(path)[0], 404)

    # ------------------------------------------------------------ one submission
    def test_submission_bytes_are_clean_and_complete(self):
        status, raw = self.get(f'/review/api/submission/{self.label}?phase=first')
        self.assertEqual(status, 200)
        self.assert_clean(raw, 'GET /review/api/submission')
        payload = json.loads(raw)
        self.assertEqual(payload['label'], self.label)
        self.assertEqual({e['path'] for e in payload['files']},
                         {'src/app.mjs', 'src/cue.mjs', 'README.md', 'tests/smoke.test.mjs'})
        for hidden in ('evidence', 'stdout', 'stderr', 'details', 'method', 'model'):
            self.assertNotIn(hidden, common.canonical(payload['evaluation']))

    def test_unknown_label_is_not_found(self):
        self.assertEqual(self.get('/review/api/submission/B-ABCDEF?phase=first')[0], 404)
        self.assertEqual(self.get('/review/api/submission/nonsense?phase=first')[0], 404)

    # ------------------------------------------------------------ files
    def test_listed_files_are_served_byte_for_byte(self):
        for entry in self.projections[0]['files']:
            status, raw = self.get(
                f'/review/api/file/{self.label}/{entry["path"]}?phase=first')
            self.assertEqual(status, 200, entry['path'])
            self.assertNotIn(str(self.exp).encode(), raw)
            if entry['path'] != 'src/cue.mjs':
                self.assert_clean(raw, f'GET file {entry["path"]}')

    def test_submitted_source_may_still_carry_a_residual_cue(self):
        """Documented limitation: blinding cannot rewrite the submission's own content."""
        status, raw = self.get(f'/review/api/file/{self.label}/src/cue.mjs?phase=first')
        self.assertEqual(status, 200)
        cues = review_projection.scan(bytes(raw), self.terms)
        self.assertTrue(cues, 'the fixture plants a cue in submitted source')

    def test_unlisted_and_traversing_paths_are_refused(self):
        attempts = [
            'LAUNCH.md', 'APPROACH.md', 'SUBMISSION.md', 'HANDOFF.md', 'AGENTS.md',
            f'{support.PRIVATE_DIR}/expected.json', 'src/link.mjs',
            '../../../experiment.json', '../first/LAUNCH.md',
            '%2e%2e%2f%2e%2e%2fexperiment.json', '%2E%2E/%2E%2E/review-map.json',
            '/etc/passwd', 'src/../LAUNCH.md', 'src%2f..%2fLAUNCH.md', 'missing.mjs',
        ]
        for attempt in attempts:
            with self.subTest(path=attempt):
                status, raw = self.get(
                    f'/review/api/file/{self.label}/{attempt}?phase=first')
                self.assertIn(status, (400, 404))
                self.assertNotIn(b'Zebra-Method-Q7', raw)
                self.assertNotIn(str(self.exp).encode(), raw)

    def test_a_file_changed_after_projection_shifts_the_served_hash(self):
        """The server always serves the current snapshot; the POST hash check catches drift."""
        label = next(p['label'] for p in self.projections
                     if review_projection.resolve_label(self.exp, p['label'])['run']
                     == support.RUN_IDS[0])
        before = json.loads(self.get(f'/review/api/submission/{label}?phase=first')[1])
        target = self.exp / 'snapshots' / support.RUN_IDS[0] / 'first' / 'src/app.mjs'
        target.write_text('tampered\n')
        status, raw = self.get(f'/review/api/file/{label}/src/app.mjs?phase=first')
        self.assertEqual(status, 200)
        self.assertEqual(raw, b'tampered\n')
        after = json.loads(self.get(f'/review/api/submission/{label}?phase=first')[1])
        self.assertNotEqual(before['submissionHash'], after['submissionHash'])
        self.assertEqual(self.post_review(projection=before)[0], 409)

    # ------------------------------------------------------------ route surface
    def test_operator_routes_are_absent(self):
        for path in OPERATOR_ROUTES:
            with self.subTest(path=path):
                status, raw = self.get(path)
                self.assertEqual(status, 404, path)
                self.assertNotIn(str(self.exp).encode(), raw)
        self.assertEqual(self.request('POST', '/api/data', body={},
                                      headers={'X-Review-Token': self.token})[0], 404)

    def test_server_module_never_imports_the_operator_controller(self):
        source = (common.ROOT / 'bench_core' / 'review_server.py').read_text()
        self.assertNotIn('import bench\n', source)
        self.assertNotIn('from bench ', source)
        self.assertNotIn('experiment.view', source)
        self.assertNotIn('bench', sys.modules.get('bench_core.review_server').__dict__)

    # ------------------------------------------------------------ POST
    def post_review(self, projection=None, review=None, hash_value=None, version=None,
                    token=True):
        projection = projection or self.projections[0]
        headers = {'X-Review-Token': self.token} if token else {}
        return self.request('POST', '/review/api/review', headers=headers, body={
            'label': projection['label'], 'phase': projection['phase'],
            'submissionHash': hash_value or projection['submissionHash'],
            'evaluatorVersion': version or projection['evaluatorVersion'],
            'review': review or support.good_review()})

    def test_review_post_requires_the_launch_token(self):
        status, _ = self.post_review(token=False)
        self.assertEqual(status, 403)

    def test_review_post_saves_and_binds(self):
        status, raw = self.post_review()
        self.assertEqual(status, 200, raw)
        payload = json.loads(raw)
        self.assertTrue(payload['ok'])
        self.assertEqual(payload['submissionHash'], self.projections[0]['submissionHash'])
        run_id = review_projection.resolve_label(self.exp, self.label)['run']
        stored = common.read(self.exp / 'results' / run_id / 'first' / 'review.json')
        self.assertEqual(stored['label'], self.label)
        self.assert_clean(raw, 'POST /review/api/review')

    def test_stale_submission_hash_is_409(self):
        run_id = review_projection.resolve_label(self.exp, self.label)['run']
        target = self.exp / 'snapshots' / run_id / 'first' / 'src/app.mjs'
        target.write_text(target.read_text() + '// edited after the package was built\n')
        status, raw = self.post_review()
        self.assertEqual(status, 409)
        self.assertTrue(json.loads(raw)['stale'])
        self.assert_clean(raw, '409 body')

    def test_stale_evaluator_version_is_409(self):
        status, raw = self.post_review(version='9.9.9')
        self.assertEqual(status, 409)
        self.assertTrue(json.loads(raw)['stale'])

    def test_invalid_review_is_400_without_saving(self):
        broken = support.good_review()
        broken['scores'].pop('ux')
        status, raw = self.post_review(review=broken)
        self.assertEqual(status, 400)
        run_id = review_projection.resolve_label(self.exp, self.label)['run']
        self.assertFalse((self.exp / 'results' / run_id / 'first' / 'review.json').exists())
        self.assert_clean(raw, '400 body')

    def test_unknown_post_route_is_404(self):
        status, _ = self.request('POST', '/review/api/pair', body={},
                                 headers={'X-Review-Token': self.token})
        self.assertEqual(status, 404)


if __name__ == '__main__':
    unittest.main()
