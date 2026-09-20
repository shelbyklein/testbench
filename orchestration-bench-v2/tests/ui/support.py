"""Shared scaffolding for the UI lane tests: the demo experiment plus both real servers.

Both servers are the real ones (``bench.make_server`` and
``bench_core.review_server.make_server``) bound to ephemeral ports, so the pages are tested
against the actual operator and reviewer APIs rather than against a mock.
"""
import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import bench  # noqa: E402
from bench_core import review_server  # noqa: E402
from tests.ui import demo  # noqa: E402

PLAYWRIGHT_DIR = Path('/Users/shelbyklein/Vibes/Newton/node_modules')
CHROME_APP = Path('/Applications/Google Chrome.app')
MIN_NODE_MAJOR = 22


class Servers:
    """The operator and review servers for one demo experiment."""

    def __init__(self, exp_dir):
        self.operator = bench.make_server(exp_dir, 0)
        self.review = review_server.make_server(exp_dir, 0)
        self._threads = []

    def start(self):
        for server in (self.operator, self.review):
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            self._threads.append(thread)
        return self

    @property
    def bench_url(self):
        return f'http://127.0.0.1:{self.operator.server_address[1]}'

    @property
    def review_url(self):
        return f'http://127.0.0.1:{self.review.review_port}'

    def stop(self):
        # Only servers this process started are ever shut down.
        for server in (self.operator, self.review):
            server.shutdown()
            server.server_close()
        for thread in self._threads:
            thread.join(timeout=5)


class DemoBenchCase(unittest.TestCase):
    """A demo experiment in a temp directory with both servers running."""

    @classmethod
    def setUpClass(cls):
        cls._base = Path(tempfile.mkdtemp(prefix='ob2-ui-'))
        cls.demo = demo.build(cls._base)
        cls.exp = Path(cls.demo['experiment'])
        cls.servers = Servers(cls.exp).start()

    @classmethod
    def tearDownClass(cls):
        cls.servers.stop()
        shutil.rmtree(cls._base, ignore_errors=True)


def node_executable():
    """The `node` binary when it is new enough for this script, else None."""
    import subprocess
    node = shutil.which('node')
    if not node:
        return None
    try:
        version = subprocess.run([node, '--version'], text=True, capture_output=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    try:
        major = int(version.strip().lstrip('v').split('.')[0])
    except ValueError:
        return None
    return node if major >= MIN_NODE_MAJOR else None


def browser_tooling_problem():
    """A human-readable reason the browser checks cannot run, or None when they can."""
    if node_executable() is None:
        return f'node {MIN_NODE_MAJOR}+ is not on PATH'
    if not (PLAYWRIGHT_DIR / 'playwright').is_dir():
        return f'Playwright is not present at {PLAYWRIGHT_DIR / "playwright"}'
    if not CHROME_APP.exists():
        return f'Google Chrome is not installed at {CHROME_APP}'
    return None
