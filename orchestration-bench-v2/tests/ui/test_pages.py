"""Checks that do not need a browser: page isolation, served shapes, and the demo experiment.

These run everywhere. The browser-driven acceptance checks live in ``test_browser.py``.
"""
import json
import re
import sys
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.ui.support import DemoBenchCase  # noqa: E402

DASHBOARD = ROOT / 'bench' / 'dashboard.html'
REVIEW_PAGE = ROOT / 'bench' / 'review.html'
ASSETS = ROOT / 'bench' / 'assets'
EXTERNAL = re.compile(r'(?:src|href)\s*=\s*["\'](?!#)((?:https?:)?//|data:|file:)', re.I)


def fetch(url, headers=None, data=None):
    request = urllib.request.Request(url, data=data, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status, response.read().decode()
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode()


class PageSourceTest(unittest.TestCase):
    """The two pages must stay offline-capable, and the review page must stay isolated."""

    def test_pages_exist_with_token_markers(self):
        self.assertIn('__BENCH_TOKEN__', DASHBOARD.read_text())
        self.assertIn('__REVIEW_TOKEN__', REVIEW_PAGE.read_text())

    def test_no_external_resources(self):
        for page in (DASHBOARD, REVIEW_PAGE):
            match = EXTERNAL.search(page.read_text())
            self.assertIsNone(match, f'{page.name} loads an external resource: {match}')

    def test_assets_are_plain_and_local(self):
        suffixes = {path.suffix for path in ASSETS.iterdir() if path.is_file()}
        self.assertTrue(suffixes <= {'.css', '.js', '.mjs', '.svg', '.json'}, suffixes)
        for path in ASSETS.iterdir():
            if path.is_file():
                self.assertIsNone(EXTERNAL.search(path.read_text()), path.name)

    def test_review_page_is_self_contained(self):
        """The review server serves no asset route, so the page may not reference one."""
        text = REVIEW_PAGE.read_text().lower()
        self.assertNotIn('/assets/', text)
        self.assertNotIn('rel="stylesheet"', text)
        self.assertNotIn('<script src', text)

    def test_review_page_calls_only_review_routes(self):
        text = REVIEW_PAGE.read_text()
        routes = set(re.findall(r"""['"](/[a-z0-9/_.-]*api[a-z0-9/_.-]*)""", text, re.I))
        self.assertTrue(routes, 'the review page calls no API at all')
        for route in routes:
            self.assertTrue(route.startswith('/review/api/'), route)

    def test_review_page_names_no_operator_concept(self):
        text = REVIEW_PAGE.read_text().lower()
        for term in ('methodlabel', 'runid', '/api/data', '/api/metrics', '/api/trace',
                     'x-bench-token', 'pairkey', 'launch'):
            self.assertNotIn(term, text, f'review.html mentions {term!r}')

    def test_dashboard_renders_unknown_rather_than_zero(self):
        script = (ASSETS / 'dashboard.js').read_text()
        self.assertIn('>unknown<', script)
        self.assertIn('partial (', script)
        self.assertIn('winner', script)

    def test_stylesheet_supports_dark_and_reduced_motion(self):
        css = (ASSETS / 'bench.css').read_text()
        self.assertIn('prefers-color-scheme: dark', css)
        self.assertIn('prefers-reduced-motion: reduce', css)
        self.assertIn(':focus-visible', css)


class ServedPagesTest(DemoBenchCase):
    """Both servers serve the lane's pages, with their own token injected."""

    def test_operator_serves_the_dashboard_and_its_assets(self):
        status, body = fetch(self.servers.bench_url + '/')
        self.assertEqual(status, 200)
        self.assertNotIn('__BENCH_TOKEN__', body)
        self.assertIn('window.BENCH_TOKEN', body)
        for asset in ('bench.css', 'dashboard.js'):
            status, text = fetch(self.servers.bench_url + '/assets/' + asset)
            self.assertEqual(status, 200, asset)
            self.assertTrue(text.strip())

    def test_review_server_serves_the_lane_review_page(self):
        status, body = fetch(self.servers.review_url + '/')
        self.assertEqual(status, 200)
        self.assertNotIn('__REVIEW_TOKEN__', body)
        self.assertIn('Blind review', body)
        self.assertNotIn('placeholder confirms', body)

    def test_review_server_has_no_operator_route(self):
        for route in ('/api/data', '/api/metrics', '/api/trace/run-zz0001', '/assets/bench.css'):
            status, _ = fetch(self.servers.review_url + route)
            self.assertEqual(status, 404, route)

    def test_operator_payloads_carry_what_the_pages_render(self):
        status, body = fetch(self.servers.bench_url + '/api/data')
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertTrue(data['synthetic'])
        self.assertFalse(data['readiness']['ready'])
        self.assertTrue(data['readiness']['blockers'])
        gates = {run['id']: {p: d['gate'] for p, d in run['phases'].items()} for run in data['runs']}
        self.assertIn('Review is stale', json.dumps(gates))

        status, body = fetch(self.servers.bench_url + '/api/trace/run-zz0001')
        trace = json.loads(body)
        self.assertTrue(trace['synthetic'])
        self.assertIn('worker-d', trace['report']['join']['missing'])
        self.assertIn('worker-c', trace['report']['join']['failed'])
        self.assertEqual(trace['declared']['nodes']['worker-a']['attempts'], [1])

        status, body = fetch(self.servers.bench_url + '/api/metrics')
        comparison = json.loads(body)
        self.assertIsNone(comparison['winner'])
        self.assertEqual(comparison['winnerPolicy'], 'not computed')
        self.assertIsNone(comparison['compositeScore'])
        self.assertTrue(comparison['incompleteTraces'])

    def test_an_estimated_and_an_unknown_measurement_are_both_present(self):
        status, body = fetch(self.servers.bench_url + '/api/trace/run-zz0003')
        trace = json.loads(body)
        provenances = {(event.get('usage') or {}).get('costUSD', {}).get('provenance')
                       for event in trace['timeline'] if (event.get('usage') or {}).get('costUSD')}
        self.assertIn('estimated', provenances)
        self.assertIn('unavailable', provenances)
        totals = trace['report']['usageTotals']
        self.assertFalse(totals['costUSD']['complete'])
        self.assertIsNone(totals['outputTokens']['value'])

    def test_review_api_serves_labels_without_operator_terms(self):
        status, body = fetch(self.servers.review_url + '/review/api/submissions?phase=first')
        self.assertEqual(status, 200)
        payload = json.loads(body)
        labels = [row['label'] for row in payload['submissions']]
        self.assertEqual(labels, sorted(labels), 'the page must be served an already-sorted list')
        for term in self.demo['identityStrings']:
            self.assertNotIn(term, body, term)

    def test_a_moved_submission_is_refused_as_stale(self):
        target = self.demo['staleTarget']
        status, body = fetch(
            self.servers.review_url + f'/review/api/submission/{target["label"]}?phase=first')
        projection = json.loads(body)
        path = Path(target['file'])
        path.write_text(path.read_text() + '\nMoved under the reviewer.\n')
        payload = json.dumps({
            'label': projection['label'], 'phase': 'first',
            'submissionHash': projection['submissionHash'],
            'evaluatorVersion': projection['evaluatorVersion'],
            'review': dict(projection['reviewTemplate']['blank'], reviewer='anon-1'),
        }).encode()
        status, body = fetch(self.servers.review_url + '/review/api/review',
                             headers={'Content-Type': 'application/json',
                                      'X-Review-Token': self.servers.review.review_token},
                             data=payload)
        self.assertEqual(status, 409)
        self.assertTrue(json.loads(body)['stale'])


if __name__ == '__main__':
    unittest.main()
