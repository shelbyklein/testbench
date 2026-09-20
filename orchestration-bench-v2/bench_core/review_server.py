"""Separate reviewer HTTP server (CONTRACTS.md §10).

This module deliberately imports **no operator controller**: it has no route to operator state,
no `/api/data`, no trace or metrics route, and no code path that reads the experiment other
than through :mod:`bench_core.review_projection`, which builds allow-listed projections.

It binds 127.0.0.1 only, checks the Host header, and requires a per-launch token on POST.
Error bodies are fixed strings or validation text; server-side paths never reach a response.
"""
import http.server
import json
import re
import secrets
import threading
import urllib.parse
import webbrowser
from pathlib import Path

from . import review_projection
from .review_projection import ReviewError, StaleReview

DEFAULT_PORT = 4389
REVIEW_PAGE = Path('bench') / 'review.html'
TOKEN_MARKER = '__REVIEW_TOKEN__'
MAX_BODY = 500_000
PHASE_PATTERN = re.compile(r'^[a-z][a-z0-9_-]{0,31}$')
LABEL_PATTERN = re.compile(r'^B-[0-9A-F]{6}$')
NOT_FOUND = {'error': 'Not found'}
PLACEHOLDER_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Blind review</title>
<style>
 :root { color-scheme: light dark; font-family: system-ui, sans-serif; }
 body { margin: 0 auto; max-width: 52rem; padding: 1.5rem 1rem; line-height: 1.5; }
 code { font-family: ui-monospace, monospace; }
 li { margin: .25rem 0; }
</style></head>
<body>
<h1>Blind review server</h1>
<p>The review page has not been installed yet. This placeholder confirms the reviewer server
is running and isolated from the operator dashboard.</p>
<p>Reviewer routes, and nothing else:</p>
<ul>
 <li><code>GET /review/api/submissions?phase=first</code></li>
 <li><code>GET /review/api/submission/&lt;label&gt;</code></li>
 <li><code>GET /review/api/file/&lt;label&gt;/&lt;path&gt;</code></li>
 <li><code>POST /review/api/review</code> (header <code>X-Review-Token</code>)</li>
</ul>
<p>Submissions are anonymized best-effort: submitted source can still reveal its author.</p>
<!-- token: __REVIEW_TOKEN__ -->
</body></html>
"""


def _page_source(exp_dir):
    """The UI lane's review page when installed, else the built-in placeholder."""
    for root in (Path(exp_dir), review_projection.common.ROOT):
        candidate = Path(root) / REVIEW_PAGE
        if candidate.is_file():
            return candidate.read_text()
    return PLACEHOLDER_PAGE


def make_handler(exp_dir, port, token, lock):
    exp_dir = Path(exp_dir)

    class ReviewHandler(http.server.BaseHTTPRequestHandler):
        server_version = 'ob2-review'
        sys_version = ''

        # ---------------------------------------------------------- plumbing
        def send(self, status, value, ctype='application/json'):
            if isinstance(value, (bytes, bytearray)):
                body = bytes(value)
            elif ctype.startswith('application/json'):
                body = json.dumps(value).encode()
            else:
                body = str(value).encode()
            self.send_response(status)
            self.send_header('Content-Type', ctype)
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            if self.command != 'HEAD':
                self.wfile.write(body)

        def valid_host(self):
            return self.headers.get('Host', '') in (f'127.0.0.1:{port}', f'localhost:{port}')

        def log_message(self, *args):
            pass

        # ---------------------------------------------------------- GET
        def do_GET(self):
            if not self.valid_host():
                return self.send(403, {'error': 'Local host required'})
            parsed = urllib.parse.urlsplit(self.path)
            path = urllib.parse.unquote(parsed.path)
            query = urllib.parse.parse_qs(parsed.query)
            try:
                with lock:
                    if path == '/':
                        return self.send(200, _page_source(exp_dir).replace(TOKEN_MARKER, token),
                                         'text/html; charset=utf-8')
                    if path == '/review/api/submissions':
                        return self.submissions(query)
                    if path.startswith('/review/api/submission/'):
                        return self.submission(path[len('/review/api/submission/'):], query)
                    if path.startswith('/review/api/file/'):
                        return self.file(path[len('/review/api/file/'):], query)
            except ReviewError:
                return self.send(404, NOT_FOUND)
            except Exception:  # never leak a server-side path or stack detail
                return self.send(400, {'error': 'Request could not be served'})
            return self.send(404, NOT_FOUND)

        def phase_of(self, query):
            phase = (query.get('phase') or [''])[0]
            if not PHASE_PATTERN.match(phase):
                raise ReviewError('Invalid phase')
            return phase

        def submissions(self, query):
            phase = self.phase_of(query)
            rows = [review_projection.summary(p) for p in review_projection.build(exp_dir, phase)]
            return self.send(200, {'contract': review_projection.CONTRACT, 'phase': phase,
                                   'submissions': rows,
                                   'residualCues': review_projection.RESIDUAL_CUES})

        def submission(self, rest, query):
            label = rest.strip('/')
            if not LABEL_PATTERN.match(label):
                raise ReviewError('Invalid label')
            return self.send(200, review_projection.find(exp_dir, self.phase_of(query), label))

        def file(self, rest, query):
            label, _, relative = rest.partition('/')
            if not LABEL_PATTERN.match(label) or not relative:
                raise ReviewError('Invalid file request')
            projection = review_projection.find(exp_dir, self.phase_of(query), label)
            listed = {entry['path']: entry for entry in projection['files']}
            entry = listed.get(relative)
            if entry is None:
                raise ReviewError('File is not part of this submission')
            run_id = review_projection.resolve_label(exp_dir, label)['run']
            snapshot = (exp_dir / 'snapshots' / run_id / projection['phase']).resolve()
            target = (snapshot / relative)
            if target.is_symlink() or not target.is_file():
                raise ReviewError('File is not part of this submission')
            resolved = target.resolve()
            if resolved != snapshot / relative or snapshot not in resolved.parents:
                raise ReviewError('File is not part of this submission')
            if review_projection.common.digest(resolved) != entry['sha256']:
                raise ReviewError('File changed after the review package was built')
            return self.send(200, resolved.read_bytes(), 'text/plain; charset=utf-8')

        # ---------------------------------------------------------- POST
        def do_POST(self):
            if not self.valid_host() or self.headers.get('X-Review-Token') != token:
                return self.send(403, {'error': 'Use this local review page'})
            path = urllib.parse.urlsplit(self.path).path
            if path != '/review/api/review':
                return self.send(404, NOT_FOUND)
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= MAX_BODY:
                    return self.send(400, {'error': 'Invalid body length'})
                body = json.loads(self.rfile.read(length))
                with lock:
                    record = review_projection.accept_review(
                        exp_dir, body.get('label'), body.get('phase'),
                        body.get('submissionHash'), body.get('evaluatorVersion'),
                        body.get('review'))
            except StaleReview as error:
                return self.send(409, {'error': str(error), 'stale': True})
            except ReviewError as error:
                return self.send(400, {'error': str(error)})
            except Exception:
                return self.send(400, {'error': 'Review could not be saved'})
            return self.send(200, {'ok': True, 'label': record['label'],
                                   'savedAt': record['savedAt'],
                                   'submissionHash': record['submissionHash']})

    return ReviewHandler


def make_server(exp_dir, port=DEFAULT_PORT):
    """A bound, unstarted ``ThreadingHTTPServer``. ``server.review_token`` is the POST token."""
    token = secrets.token_urlsafe(24)
    lock = threading.RLock()
    server = http.server.ThreadingHTTPServer(('127.0.0.1', port),
                                             make_handler(exp_dir, port, token, lock))
    # A port of 0 binds an ephemeral port; re-issue the handler so the Host check matches it.
    actual = server.server_address[1]
    if actual != port:
        server.RequestHandlerClass = make_handler(exp_dir, actual, token, lock)
    server.review_token = token
    server.review_port = actual
    return server


def serve(exp_dir, port=DEFAULT_PORT, open_browser=False):
    server = make_server(exp_dir, port)
    url = f'http://127.0.0.1:{server.review_port}'
    print(f'Blind review available at {url}\nReviewer view only; the operator dashboard is a '
          f'separate server.\nCtrl-C stops the review server; saved reviews remain.', flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return server
