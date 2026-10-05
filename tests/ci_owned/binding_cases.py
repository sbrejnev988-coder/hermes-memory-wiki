"""Synthetic receipt/launch validator units, NEVER native E2E evidence."""
import ast
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import unittest

SCRIPTS = Path(__file__).resolve().parents[2] / 'scripts/ci_owned'
sys.path.insert(0, str(SCRIPTS))  # CI-owned stdlib helpers only, not a native core.


def load(name):
    spec = importlib.util.spec_from_file_location('unit_' + name, SCRIPTS / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fixtures():
    # These are data identities only: no native file/core/plugin is loaded.
    run_id, root_id, child_id = 'a' * 32, 'b' * 32, 'c' * 32
    contract = {'run_id': run_id, 'source_sha': 'd' * 40, 'core_sha': load('memory_wiki_ci').CORE_SHA,
                'executable': 'fixture/python', 'memory_provider_origin': str(Path('fixture/core/agent/memory_provider.py').resolve()),
                'memory_provider_sha256': 'e' * 64, 'source_origin': str(Path('fixture/source/__init__.py').resolve())}
    def launch(identity, owner, pid, role):
        return {'launch_id': identity, 'run_id': run_id, 'owner_id': owner, 'pid': pid,
                'status': 'exited', 'role': role, 'lifecycle': 'must_finish', 'returncode': 0,
                'executable': contract['executable'], 'same_interpreter': True,
                'site_enabled': True, 'venv_launcher': False, 'command_sha256': 'f' * 64, 'expectation': None}
    launches = [launch(root_id, 'controller-' + run_id, 101, 'plugin'), launch(child_id, root_id, 102, 'plugin_capable')]
    def binding(row):
        value = {k: row[k] for k in ('launch_id', 'run_id', 'owner_id', 'role', 'pid', 'command_sha256', 'executable')}
        value.update({k: contract[k] for k in ('source_sha', 'core_sha', 'memory_provider_origin', 'memory_provider_sha256')})
        value.update(started=True, finished=True, state='finished', violations=[], ppid=101,
                     native_class_module='agent.memory_provider', nonplugin_guard_armed=False,
                     plugin_classes=[{'module': 'memory_wiki', 'origin': contract['source_origin'],
                                      'native_MRO': True, 'origin_role': 'source'}])
        return value
    return contract, launches, [binding(row) for row in launches]


def coverage(module, contract, launches, bindings):
    if hasattr(module, 'binding_coverage'):
        return module.binding_coverage(launches, bindings, contract)
    # Exercise the old actual source predicate for RED, not a replacement validator.
    tree = ast.parse((SCRIPTS / 'memory_wiki_ci.py').read_bytes())
    assignments = [node for node in ast.walk(tree) if isinstance(node, ast.Assign)
                   and any(isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name)
                           and t.value.id == 'receipt' and isinstance(t.slice, ast.Constant)
                           and t.slice.value == 'bindings_verified' for t in node.targets)]
    assert len(assignments) == 1
    expression = compile(ast.Expression(assignments[0].value), '<frozen actual legacy binding predicate>', 'eval')
    valid = eval(expression, {'CORE_SHA': module.CORE_SHA, 'bindings': bindings, 'origins': {'native_MRO': True},
                             'base_file': Path(contract['memory_provider_origin']), 'expected_base_hash': contract['memory_provider_sha256']})
    return {'verified': valid, 'errors': []}


class LaunchCoverageContract(unittest.TestCase):
    def setUp(self):
        self.module = load('memory_wiki_ci')
        self.contract, self.launches, self.bindings = fixtures()

    def result(self):
        return coverage(self.module, self.contract, self.launches, self.bindings)

    def test_complete_matching_plugin_processes_are_positive_control(self):
        self.assertTrue(self.result()['verified'])

    def test_launched_child_missing_receipt_fails_lane_and_matrix(self):
        self.bindings.pop()
        report = self.result()
        self.assertFalse(report['verified'], 'CI-NATIVE-01: finished parent must not hide missing launched child')
        records = []
        for platform in ('linux', 'win32'):
            for stage in ('full', 'recovery'):
                records.append({'platform': platform, 'python': '3.14', 'stage': stage,
                                'source_sha': self.contract['source_sha'], 'source_digest': 'same',
                                'core_sha': self.module.CORE_SHA, 'complete': bool(report['verified']),
                                'bindings_verified': bool(report['verified']), 'collected': ['case'],
                                'passed': ['case'], 'skipped': [], 'failed': [], 'errors': []})
        with self.assertRaises(RuntimeError):
            self.module.matrix_coverage(records, self.contract['source_sha'], versions=['3.14'])

    def test_startup_only_plugin_child_cannot_hide_behind_finished_parent(self):
        self.bindings[1].update(state='native_ready', finished=False, plugin_classes=[])
        self.assertFalse(self.result()['verified'])

    def test_finished_plugin_role_requires_own_MRO_record(self):
        self.launches[1]['role'] = self.bindings[1]['role'] = 'plugin'
        self.bindings[1]['plugin_classes'] = []
        self.assertFalse(self.result()['verified'])

    def test_foreign_unrecognized_no_site_or_stale_identity_fails_closed(self):
        original = copy.deepcopy(self.launches[1])
        mutations = ({'same_interpreter': False}, {'site_enabled': False}, {'role': 'unknown'},
                     {'status': 'planned'}, {'pid': 777}, {'run_id': '0' * 32},
                     {'command_sha256': '0' * 64}, {'owner_id': '0' * 32})
        for change in mutations:
            with self.subTest(change=change):
                self.launches[1] = {**original, **change}
                self.assertFalse(self.result()['verified'])

    def test_orphan_duplicate_or_missing_primary_identity_fails_closed(self):
        original = copy.deepcopy(self.bindings)
        for rows in (original + [copy.deepcopy(original[1])], original[1:],
                     original + [{**original[1], 'launch_id': '0' * 32}]):
            with self.subTest(rows=len(rows)):
                self.bindings = rows
                self.assertFalse(self.result()['verified'])

    def test_abnormal_or_finalize_failed_state_cannot_be_overridden_by_expected_kill(self):
        self.launches[1].update(role='nonplugin_worker', lifecycle='may_terminate', returncode=-9,
                                expectation={'explicit': True, 'command_sha256': 'f' * 64, 'reason': 'synthetic deliberate kill'})
        self.bindings[1].update(role='nonplugin_worker', state='finalize_failed', finished=False,
                               plugin_classes=[], nonplugin_guard_armed=True)
        self.assertFalse(self.result()['verified'])

    def test_only_explicit_bound_nonplugin_termination_with_preexecution_evidence_is_positive(self):
        self.launches[1].update(role='nonplugin_worker', lifecycle='may_terminate', returncode=-9,
                                expectation={'explicit': True, 'command_sha256': 'f' * 64, 'reason': 'synthetic deliberate kill'})
        self.bindings[1].update(role='nonplugin_worker', state='native_ready', finished=False,
                               plugin_classes=[], nonplugin_guard_armed=True)
        self.assertTrue(self.result()['verified'])
        self.launches[1]['expectation'] = None
        self.assertFalse(self.result()['verified'])

    def test_expected_kill_without_native_guard_or_with_plugin_class_fails(self):
        self.launches[1].update(role='nonplugin_worker', lifecycle='may_terminate', returncode=-9,
                                expectation={'explicit': True, 'command_sha256': 'f' * 64, 'reason': 'synthetic deliberate kill'})
        self.bindings[1].update(role='nonplugin_worker', state='native_ready', finished=False, nonplugin_guard_armed=True)
        self.assertFalse(self.result()['verified'])
        self.bindings[1].update(plugin_classes=[], nonplugin_guard_armed=False)
        self.assertFalse(self.result()['verified'])

    def test_unexpected_unfinished_nonplugin_is_not_a_blanket_exception(self):
        self.bindings[1].update(finished=False, state='native_ready', plugin_classes=[])
        self.assertFalse(self.result()['verified'])

    def test_native_base_and_every_observed_plugin_origin_and_MRO_remain_mandatory(self):
        self.bindings[1]['plugin_classes'][0]['native_MRO'] = False
        self.assertFalse(self.result()['verified'])
        self.bindings[1]['plugin_classes'][0]['native_MRO'] = True
        self.bindings[1]['plugin_classes'][0]['origin'] = 'fixture/foreign/__init__.py'
        self.assertFalse(self.result()['verified'])
        self.bindings[1]['plugin_classes'][0]['origin'] = self.contract['source_origin']
        self.bindings[1]['memory_provider_sha256'] = '0' * 64
        self.assertFalse(self.result()['verified'])

    def test_no_plugin_loaded_normal_native_child_can_finish_without_fake_MRO(self):
        self.bindings[1]['plugin_classes'] = []
        self.assertTrue(self.result()['verified'])

    def test_bootstrap_failure_missing_and_empty_launch_inventory_fails(self):
        self.bindings[1].update(started=False, state='bootstrap_failed', finished=False, plugin_classes=[])
        self.assertFalse(self.result()['verified'])
        self.launches.clear()
        self.bindings.clear()
        self.assertFalse(self.result()['verified'])


class RecorderBootstrapContract(unittest.TestCase):
    def test_recorder_exists_and_durably_tracks_distinct_launch_intent_creation_and_exit(self):
        path = SCRIPTS / 'ci_process.py'
        self.assertTrue(path.is_file(), 'real relevant launch recorder is missing')
        process = load('ci_process')
        root = Path(os.environ['MW_CI_UNIT_FIXTURES']) / 'launch-state'
        root.mkdir()
        recorder = process.LaunchRecorder({'run_id': 'a' * 32, 'runroot': str(root), 'executable': sys.executable}, 'controller-' + 'a' * 32)
        command = [sys.executable, '-B', 'fixture/never-launched.py']
        first, env = recorder.plan(command, {})
        second, _ = recorder.plan(command, {})
        self.assertNotEqual(first['launch_id'], second['launch_id'])
        self.assertEqual(env['MW_CI_LAUNCH_ID'], first['launch_id'])
        target = root / 'launches' / (first['launch_id'] + '.json')
        self.assertEqual(json.loads(target.read_text(encoding='utf-8'))['status'], 'planned')
        recorder.created(first, 404)
        recorder.exited(first, -9)
        saved = json.loads(target.read_text(encoding='utf-8'))
        self.assertEqual(saved['pid'], 404)
        self.assertEqual(saved['status'], 'exited')
        self.assertEqual(saved['returncode'], -9)
        self.assertEqual(saved['role'], 'plugin_capable')
        self.assertEqual(saved['lifecycle'], 'must_finish')

    def test_foreign_and_combined_no_site_command_shapes_are_durably_refused(self):
        self.assertTrue((SCRIPTS / 'ci_process.py').is_file(), 'unrecognized launch handling missing')
        process = load('ci_process')
        root = Path(os.environ['MW_CI_UNIT_FIXTURES']) / 'refused-shapes'
        root.mkdir()
        recorder = process.LaunchRecorder({'run_id': 'a' * 32, 'runroot': str(root), 'executable': sys.executable}, 'owner')
        for command in ([sys.executable, '-BS', '-c', 'pass'], ['fixture/foreign-python', '-c', 'pass']):
            with self.assertRaises(RuntimeError):
                recorder.plan(command, {})
        rows = [json.loads(p.read_text(encoding='utf-8')) for p in (root / 'launches').glob('*.json')]
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row['status'] == 'refused_shape' for row in rows))

    def test_unknown_audit_launch_is_recorded_before_refusal(self):
        self.assertTrue((SCRIPTS / 'ci_process.py').is_file(), 'unknown audit launches are not inventoried')
        process = load('ci_process')
        root = Path(os.environ['MW_CI_UNIT_FIXTURES']) / 'unknown-event'
        root.mkdir()
        recorder = process.LaunchRecorder({'run_id': 'a' * 32, 'runroot': str(root), 'executable': sys.executable}, 'owner')
        with self.assertRaises(RuntimeError):
            recorder.audit('os.fork', ())  # Direct handler call: NO process creation.
        rows = [json.loads(p.read_text(encoding='utf-8')) for p in (root / 'launches').glob('*.json')]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['role'], 'unknown')
        self.assertEqual(rows[0]['status'], 'unrecognized_launch')

    def test_nonplugin_expectation_is_command_bound_scoped_and_not_an_ambient_flag(self):
        self.assertTrue((SCRIPTS / 'ci_process.py').is_file(), 'explicit lifecycle expectation missing')
        process = load('ci_process')
        root = Path(os.environ['MW_CI_UNIT_FIXTURES']) / 'expected-worker'
        root.mkdir()
        worker = root / 'worker.py'
        worker.write_text('pass\n', encoding='utf-8')
        recorder = process.LaunchRecorder({'run_id': 'a' * 32, 'runroot': str(root), 'executable': sys.executable}, 'owner')
        command = [sys.executable, '-B', str(worker)]
        with recorder.expect_nonplugin(command, 'synthetic deliberate timeout worker'):
            expected, _ = recorder.plan(command, {'MW_CI_ROLE': 'plugin'})
            normal, _ = recorder.plan(command, {'MW_CI_ROLE': 'nonplugin_worker'})
        self.assertEqual(expected['role'], 'nonplugin_worker')
        self.assertEqual(expected['lifecycle'], 'may_terminate')
        self.assertEqual(expected['expectation']['command_sha256'], expected['command_sha256'])
        self.assertEqual(expected['expectation']['script_sha256'], hashlib.sha256(worker.read_bytes()).hexdigest())
        self.assertEqual(normal['role'], 'plugin_capable')
        self.assertEqual(normal['lifecycle'], 'must_finish')

    def test_finalize_scan_error_is_durable_before_abnormal_exit(self):
        bootstrap = load('ci_bootstrap')
        self.assertTrue(hasattr(bootstrap, 'finalize_receipt'), 'finalization failure must be durably published')
        root = Path(os.environ['MW_CI_UNIT_FIXTURES']) / 'finalize-error'
        root.mkdir()
        target = root / 'binding.json'
        contract, launches, bindings = fixtures()
        receipt = bindings[1]
        receipt.update(finished=False, state='native_ready', plugin_classes=[])
        observed = []
        def broken_scan():
            raise ValueError('synthetic scanner fault')
        def record_exit(code):
            observed.append((code, json.loads(target.read_text(encoding='utf-8'))))
        bootstrap.finalize_receipt(receipt, target, broken_scan, exit_func=record_exit)
        self.assertEqual(observed[0][0], 86)
        self.assertEqual(observed[0][1]['state'], 'finalize_failed')
        self.assertFalse(observed[0][1]['finished'])
        self.assertIn('finalize_failed', observed[0][1]['violations'])
        self.assertFalse(coverage(load('memory_wiki_ci'), contract, launches, [bindings[0], observed[0][1]])['verified'])

    def test_bootstrap_failure_publication_precedes_exit_even_before_native_ready(self):
        bootstrap = load('ci_bootstrap')
        self.assertTrue(hasattr(bootstrap, 'publish_failure'), 'bootstrap failures need durable state, not only stderr')
        root = Path(os.environ['MW_CI_UNIT_FIXTURES']) / 'bootstrap-error'
        root.mkdir()
        target = root / 'binding.json'
        contract, launches, bindings = fixtures()
        receipt = bindings[1]
        bootstrap.publish_failure(receipt, target, 'bootstrap_failed', ValueError('synthetic failure'))
        saved = json.loads(target.read_text(encoding='utf-8'))
        self.assertEqual(saved['state'], 'bootstrap_failed')
        self.assertFalse(saved['finished'])
        self.assertIn('bootstrap_failed', saved['violations'])
        self.assertFalse(coverage(load('memory_wiki_ci'), contract, launches, [bindings[0], saved])['verified'])

    def test_plugin_execution_observed_but_class_missing_cannot_be_native_green(self):
        module = load('memory_wiki_ci')
        contract, launches, bindings = fixtures()
        bindings[1].update(plugin_attempted=True, plugin_classes=[])
        self.assertFalse(coverage(module, contract, launches, bindings)['verified'])

    def test_production_lane_and_aggregate_recompute_coverage_from_uploaded_inventory(self):
        module = load('memory_wiki_ci')
        self.assertTrue(hasattr(module, 'verify_lane_bindings'), 'lane/aggregate must share real binding verifier')
        contract, launches, bindings = fixtures()
        origins = {'native_MRO': True, 'modules': {'agent.memory_provider': {
            'origin': contract['memory_provider_origin'], 'sha256': contract['memory_provider_sha256']}}}
        self.assertTrue(module.verify_lane_bindings(launches, bindings, contract, origins)['verified'])
        self.assertFalse(module.verify_lane_bindings(launches, bindings[:-1], contract, origins)['verified'])
        tree = ast.parse((SCRIPTS / 'memory_wiki_ci.py').read_bytes())
        main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'main')
        calls = [n for n in ast.walk(main) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == 'verify_lane_bindings']
        self.assertEqual(len(calls), 2, 'both hosted lane and downloaded aggregate must revalidate actual inventory')
        self.assertIn("public / 'launches.json'", (SCRIPTS / 'memory_wiki_ci.py').read_text(encoding='utf-8'))

    def test_bootstrap_documentation_requires_registration_and_distinct_trusted_workflow_ref(self):
        text = (SCRIPTS / 'README.md').read_text(encoding='utf-8')
        for phrase in ('default main', 'workflow registration', 'trusted workflow ref', 'source_sha', 'CI-only', 'no force push'):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)
        workflow = (SCRIPTS.parents[1] / '.github/workflows/memory-wiki-synthetic.yml').read_text(encoding='utf-8')
        self.assertIn('workflow_dispatch:', workflow)
        self.assertNotIn('  push:', workflow)
        self.assertNotIn('  pull_request:', workflow)
        self.assertIn('public/launches.json', workflow)
        self.assertIn('public/binding-coverage.json', workflow)
        self.assertIn('binding_cases.py', workflow)


if __name__ == '__main__':
    unittest.main()
