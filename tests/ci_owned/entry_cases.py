"""CI-NONPLUGIN-ENTRY-01: реальные expectation/plan, но ни один argv не исполняется.

Синтетические dictionaries из старых fixtures не доказывают native SDK/MRO/runtime.
"""
import hashlib
import json
import os
from pathlib import Path
import sys
import unittest
from binding_cases import fixtures, load

OBSERVATIONS = []


class ScriptOperandContract(unittest.TestCase):
    def setUp(self):
        self.module = load('ci_process')
        self.root = Path(os.environ['MW_CI_UNIT_FIXTURES']) / ('entry-' + self._testMethodName)
        self.root.mkdir()
        self.worker = self.root / 'reviewed-worker.py'
        self.data = self.root / 'data.py'
        for path in (self.worker, self.data):
            path.write_bytes(b'raise AssertionError("Unit fixture must never execute")\n')
        self.recorder = self.module.LaunchRecorder({'run_id': 'a' * 32, 'runroot': str(self.root),
                                                  'executable': sys.executable}, 'b' * 32)

    def refusal(self, label, argv):
        rejected = False
        planned = None
        try:
            with self.recorder.expect_nonplugin(argv, 'Проверяемый unit worker; команду не исполнять'):
                planned, _ = self.recorder.plan(argv, {})
        except ValueError:
            rejected = True
        OBSERVATIONS.append({'case': label, 'command': list(argv), 'expected': 'refused_nonplugin',
                             'refused': rejected, 'planned_role': planned['role'] if planned else None,
                             'actually_executed': False, 'synthetic_only': True})
        self.assertTrue(rejected, 'CI-NONPLUGIN-ENTRY-01: .py dataarg не является исполняемым script operand: ' + label)
        self.assertIsNone(getattr(self.recorder.local, 'expectation', None))

    def positive(self, label, argv, script=None):
        script = self.worker if script is None else script
        with self.recorder.expect_nonplugin(argv, 'Точный script operand, без выполнения'):
            planned, _ = self.recorder.plan(argv, {})
        OBSERVATIONS.append({'case': label, 'command': list(argv), 'expected': 'bound_script',
                             'planned': planned, 'actually_executed': False, 'synthetic_only': True})
        self.assertEqual(planned['role'], 'nonplugin_worker')
        self.assertEqual(planned['lifecycle'], 'may_terminate')
        self.assertTrue(planned['same_interpreter'])
        self.assertTrue(planned['site_enabled'])
        self.assertEqual(planned['expectation']['command_sha256'], self.module.command_digest(argv))
        self.assertEqual(planned['expectation']['script'], str(script.resolve()))
        self.assertEqual(planned['expectation']['script_sha256'], hashlib.sha256(script.read_bytes()).hexdigest())
        self.assertIsNone(getattr(self.recorder.local, 'expectation', None))
        return planned

    def test_inline_command_py_dataarg_is_not_script_entrypoint(self):
        for flags in ([], ['-B'], ['-u', '-W', 'ignore'], ['-X', 'utf8']):
            with self.subTest(flags=flags):
                self.refusal('inline_dataarg', [sys.executable, *flags, '-c', 'pass', str(self.worker)])

    def test_module_py_dataarg_is_not_script_entrypoint(self):
        for flags in ([], ['-B'], ['-Wdefault'], ['-Xutf8']):
            with self.subTest(flags=flags):
                self.refusal('module_dataarg', [sys.executable, *flags, '-m', 'never_executed_module', str(self.worker)])

    def test_non_py_script_cannot_borrow_py_argument_identity(self):
        for name in ('worker', 'worker.txt', 'worker.pyc'):
            actual = self.root / name
            actual.write_bytes(b'raise AssertionError("Not executed")\n')
            with self.subTest(name=name):
                self.refusal('other_script_dataarg', [sys.executable, str(actual), str(self.worker)])

    def test_stdin_no_operand_and_option_only_are_not_workers(self):
        commands = ([sys.executable], [sys.executable, '--'], [sys.executable, '-', str(self.worker)],
                    [sys.executable, '--', '-', str(self.worker)],
                    [sys.executable, '-W', str(self.worker)], [sys.executable, '-X', str(self.worker)],
                    [sys.executable, '-c', str(self.worker)], [sys.executable, '-m', str(self.worker)])
        for command in commands:
            with self.subTest(command=command):
                self.refusal('no_script_operand', command)

    def test_actual_script_accepts_py_data_arguments_without_ambiguity(self):
        for data in ([str(self.data)], [str(self.data), str(self.worker)], ['--file', str(self.data), 'plain']):
            with self.subTest(data=data):
                self.positive('script_with_dataargs', [sys.executable, str(self.worker), *data])

    def test_known_interpreter_flags_preserve_legitimate_script_binding(self):
        for flags in ([], ['-B'], ['-u'], ['-BO'], ['-bBEIuOq'], ['-s'], ['-B', '-u', '-OO', '-q']):
            with self.subTest(flags=flags):
                self.positive('known_flags', [sys.executable, *flags, str(self.worker)])

    def test_W_X_values_and_attached_flags_are_not_script_candidates(self):
        for flags in (['-W', str(self.data)], ['-X', str(self.data)],
                      ['-W' + str(self.data)], ['-X' + str(self.data)],
                      ['-B', '-W', str(self.data), '-X', str(self.data), '-u']):
            with self.subTest(flags=flags):
                self.positive('option_value_not_script', [sys.executable, *flags, str(self.worker)])

    def test_double_dash_proves_script_operand_including_leading_hyphen(self):
        self.positive('double_dash', [sys.executable, '-B', '--', str(self.worker), str(self.data)])
        odd = self.root / '-reviewed.py'
        odd.write_bytes(self.worker.read_bytes())
        old_cwd = Path.cwd()
        try:
            os.chdir(self.root)
            self.positive('double_dash_hyphen_script', [sys.executable, '--', '-reviewed.py'], odd)
        finally:
            os.chdir(old_cwd)

    def test_plugin_capable_and_primary_inline_module_routes_remain_admitted(self):
        for argv in ([sys.executable, '-c', 'pass', str(self.worker)],
                     [sys.executable, '-B', '-m', 'never_executed_module', str(self.worker)]):
            with self.subTest(argv=argv):
                row, _ = self.recorder.plan(argv, {})
                self.assertEqual(row['role'], 'plugin_capable')
                self.assertEqual(row['lifecycle'], 'must_finish')
                self.assertTrue(row['site_enabled'])
                with self.recorder.expect_primary(argv):
                    primary, _ = self.recorder.plan(argv, {})
                self.assertEqual(primary['role'], 'plugin')
                OBSERVATIONS.append({'case': 'ordinary_inline_module_route', 'command': list(argv),
                                     'planned_role': row['role'], 'primary_role': primary['role'], 'actually_executed': False})

    def test_site_unknown_foreign_and_shell_refusals_are_preserved(self):
        commands = ([sys.executable, '-S', str(self.worker)], [sys.executable, '-BS', str(self.worker)],
                    [sys.executable, '--unknown-ci-option', str(self.worker)],
                    ['fixture/foreign-python', str(self.worker)])
        for command in commands:
            with self.subTest(command=command):
                self.refusal('site_or_foreign_refused', command)
                with self.assertRaises(RuntimeError):
                    self.recorder.plan(command, {})
        with self.assertRaises(RuntimeError):
            self.recorder.plan([sys.executable, str(self.worker)], {}, shell=True)
        with self.assertRaises(RuntimeError):
            self.recorder.plan([sys.executable, str(self.worker)], {}, executable='fixture/foreign-python')
        with self.assertRaises(RuntimeError):
            self.recorder.plan('python reviewed-worker.py', {})

    def test_missing_directory_and_outside_runroot_are_not_reviewed_workers(self):
        directory = self.root / 'directory.py'
        directory.mkdir()
        outside = self.root.parent / (self._testMethodName + '.py')
        outside.write_bytes(self.worker.read_bytes())
        for script in (self.root / 'missing.py', directory, outside):
            with self.subTest(script=str(script)):
                self.refusal('unreviewed_script', [sys.executable, str(script)])

    def test_expectation_remains_single_use_exact_command_and_scoped(self):
        command = [sys.executable, '-B', str(self.worker)]
        different = command + ['data']
        with self.recorder.expect_nonplugin(command, 'Один точный argv'):
            mismatch, _ = self.recorder.plan(different, {})
            bound, _ = self.recorder.plan(command, {})
            second, _ = self.recorder.plan(command, {})
        outside, _ = self.recorder.plan(command, {'MW_CI_ROLE': 'nonplugin_worker'})
        self.assertEqual([row['role'] for row in (mismatch, bound, second, outside)],
                         ['plugin_capable', 'nonplugin_worker', 'plugin_capable', 'plugin_capable'])
        self.assertEqual(bound['expectation']['script_sha256'], hashlib.sha256(self.worker.read_bytes()).hexdigest())
        self.assertIsNone(getattr(self.recorder.local, 'expectation', None))
        for role, reason in (('unknown', 'reason'), ('nonplugin_worker', '')):
            with self.assertRaises(ValueError):
                with self.recorder.expectation(command, role, reason):
                    self.fail('Invalid explicit role/reason accepted')

    def test_native_ready_plugin_audit_denial_guard_is_retained_pure_seam(self):
        bootstrap = load('ci_bootstrap')
        contract, launches, bindings = fixtures()
        receipt = bindings[1]
        receipt.update(role='nonplugin_worker', state='native_ready', finished=False,
                       plugin_classes=[], plugin_attempted=False, nonplugin_guard_armed=True)
        target = self.root / 'denied-binding.json'
        with self.assertRaises(PermissionError):
            bootstrap.plugin_audit('import', ('memory_wiki',), {}, receipt, target)
        saved = json.loads(target.read_text(encoding='utf-8'))
        self.assertEqual(saved['state'], 'native_ready')
        self.assertFalse(saved['finished'])
        self.assertTrue(saved['plugin_attempted'])
        self.assertIn('nonplugin_plugin_execution_denied', saved['violations'])
        self.assertEqual(saved['plugin_classes'], [])
        OBSERVATIONS.append({'case': 'native_ready_denial_pure_seam', 'actually_executed': False,
                             'synthetic_native_fields': True, 'actual_native_runtime_or_MRO': False,
                             'denied_before_plugin_import': True, 'saved': saved})

    def test_options_after_script_are_data_and_do_not_change_entrypoint(self):
        for data in (['-c', 'pass'], ['-m', 'never_executed_module'], ['-S'], ['--unknown-ci-option'],
                     ['--', str(self.data)]):
            with self.subTest(data=data):
                self.positive('post_script_data', [sys.executable, str(self.worker), *data])


if __name__ == '__main__':
    unittest.main()
