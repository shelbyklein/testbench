"""Browser acceptance checks for OB2-12, run in installed Chrome through Playwright.

The Node script does the driving; this wrapper builds the demo experiment, starts both real
servers on ephemeral ports and reports the script's result. When Playwright, Chrome or a new
enough Node is missing, the test **skips** — it never passes silently, and it never claims a
browser verification that did not happen.
"""
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.ui import support  # noqa: E402

SCRIPT = Path(__file__).resolve().parent / 'browser_checks.mjs'
SHOTS = ROOT / 'validation' / 'ui'
TIMEOUT_SECONDS = 600


class BrowserChecksTest(support.DemoBenchCase):

    @classmethod
    def setUpClass(cls):
        problem = support.browser_tooling_problem()
        if problem:
            raise unittest.SkipTest(f'Browser checks cannot run: {problem}')
        super().setUpClass()

    def test_dashboard_and_review_pass_every_browser_check(self):
        SHOTS.mkdir(parents=True, exist_ok=True)
        environment = dict(os.environ)
        environment.update({
            'BENCH_URL': self.servers.bench_url,
            'REVIEW_URL': self.servers.review_url,
            'DEMO_JSON': str(Path(self.demo['experiment']).parent / 'demo.json'),
            'SHOT_DIR': str(SHOTS),
            'PLAYWRIGHT_DIR': str(support.PLAYWRIGHT_DIR),
        })
        result = subprocess.run([support.node_executable(), str(SCRIPT)],
                                cwd=str(ROOT), env=environment, text=True,
                                capture_output=True, timeout=TIMEOUT_SECONDS)
        report = None
        try:
            report = json.loads(result.stdout[result.stdout.index('{'):])
        except (ValueError, json.JSONDecodeError):
            pass
        if result.returncode != 0:
            failed = ([c for c in report['checks'] if not c['ok']] if report else [])
            detail = '\n'.join(f'  - {c["name"]}: {c["detail"]}' for c in failed) or result.stderr[-4000:]
            self.fail(f'browser checks failed (exit {result.returncode}):\n{detail}')
        self.assertIsNotNone(report, result.stdout[-2000:])
        self.assertEqual(report['failures'], 0)
        self.assertGreater(len(report['checks']), 40)
        for name in ('desktop', 'mobile'):
            for shot in ('dashboard-overview', 'trace-view', 'comparison', 'blind-review'):
                self.assertTrue((SHOTS / f'{shot}-{name}.png').is_file(), f'{shot}-{name}.png')


if __name__ == '__main__':
    unittest.main()
