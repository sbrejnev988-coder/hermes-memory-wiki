"""Standalone stdlib tests; NOT Memory Wiki native integration evidence."""
import importlib.util
import pathlib
import tempfile
import unittest

SCRIPT = pathlib.Path(__file__).resolve().parents[2] / 'scripts/ci_owned/memory_wiki_ci.py'

class ReceiptContract(unittest.TestCase):
    def test_skipped_junit_is_not_counted_as_pass(self):
        self.assertTrue(SCRIPT.is_file(), 'CI receipt implementation is missing')
        spec = importlib.util.spec_from_file_location('ci_receipt', SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / 'junit.xml'
            path.write_text('<testsuites><testsuite tests="2" errors="0" failures="0" skipped="1"><testcase name="a"/><testcase name="b"><skipped message="Windows only"/></testcase></testsuite></testsuites>', encoding='utf-8')
            result = module.junit_summary(path)
        self.assertEqual(result['passed'], 1)
        self.assertEqual(result['skipped'], 1)
        self.assertFalse(result['all_passed'])

    def test_child_environment_drops_credentials_and_live_paths(self):
        spec = importlib.util.spec_from_file_location('ci_receipt', SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertTrue(hasattr(module, 'clean_environment'), 'synthetic-only environment boundary missing')
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            env = module.clean_environment({'PATH': 'toolpath', 'SystemRoot': 'C:/Windows', 'OPENAI_API_KEY': 'not-a-real-key', 'HERMES_HOME': 'live', 'GITHUB_TOKEN': 'not-a-real-token', 'APPDATA': 'live'}, root, root / 'core', root / 'source')
        self.assertNotIn('OPENAI_API_KEY', env)
        self.assertNotIn('GITHUB_TOKEN', env)
        self.assertNotEqual(env['HERMES_HOME'], 'live')
        self.assertNotEqual(env['APPDATA'], 'live')
        self.assertIn(str(root / 'core'), env['PYTHONPATH'])

    def test_native_gate_refuses_local_execution(self):
        spec = importlib.util.spec_from_file_location('ci_receipt', SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertTrue(hasattr(module, 'require_hosted'), 'hosted-only admission missing')
        for env in ({}, {'GITHUB_ACTIONS': 'true'}, {'GITHUB_ACTIONS': 'true', 'RUNNER_ENVIRONMENT': 'self-hosted'}):
            with self.assertRaises(RuntimeError):
                module.require_hosted(env)
        module.require_hosted({'GITHUB_ACTIONS': 'true', 'RUNNER_ENVIRONMENT': 'github-hosted'})

    def test_timeout_preserves_log_and_incomplete_receipt(self):
        import json
        import subprocess
        spec = importlib.util.spec_from_file_location('ci_receipt', SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertTrue(hasattr(module, 'execute_child'), 'bounded child receipt missing')
        def fake_run(command, **kwargs):
            kwargs['stdout'].write(b'synthetic-failure-log\n')
            raise subprocess.TimeoutExpired(command, kwargs['timeout'])
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            receipt = module.execute_child(['synthetic-never-launched'], root, {}, root, 1, run=fake_run)
            self.assertEqual(receipt['status'], 'incomplete_timeout')
            self.assertFalse(receipt['accepted'])
            self.assertEqual((root / 'pytest.log').read_bytes(), b'synthetic-failure-log\n')
            self.assertEqual(json.loads((root / 'execution.json').read_text())['status'], 'incomplete_timeout')

    def test_remote_network_denied_without_native_import(self):
        bootstrap = SCRIPT.with_name('ci_bootstrap.py')
        self.assertTrue(bootstrap.is_file(), 'synthetic runtime network guard missing')
        spec = importlib.util.spec_from_file_location('ci_bootstrap_test', bootstrap)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertTrue(module.is_loopback('127.0.0.1'))
        self.assertTrue(module.is_loopback('::1'))
        self.assertFalse(module.is_loopback('api.openai.com'))
        self.assertFalse(module.is_loopback('8.8.8.8'))
        with self.assertRaises(PermissionError):
            module.network_audit('socket.connect', (None, ('api.openai.com', 443)))
        module.network_audit('socket.connect', (None, ('127.0.0.1', 8080)))

    def test_metadata_preflight_reads_exact_git_without_plugin_import(self):
        import sys
        spec = importlib.util.spec_from_file_location('ci_receipt', SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertTrue(hasattr(module, 'source_inventory'), 'exact-source metadata binding missing')
        import os
        baseline = pathlib.Path(os.environ.get('MW_CI_METADATA_SOURCE', str(SCRIPT.parents[3] / 'publication-20261004T0520Z')))
        expected = os.environ.get('MW_CI_METADATA_SHA', '438e0b57cb44470c2d47b9210941bea177d379f1')
        result = module.source_inventory(baseline, expected)
        self.assertEqual(result['sha'], expected)
        self.assertIn('__init__.py', result['files'])
        self.assertNotIn('memory_wiki', sys.modules)
        with self.assertRaises(ValueError):
            module.source_inventory(baseline, '438e0b57')

    def test_matrix_requires_real_pass_for_every_collected_node(self):
        spec = importlib.util.spec_from_file_location('ci_receipt', SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertTrue(hasattr(module, 'matrix_coverage'), 'cross-platform no-skip-as-pass coverage missing')
        records = []
        for platform in ('linux', 'win32'):
            for stage in ('full', 'recovery'):
                records.append({'platform': platform, 'python': '3.14', 'stage': stage, 'source_sha': 'a' * 40, 'source_digest': 'same', 'core_sha': module.CORE_SHA, 'complete': True, 'bindings_verified': True, 'collected': ['a', 'b'], 'passed': ['a'] if stage == 'full' else ['a', 'b'], 'skipped': ['b'] if stage == 'full' else [], 'failed': [], 'errors': []})
        with self.assertRaises(RuntimeError):
            module.matrix_coverage(records, 'a' * 40, versions=['3.14'])
        records[2]['passed'] = ['a', 'b']
        records[2]['skipped'] = []
        result = module.matrix_coverage(records, 'a' * 40, versions=['3.14'])
        self.assertTrue(result['accepted'])
        self.assertEqual(result['platform_skips'], 1)
        with self.assertRaises(RuntimeError):
            module.matrix_coverage(records[:-1], 'a' * 40, versions=['3.14'])

    def test_teardown_error_cannot_be_counted_as_pass(self):
        spec = importlib.util.spec_from_file_location('ci_receipt', SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertTrue(hasattr(module, 'classify_phases'), 'phase-aware completion missing')
        rows = [{'nodeid': 'case', 'when': when, 'outcome': outcome} for when, outcome in [('setup', 'passed'), ('call', 'passed'), ('teardown', 'failed')]]
        result = module.classify_phases({'collected': ['case'], 'phases': rows, 'collection_errors': [], 'session_finished': True, 'exitstatus': 1})
        self.assertEqual(result['passed'], [])
        self.assertEqual(result['errors'], ['case'])
        self.assertFalse(result['complete'])

    def test_runtime_hook_is_explicit_and_stdlib_unit_only(self):
        import json
        spec = importlib.util.spec_from_file_location('ci_receipt', SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertTrue(hasattr(module, 'prepare_runtime'), 'child .pth bindings installer missing')
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            purelib = root / 'stdlib-unit-purelib'
            purelib.mkdir()
            config = root / 'synthetic-runtime.json'
            config.write_text(json.dumps({'core': 'unit-data-not-loaded'}), encoding='utf-8')
            target = module.prepare_runtime(purelib, SCRIPT.parent, config)
            text = target.read_text(encoding='utf-8')
            self.assertIn('import ci_bootstrap; ci_bootstrap.configure(', text)
            self.assertIn(repr(str(config.resolve())), text)
            self.assertNotIn('sys.modules', text)

if __name__ == '__main__':
    unittest.main()
