"""OFFLINE validation: FakeExecutor provider isolation and LiveExecutor fail-closed.

`FakeExecutor` is provider-free BY CONSTRUCTION. The proof here is threefold: socket
creation is patched to raise, `claude` is removed from PATH, and the adapter's own source
is asserted to contain no provider endpoint or SDK reference. `LiveExecutor` is never
executed; it is only asserted to refuse. No paid model call is made.
"""
import ast
import socket
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from adapters import claude_workflow as adapter
from tests.workflow import fixtures

#: substrings that would indicate this module can reach a model provider
FORBIDDEN_SOURCE_TOKENS = (
    'api.anthropic.com', 'anthropic.com', 'openai', 'api.openai.com', 'googleapis',
    'bedrock', 'x-api-key', 'ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN',
    'import anthropic', 'from anthropic', 'urllib.request', 'http.client', 'requests.',
    'claude -p', "'-p'", '"-p"', '--print',
)

ADAPTER_SOURCES = sorted(Path(adapter.HERE).glob('*.py'))


class SourceLevelIsolationTest(unittest.TestCase):

    def test_adapter_sources_name_no_provider_endpoint_or_sdk(self):
        self.assertTrue(ADAPTER_SOURCES)
        for path in ADAPTER_SOURCES:
            text = path.read_text()
            for token in FORBIDDEN_SOURCE_TOKENS:
                self.assertNotIn(token, text, f'{path.name} references {token!r}')

    def test_adapter_imports_no_network_module(self):
        forbidden = {'socket', 'ssl', 'http', 'http.client', 'urllib', 'urllib.request',
                     'requests', 'httpx', 'anthropic', 'openai'}
        for path in ADAPTER_SOURCES:
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = {alias.name.split('.')[0] for alias in node.names}
                elif isinstance(node, ast.ImportFrom):
                    names = {(node.module or '').split('.')[0]}
                else:
                    continue
                self.assertFalse(names & forbidden,
                                 f'{path.name} imports {sorted(names & forbidden)}')

    def test_fake_executor_can_only_spawn_this_interpreter(self):
        import sys
        self.assertEqual(adapter.FakeExecutor.CHILD_ARGV_HEAD, (sys.executable, '-c'))
        source = Path(adapter.HERE, '__init__.py').read_text()
        # the only Popen in the module is the one built from CHILD_ARGV_HEAD
        self.assertEqual(source.count('Popen('), 1)
        self.assertIn('[*self.CHILD_ARGV_HEAD,', source)


class RuntimeIsolationTest(unittest.TestCase):
    """A full fake run completes with sockets disabled and `claude` off PATH."""

    def test_full_run_with_sockets_disabled_and_empty_path(self):
        def no_sockets(*args, **kwargs):
            raise AssertionError('FakeExecutor attempted to create a socket')

        with tempfile.TemporaryDirectory() as workspace, \
                mock.patch.object(socket, 'socket', no_sockets), \
                mock.patch.object(socket, 'create_connection', no_sockets), \
                mock.patch.dict('os.environ', {'PATH': ''}, clear=False):
            events = []
            result = adapter.run(fixtures.graph_shape(), adapter.FakeExecutor(),
                                 fixtures.limits(), events, workspace)
            self.assertEqual(result['status'], 'complete')
            self.assertFalse(result['paidCallsMade'])
            self.assertTrue(result['synthetic'])
            self.assertTrue(result['offlineValidation'])
            self.assertTrue(events)

    def test_capabilities_reports_unavailable_without_the_cli(self):
        with mock.patch.dict('os.environ', {'PATH': ''}, clear=False):
            report = adapter.capabilities()
        self.assertFalse(report['available'])
        self.assertFalse(report['paidCallsMade'])
        by_name = {c['name']: c for c in report['checked']}
        self.assertFalse(by_name['claude_on_path']['ok'])

    def test_fake_executor_describes_itself_as_provider_free(self):
        described = adapter.FakeExecutor().describe()
        self.assertIsNone(described['provider'])
        self.assertFalse(described['paidCallsMade'])


class LiveExecutorFailClosedTest(unittest.TestCase):
    """The live executor is never run here. It is only asserted to refuse."""

    AVAILABLE = {'available': True, 'checked': [], 'paidCallsMade': False}
    UNAVAILABLE = {'available': False, 'paidCallsMade': False,
                   'checked': [{'name': 'claude_on_path', 'ok': False, 'detail': 'absent'}]}

    def test_refuses_without_a_configured_run_command(self):
        executor = adapter.LiveExecutor(capabilities_fn=lambda: self.AVAILABLE)
        with self.assertRaises(adapter.LiveExecutorUnavailable) as caught:
            executor.preflight()
        self.assertIn('explicitly configured run command', str(caught.exception))

    def test_refuses_when_capabilities_are_unavailable(self):
        executor = adapter.LiveExecutor(run_command=['claude', '--version'],
                                        capabilities_fn=lambda: self.UNAVAILABLE)
        with self.assertRaises(adapter.LiveExecutorUnavailable) as caught:
            executor.preflight()
        message = str(caught.exception)
        self.assertIn('fails closed', message)
        self.assertIn('claude_on_path', message)
        self.assertIn('never falls back', message)

    def test_run_fails_closed_before_declaring_any_node(self):
        with tempfile.TemporaryDirectory() as workspace:
            events = []
            with self.assertRaises(adapter.LiveExecutorUnavailable):
                adapter.run(fixtures.graph_shape(),
                            adapter.LiveExecutor(capabilities_fn=lambda: self.AVAILABLE),
                            fixtures.limits(), events, workspace)
            self.assertEqual(events, [], 'a refused live run must emit nothing')

    def test_execute_refuses_even_when_everything_checks_out(self):
        """This lane never performs paid execution, so execute() itself stops."""
        executor = adapter.LiveExecutor(run_command=['claude', 'run'],
                                        capabilities_fn=lambda: self.AVAILABLE)
        with self.assertRaises(adapter.LiveExecutorUnavailable) as caught:
            executor.execute(None)
        self.assertIn('paid model call', str(caught.exception))

    def test_effective_model_and_settings_stay_unverified_offline(self):
        described = adapter.LiveExecutor(run_command=['claude'],
                                         requested_model='RECORD MODEL',
                                         requested_settings={'effort': 'medium'}).describe()
        self.assertEqual(described['model']['requested'], 'RECORD MODEL')
        self.assertIsNone(described['model']['effective'])
        self.assertFalse(described['model']['verified'])
        self.assertEqual(described['settings']['requested'], {'effort': 'medium'})
        self.assertIsNone(described['settings']['effective'])
        self.assertFalse(described['settings']['verified'])
        self.assertFalse(described['paidCallsMade'])


if __name__ == '__main__':
    unittest.main()
