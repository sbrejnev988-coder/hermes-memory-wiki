"""SOURCE/stdlib регрессии CI prerequisites; не native provider qualification."""
from __future__ import annotations

import ast
from collections import Counter
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE / 'scripts/ci_owned'))
from fixture_prerequisites import SOURCE_SUITES, clean_environment, native_pytest_args, no_links, suite_case_ids
from source_suites import CaseResult, case_report, run_unittest

# Actual test-method AST from authoritative a4e118e; setup/fixtures may change,
# not historical behavioral assertions, gold, fault injections or security tests.
ORIGINAL_TESTS = {
    'test_memory_diff_polarity.py': 'f150f6c71394ca3f75e210c8806f49c4e5955bcc81121ebc896b6ba0a449c4f9',
    'test_observation_finite_work.py': '3d3145b411768f4d7f92974838ecb833888e563a72c5fa09fd37a42da582a7e4',
    'test_observation_repair01.py': '84c16fab3c539bfd3c2aedcd27d1ec14191c792d49f1ba78bf54f9e357cf426e',
    'test_p2_g4_identity_errors.py': '8017b80c0d73939d4ad390d5ff77b65863b9feae04b39b83a46c416dad172d92',
    'test_p2_g4_repair01.py': 'e5354523774ed81ce4c7724770f93d683a657cdac9747abcbe27d00a5ec0da30',
    'test_prefetch_current_diagnostics.py': '14ea1da3cd12bb1848ed2eeb6cff09c89a4794134b84b41b18c6dc3ccbeb1540',
}


def tree(relative):
    return ast.parse((SOURCE / relative).read_bytes())


def load(relative, name):
    path = SOURCE / relative
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    exec(compile(path.read_bytes(), str(path), 'exec', dont_inherit=True), module.__dict__)
    return module


class PrerequisiteControls(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix='foundation-ci-'))

    def positive_rows(self):
        return {rel: {'sha256': hashlib.sha256((SOURCE / rel).read_bytes()).hexdigest(),
                      'exit_code': 0, 'total': count, 'passed': count,
                      'failed': 0, 'errors': 0, 'skipped': 0, 'case_ids': suite_case_ids(SOURCE, rel)}
                for rel, (_, count) in SOURCE_SUITES.items()}

    def test_clean_environment_drops_credentials_and_all_fixture_carriers(self):
        env = clean_environment(self.root, {
            'OPENAI_API_KEY': 'authored-not-real', 'TOKEN': 'authored-not-real',
            'PATH': 'foreign', 'PYTHONPATH': 'foreign', 'HERMES_HOME': 'foreign',
            'RECOVERY_DIAGNOSTIC_OUT': 'foreign', 'G4_FIXTURE': 'foreign',
            'G4_REPAIR_FIXTURE': 'foreign', 'AUDIT8_OBSERVATIONS': 'foreign',
        })
        for key in ('OPENAI_API_KEY', 'TOKEN', 'PATH', 'PYTHONPATH', 'RECOVERY_DIAGNOSTIC_OUT',
                    'G4_FIXTURE', 'G4_REPAIR_FIXTURE', 'AUDIT8_OBSERVATIONS'):
            self.assertNotIn(key, env)
        for key in ('HOME', 'USERPROFILE', 'LOCALAPPDATA', 'APPDATA', 'HERMES_HOME', 'TMP', 'TEMP', 'TMPDIR'):
            self.assertTrue(Path(env[key]).is_relative_to(self.root))
            self.assertTrue(Path(env[key]).is_dir())
        self.assertEqual(env['MEMORY_WIKI_SEMANTIC'], '0')
        self.assertEqual(env['MEMORY_WIKI_GRAPH_EXTRACT_ENABLED'], '0')

    def test_historical_test_bodies_are_byte_semantic_preserved(self):
        for name, expected in ORIGINAL_TESTS.items():
            with self.subTest(file=name):
                methods = [ast.dump(node, include_attributes=False) for node in ast.walk(tree('tests/' + name))
                           if isinstance(node, ast.FunctionDef) and node.name.startswith('test')]
                actual = hashlib.sha256(json.dumps(sorted(methods), ensure_ascii=True).encode()).hexdigest()
                self.assertEqual(actual, expected)

    def test_source_modules_import_without_external_environment_or_audit_install(self):
        old = dict(os.environ)
        try:
            for key in ('G4_FIXTURE', 'G4_REPAIR_FIXTURE', 'TMPDIR', 'HERMES_HOME', 'USERPROFILE'):
                os.environ.pop(key, None)
            for index, relative in enumerate(rel for rel, (owner, _) in SOURCE_SUITES.items()
                                             if owner != 'PrerequisiteControls'):
                module = load(relative, '_foundation_g4_' + str(index))
                self.assertIsNone(module.FIX)
                # No test execution/audit hook during collection.
                for node in tree(relative).body:
                    if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
                        self.assertNotEqual(ast.unparse(node.value.func), 'sys.addaudithook')
            self.assertNotIn('agent.memory_provider', sys.modules)
            self.assertNotIn('memory_wiki', sys.modules)
            self.assertNotIn('hermes_trust_core', sys.modules)
        finally:
            os.environ.clear()
            os.environ.update(old)

    def test_native_split_is_exact_and_requires_complete_source_roster(self):
        rows = self.positive_rows()
        expected = ['--ignore=' + str(SOURCE / rel) for rel in SOURCE_SUITES]
        self.assertEqual(native_pytest_args(SOURCE, rows), expected)
        for relative in rows:
            missing = copy.deepcopy(rows)
            del missing[relative]
            with self.assertRaises(RuntimeError):
                native_pytest_args(SOURCE, missing)
        extra = copy.deepcopy(rows)
        extra['tests/foreign.py'] = {}
        with self.assertRaises(RuntimeError):
            native_pytest_args(SOURCE, extra)

    def test_nonzero_failed_skipped_incomplete_or_drifted_source_blocks_native(self):
        original = self.positive_rows()
        relative = next(iter(original))
        for key, bad in [('exit_code', 1), ('exit_code', None), ('total', 0), ('passed', 7),
                         ('failed', 1), ('errors', 1), ('skipped', 1), ('sha256', '0' * 64),
                         ('exit_code', False), ('case_ids', []), ('passed', True)]:
            with self.subTest(field=key, value=bad):
                rows = copy.deepcopy(original)
                rows[relative][key] = bad
                with self.assertRaises(RuntimeError):
                    native_pytest_args(SOURCE, rows)

    def test_subtest_failure_is_not_parent_pass(self):
        class Inner(unittest.TestCase):
            def test_subtests(self):
                with self.subTest(control='negative'):
                    self.assertEqual('red', 'green')
                with self.subTest(control='positive'):
                    self.assertEqual('green', 'green')
        result = unittest.TextTestRunner(stream=io.StringIO(), resultclass=CaseResult).run(
            unittest.defaultTestLoader.loadTestsFromTestCase(Inner))
        report = case_report(result)
        self.assertEqual((report['total'], report['passed'], report['failed']), (1, 0, 1))
        self.assertEqual([row['outcome'] for row in report['subtests']], ['failed', 'passed'])

    def test_optional_trust_refuses_transitive_failure_and_required_absence(self):
        module = tree('tests/test_prefetch_current_diagnostics.py')
        scope = next(node for node in module.body if isinstance(node, ast.Try))
        self.assertEqual(ast.unparse(scope.body[0]), 'import hermes_trust_core as trust')
        handler = scope.handlers[0]
        self.assertEqual(ast.unparse(handler.type), 'ModuleNotFoundError')
        predicate = handler.body[0].test
        # Execute the genuine optionality predicate, not a substitute SDK/trust.
        code = compile(ast.Expression(predicate), '<optional-trust-predicate>', 'eval')
        for missing, required, refused in [('hermes_trust_core', None, False),
                                           ('hermes_trust_core', '1', True),
                                           ('trust_transitive_missing', None, True)]:
            error = ModuleNotFoundError(name=missing)
            env = {} if required is None else {'MW_REQUIRE_TRUST_CORE': required}
            from types import SimpleNamespace
            self.assertEqual(eval(code, {'error': error, 'os': SimpleNamespace(environ=env)}), refused)
        self.assertIsInstance(handler.body[0].body[0], ast.Raise)

    def test_portable_native_setup_supplies_all_declared_carriers(self):
        conftest = tree('tests/conftest.py')
        setup = next(node for node in conftest.body if isinstance(node, ast.FunctionDef) and node.name == 'portable_prerequisites')
        text = ast.unparse(setup)
        self.assertIn("monkeypatch.setattr(finite, 'FIXTURE', root)", text)
        self.assertIn("monkeypatch.setattr(request.module, 'FIXTURE', root)", text)
        for relative in ['tests/test_memory_diff_polarity.py', 'tests/test_observation_finite_work.py',
                         'tests/test_observation_repair01.py', 'tests/test_prefetch_current_diagnostics.py']:
            module = tree(relative)
            # No mandatory externally supplied fixture ENV at collection.
            for node in module.body:
                if isinstance(node, (ast.Assign, ast.AnnAssign, ast.Expr)):
                    self.assertNotIn('os.environ[', ast.unparse(node))

    def test_native_startup_gate_keeps_public_persistence_and_cleanup(self):
        module = tree('scripts/ci_owned/provider_startup.py')
        run = next(node for node in module.body if isinstance(node, ast.FunctionDef) and node.name == 'run')
        text = ast.unparse(run)
        self.assertIn("'memory_wiki_add_claim'", text)
        self.assertIn("saved.get('state') == 'stored'", text)
        self.assertIn("'memory_wiki_query'", text)
        self.assertIn('provider.shutdown()', text)
        self.assertIn('for reopened in (False, True)', text)
        self.assertNotIn('INSERT INTO', text)
        self.assertNotIn('unittest.mock', text)
        self.assertIn('plugin._sanitize_recalled is trust.sanitize_recalled', text)

    def test_changed_python_sources_compile_without_native_import(self):
        paths = ['scripts/ci_owned/fixture_prerequisites.py', 'scripts/ci_owned/source_suites.py',
                 'scripts/ci_owned/provider_startup.py', 'scripts/ci_owned/ci_child.py',
                 'scripts/ci_owned/memory_wiki_ci.py', 'packaging/run_native_regressions.py',
                 'tests/conftest.py', *('tests/' + name for name in ORIGINAL_TESTS)]
        for relative in paths:
            with self.subTest(file=relative):
                compile((SOURCE / relative).read_bytes(), str(SOURCE / relative), 'exec', dont_inherit=True)


if __name__ == '__main__':
    raise SystemExit(run_unittest(PrerequisiteControls, expected=10))
