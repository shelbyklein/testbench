"""OFFLINE validation: capability inspection and workflow-definition validation.

No paid model call is made anywhere in this module.
"""
import json
import unittest
from pathlib import Path

from adapters import claude_workflow as adapter
from tests.workflow import fixtures


class CapabilityInspectionTest(unittest.TestCase):
    """`capabilities()` is inspection only and says so."""

    def test_reports_no_paid_calls_and_is_inspection_only(self):
        report = adapter.capabilities()
        self.assertFalse(report['paidCallsMade'])
        self.assertTrue(report['inspectionOnly'])
        self.assertEqual(report['contract'], 'adapter/1')

    def test_every_check_is_named_with_a_detail(self):
        report = adapter.capabilities()
        names = [check['name'] for check in report['checked']]
        for expected in ('claude_on_path', 'cli_version_floor', 'workflows_not_disabled',
                         'workflow_definition', 'workflow_script_present',
                         'saved_workflow_installed', 'headless_permission_rule'):
            self.assertIn(expected, names)
        for check in report['checked']:
            self.assertIsInstance(check['ok'], bool)
            self.assertTrue(str(check['detail']).strip(), f'{check["name"]} has no detail')

    def test_available_is_the_conjunction_of_its_checks(self):
        report = adapter.capabilities()
        self.assertEqual(report['available'], all(c['ok'] for c in report['checked']))

    def test_capability_report_document_exists_and_records_unverified_items(self):
        doc = Path(adapter.HERE) / 'CAPABILITY.md'
        self.assertTrue(doc.is_file())
        text = doc.read_text()
        self.assertIn('UNVERIFIED', text)
        self.assertIn('CONFOUND', text)
        self.assertIn('2.1.278', text)


class ShippedDefinitionTest(unittest.TestCase):
    """The versioned templates load and mean what the contract says."""

    def test_graph_definition_loads(self):
        data = adapter.load_workflow()
        self.assertEqual(data['id'], 'graph-candidate')
        self.assertEqual(data['scriptVersion'], 'graph-candidate.v1')
        self.assertTrue((Path(adapter.HERE).parent.parent / data['script']).is_file())

    def test_graph_declares_planner_workers_reviewer_integrator(self):
        roles = [n['role'] for n in adapter.load_workflow()['nodes']]
        self.assertIn('planner', roles)
        self.assertIn('reviewer', roles)
        self.assertIn('integrator', roles)
        self.assertGreaterEqual(roles.count('worker'), 2)

    def test_reviewer_is_fresh_and_never_sees_the_worker_conversation(self):
        reviewer = next(n for n in adapter.load_workflow()['nodes'] if n['role'] == 'reviewer')
        self.assertTrue(reviewer['freshSession'])
        self.assertTrue(reviewer['chargedToCandidate'])
        self.assertIn('worker-conversation', reviewer['forbiddenInputs'])
        self.assertIn('external-evaluator-output', reviewer['forbiddenInputs'])

    def test_join_is_never_by_list_index(self):
        data = adapter.load_workflow()
        self.assertFalse(data['join']['byListIndex'])
        self.assertEqual(data['join']['by'], ['nodeId', 'sourceRevision'])

    def test_token_and_cost_budgets_are_never_claimed_enforced(self):
        for path in (adapter.DEFAULT_WORKFLOW, adapter.SOLO_WORKFLOW):
            budgets = adapter.load_workflow(path)['budgets']
            self.assertEqual(budgets['max_tokens']['enforcement'], 'unavailable')
            self.assertEqual(budgets['max_cost_usd']['enforcement'], 'unavailable')

    def test_solo_definition_is_a_single_node(self):
        data = adapter.load_workflow(adapter.SOLO_WORKFLOW)
        self.assertEqual(len(data['nodes']), 1)
        self.assertEqual(data['nodes'][0]['id'], 'solo')
        self.assertIn('first_persisted_ack', data['milestones'])

    def test_shipped_scripts_set_no_model_or_effort_override(self):
        """A per-node effort or model override would silently change the arm."""
        for name in ('graph-candidate.v1.js', 'solo.v1.js'):
            body = (Path(adapter.WORKFLOW_DIR) / name).read_text()
            code = '\n'.join(line for line in body.splitlines()
                             if not line.strip().startswith('//'))
            self.assertNotIn('effort:', code, f'{name} sets a per-node effort override')
            self.assertNotIn('model:', code, f'{name} sets a per-node model override')

    def test_method_json_references_the_adapter_and_stays_unconfigured(self):
        root = Path(adapter.HERE).parent.parent
        method = json.loads((root / 'methods' / 'graph.json').read_text())
        self.assertEqual(method['adapter'], 'adapters/claude_workflow')
        self.assertFalse(method['configured'])
        self.assertEqual(method['adapter_workflow']['workflow_version'], '1.0.0')
        self.assertEqual(method['adapter_workflow']['script_version'], 'graph-candidate.v1')
        self.assertEqual(method['budgets']['max_tokens']['enforcement'], 'unavailable')
        self.assertEqual(method['budgets']['max_cost_usd']['enforcement'], 'unavailable')
        self.assertEqual(method['budgets']['max_workers']['enforcement'], 'enforced')
        self.assertIsNone(method['adapter_workflow']['live']['run_command'])


class DefinitionValidationTest(unittest.TestCase):

    def test_rejects_wrong_contract(self):
        broken = fixtures.flat_workers(1)
        broken['contract'] = 'workflow-definition/999'
        with self.assertRaises(adapter.WorkflowDefinitionError):
            adapter.validate_workflow(broken)

    def test_rejects_overlapping_file_ownership(self):
        broken = fixtures.workflow([fixtures.node('worker-a', owns=['src/x.mjs']),
                                    fixtures.node('worker-b', owns=['src/x.mjs'])])
        with self.assertRaises(adapter.WorkflowDefinitionError) as caught:
            adapter.validate_workflow(broken)
        self.assertIn('exclusive file ownership', str(caught.exception))

    def test_rejects_dependency_cycle(self):
        broken = fixtures.workflow([fixtures.node('a', depends_on=['b']),
                                    fixtures.node('b', depends_on=['a'])])
        with self.assertRaises(adapter.WorkflowDefinitionError):
            adapter.validate_workflow(broken)

    def test_rejects_unknown_dependency_and_unknown_role(self):
        with self.assertRaises(adapter.WorkflowDefinitionError):
            adapter.validate_workflow(fixtures.workflow([fixtures.node('a', depends_on=['ghost'])]))
        with self.assertRaises(adapter.WorkflowDefinitionError):
            adapter.validate_workflow(fixtures.workflow([fixtures.node('a', role='wizard')]))


class PlanTest(unittest.TestCase):

    def test_plan_is_deterministic_and_topological(self):
        declared = adapter.plan(fixtures.graph_shape(), scenario='S6', workspace='/tmp/x')
        ids = [d['nodeId'] for d in declared]
        self.assertEqual(ids, [d['nodeId'] for d in
                               adapter.plan(fixtures.graph_shape(), 'S6', '/tmp/x')])
        self.assertLess(ids.index('planner'), ids.index('worker-a'))
        self.assertLess(ids.index('worker-a'), ids.index('reviewer'))
        self.assertLess(ids.index('reviewer'), ids.index('integrator'))

    def test_plan_carries_ownership_and_workflow_version(self):
        declared = adapter.plan(adapter.load_workflow())
        worker = next(d for d in declared if d['nodeId'] == 'worker-a')
        self.assertEqual(worker['owns'], ['src/store.mjs'])
        self.assertEqual(worker['workflow']['scriptVersion'], 'graph-candidate.v1')


if __name__ == '__main__':
    unittest.main()
