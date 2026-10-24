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
from source_suites import (
    CASE_DIAGNOSTIC_SCHEMA, DIAGNOSTIC_CAP, DIAGNOSTIC_UNKNOWN,
    PUBLIC_DIAGNOSTIC_INPUTS, PUBLIC_INPUT_CAP, CaseResult, case_report,
    known_error_name, public_input_metadata, run_unittest, safe_error_type,
    source_failure_text, write_source_failure,
)

# Historical method gold, including the prior explicit current-pin migrations.
# Keep every captured parser profile below. The current hybrid G4 literal is
# inversely mapped at its single typed assertion operand before this recipe.
# These are the unchanged CPython 3.13/3.14 gold values. The exact producer below
# is parser-dependent; do not normalize AST fields or derive expected from actual.
ORIGINAL_TESTS = {
    'test_memory_diff_polarity.py': 'f150f6c71394ca3f75e210c8806f49c4e5955bcc81121ebc896b6ba0a449c4f9',
    'test_observation_finite_work.py': '3d3145b411768f4d7f92974838ecb833888e563a72c5fa09fd37a42da582a7e4',
    'test_observation_repair01.py': '84c16fab3c539bfd3c2aedcd27d1ec14191c792d49f1ba78bf54f9e357cf426e',
    'test_p2_g4_identity_errors.py': 'ea6341d85a25afc3f00fd79039046417bdd2b64ff15d75483474852bcb18f84e',
    'test_p2_g4_repair01.py': 'e5354523774ed81ce4c7724770f93d683a657cdac9747abcbe27d00a5ec0da30',
    'test_prefetch_current_diagnostics.py': '14ea1da3cd12bb1848ed2eeb6cff09c89a4794134b84b41b18c6dc3ccbeb1540',
}


# Independently captured on the same public0c six source files by actual
# CPython 3.11.9 / 3.12.10 parsers (not feature_version simulation or test runs).
# Raw source bindings and original profile SHA256 are documented in FOUNDATION_CI_RU.
ORIGINAL_TESTS_311 = {
    'test_memory_diff_polarity.py': '99a505cc36a75cdab1a52d76afead9a02d0073384add1cfb7686321d74ccc7c5',
    'test_observation_finite_work.py': '2192d1f2e17cca2270841d871ebb2e03345164bfe2ab47c810a6a35fc7caf3dd',
    'test_observation_repair01.py': 'bada0446bbd2a60444295e612b9f75d6bed12509ad58d677953e88e97bae6f09',
    'test_p2_g4_identity_errors.py': '69f2e0f6075bbe1fb67eaa15ecb116eb3811c93860c1b5fbdf8f937a6f46f0d1',
    'test_p2_g4_repair01.py': 'd0a2f0aaf9a720237a20674254c03505d27b59b606fc551ef6bfa379b718e857',
    'test_prefetch_current_diagnostics.py': '5783933ba6bac3ccd2c1eff2c798dcd5c09745f11f9a73e7528f11e0a6b723fa',
}
ORIGINAL_TESTS_312 = {
    'test_memory_diff_polarity.py': 'e8c1ea12d619aad7961cc7a5a2d265883b38db2f8e286f9cb0941915b5a82307',
    'test_observation_finite_work.py': '1c0a1563975dff93fa7fec7c817241d353c657735be941defd3e4402a33226b6',
    'test_observation_repair01.py': '7a77c9ad28dfc9e5a0a3e8153748d28da57637de2d3ae639f6fdc25dbc702d6d',
    'test_p2_g4_identity_errors.py': '3342beb477dde23f6c58fe2dd470a04a64abe0f8a101f464613c6b0d3e25ba38',
    'test_p2_g4_repair01.py': 'c23bb24dcc09207d2d6f7363b1652c5b3dff03c80a532d8842bf23550a25380a',
    'test_prefetch_current_diagnostics.py': '89cd437cef22aeb0dbb69c508bb0a2b14a1b7448ad8fbff7fd7786969592ce2f',
}


def original_tests_for_runtime(implementation, version):
    """Finite actual-parser gold selection; an unknown runtime is a refusal."""
    if (type(implementation) is not str or implementation != 'cpython'
            or type(version) is not tuple or len(version) != 2
            or any(type(part) is not int for part in version)):
        raise RuntimeError('unsupported_ast_gold_runtime')
    if version == (3, 11):
        return ORIGINAL_TESTS_311
    if version == (3, 12):
        return ORIGINAL_TESTS_312
    if version in ((3, 13), (3, 14)):
        return ORIGINAL_TESTS
    raise RuntimeError('unsupported_ast_gold_runtime')


def historical_method_dumps(module, name):
    """Exact typed inverse, not hash substitution or AST field normalization."""
    module = copy.deepcopy(module)
    if name == 'test_p2_g4_identity_errors.py':
        owners = [n for n in module.body if isinstance(n, ast.ClassDef) and n.name == 'G4Tests']
        if len(owners) != 1:
            raise RuntimeError('g4_pin_owner')
        methods = [n for n in owners[0].body if isinstance(n, ast.FunctionDef)
                   and n.name == 'test_08_direct_boundary_preservation_and_network_denial']
        if len(methods) != 1:
            raise RuntimeError('g4_pin_method')
        pins = [n for n in ast.walk(methods[0]) if isinstance(n, ast.Call)
                and ast.unparse(n.func) == 'self.assertEqual' and len(n.args) == 2
                and ast.unparse(n.args[0]) == "hashlib.sha256((SOURCE / '__init__.py').read_bytes()).hexdigest()"]
        if (len(pins) != 1 or not isinstance(pins[0].args[1], ast.Constant)
                or type(pins[0].args[1].value) is not str
                or pins[0].args[1].value != '44cdca1b753f13650fcb9c9fb9bdec9192a9f7c11cdffbe91163abe64dd02805'):
            raise RuntimeError('g4_current_literal_pin')
        pins[0].args[1].value = '8007b015f204a0b673e7cf41410fe609f60b8151bd39d9042a53336de7fdaf09'
    return [ast.dump(node, include_attributes=False) for node in ast.walk(module)
            if isinstance(node, ast.FunctionDef) and node.name.startswith('test')]


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
        for name, expected in original_tests_for_runtime(sys.implementation.name, tuple(sys.version_info[:2])).items():
            with self.subTest(file=name):
                methods = historical_method_dumps(tree('tests/' + name), name)
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


class CompatibilityDiagnosticControls(unittest.TestCase):
    """Explicit tooling UNIT/SOURCE roster, not part of the shipped 8+2+10 gate.

    The lane entry extracts these pure controls and real metadata validators;
    it never executes G4, a native main, the public-input reader or the provider.
    """
    __test__ = False

    def setUp(self):
        self.rosters = {rel: suite_case_ids(SOURCE, rel) for rel in SOURCE_SUITES}
        self.rows = {
            rel: {'sha256': hashlib.sha256((SOURCE / rel).read_bytes()).hexdigest(),
                  'exit_code': 0, 'total': count, 'passed': count, 'failed': 0,
                  'errors': 0, 'skipped': 0, 'case_ids': self.rosters[rel],
                  'cases': [{'id': identity, 'outcome': 'passed'} for identity in self.rosters[rel]],
                  'diagnostics': {'schema': CASE_DIAGNOSTIC_SCHEMA, 'case_error_types': {}}}
            for rel, (_, count) in SOURCE_SUITES.items()
        }

    def decode(self, rows=None, public_inputs=None):
        text = source_failure_text(self.rows if rows is None else rows, self.rosters, public_inputs)
        self.assertLessEqual(len(text.encode('ascii')), DIAGNOSTIC_CAP)
        self.assertTrue(text.startswith('SOURCE_FAILURE_DIAGNOSTIC '))
        return text, json.loads(text.partition(' ')[2])

    def qualifier(self, validator, reporter):
        # Only the genuine owning failure boundary, never native main/imports.
        module = tree('scripts/ci_owned/source_suites.py')
        nodes = [n for n in module.body if isinstance(n, ast.FunctionDef) and n.name == 'qualified_native_args']
        self.assertEqual(len(nodes), 1)
        namespace = {'native_pytest_args': validator, 'emit_source_failure': reporter}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), '<source-qualifier-boundary>', 'exec'), namespace)
        return namespace['qualified_native_args']

    def test_selector_keeps_all_literal_profiles_and_current_gold(self):
        for version, gold in [((3, 11), ORIGINAL_TESTS_311), ((3, 12), ORIGINAL_TESTS_312),
                              ((3, 13), ORIGINAL_TESTS), ((3, 14), ORIGINAL_TESTS)]:
            self.assertIs(original_tests_for_runtime('cpython', version), gold)
            self.assertEqual(set(gold), set(ORIGINAL_TESTS))
            self.assertEqual(len(gold), 6)
        self.assertEqual(ORIGINAL_TESTS['test_p2_g4_identity_errors.py'],
                         'ea6341d85a25afc3f00fd79039046417bdd2b64ff15d75483474852bcb18f84e')
        self.assertEqual(ORIGINAL_TESTS_311['test_p2_g4_identity_errors.py'],
                         '69f2e0f6075bbe1fb67eaa15ecb116eb3811c93860c1b5fbdf8f937a6f46f0d1')
        self.assertEqual(ORIGINAL_TESTS_312['test_p2_g4_identity_errors.py'],
                         '3342beb477dde23f6c58fe2dd470a04a64abe0f8a101f464613c6b0d3e25ba38')

    def test_selector_refuses_unknown_and_malformed_runtime_without_skip(self):
        inputs = [('pypy', (3, 11)), ('CPython', (3, 11)), (None, (3, 14)),
                  ('cpython', (3, 10)), ('cpython', (3, 15)), ('cpython', (4, 11)),
                  ('cpython', [3, 11]), ('cpython', (3, True)), ('cpython', (3.0, 11)),
                  ('cpython', (3, '11')), ('cpython', (3, 11, 9)), ('cpython', None)]
        for index, (implementation, version) in enumerate(inputs):
            with self.subTest(index=index), self.assertRaisesRegex(RuntimeError, '^unsupported_ast_gold_runtime$'):
                original_tests_for_runtime(implementation, version)

    def test_error_types_never_read_foreign_metadata_or_stringify_payload(self):
        class HostileMeta(type):
            def __getattribute__(self, name):
                raise AssertionError('foreign metadata must not be read')
        class Foreign(Exception, metaclass=HostileMeta):
            pass
        class Payload:
            def __str__(self):
                raise AssertionError('foreign str must not be called')
            def __repr__(self):
                raise AssertionError('foreign repr must not be called')
        self.assertEqual(safe_error_type((AssertionError, Payload(), None)), 'AssertionError')
        self.assertEqual(safe_error_type((Foreign, Payload(), None)), 'UNKNOWN')
        self.assertEqual(safe_error_type(Payload()), 'UNKNOWN')
        self.assertEqual(known_error_name(Payload()), 'UNKNOWN')
        self.assertEqual(known_error_name('authored-secret-type-name'), 'UNKNOWN')

    def test_case_result_retains_parent_subtest_failure_and_typed_error(self):
        class Inner(unittest.TestCase):
            def test_healthy(self):
                self.assertTrue(True)
            def test_error(self):
                raise RuntimeError('authored-not-for-console')
            def test_subtests(self):
                with self.subTest(payload='authored-not-for-console'):
                    self.assertEqual('red', 'green')
                with self.subTest(payload='healthy'):
                    self.assertTrue(True)
        class QuietResult(CaseResult):
            def _exc_info_to_string(self, error, test):
                return 'authored inner failure; raw capture intentionally not rendered here'
        result = unittest.TextTestRunner(stream=io.StringIO(), resultclass=QuietResult).run(
            unittest.defaultTestLoader.loadTestsFromTestCase(Inner))
        report = case_report(result)
        self.assertEqual(report['schema'], 'memory-stack.source-suites/v1')
        self.assertEqual((report['total'], report['passed'], report['failed'], report['errors']), (3, 1, 1, 1))
        self.assertEqual([row['outcome'] for row in report['subtests']], ['failed', 'passed'])
        self.assertEqual(report['diagnostics']['schema'], CASE_DIAGNOSTIC_SCHEMA)
        self.assertEqual(sorted(report['diagnostics']['case_error_types'].values()), ['AssertionError', 'RuntimeError'])
        self.assertIn('authored-not-for-console', report['subtests'][0]['id'])

    def test_failed_case_diagnostic_is_bounded_and_omits_raw_subtest_payload(self):
        relative = next(iter(SOURCE_SUITES))
        row = self.rows[relative]
        row.update(exit_code=1, passed=row['total'] - 1, failed=1,
                   subtests=[{'id': 'authored-secret-payload', 'error': 'authored-secret-payload'}],
                   error_type='authored-secret-payload', message='authored-secret-payload')
        row['cases'][0]['outcome'] = 'failed'
        identity = self.rosters[relative][0]
        row['diagnostics']['case_error_types'][identity] = 'AssertionError'
        text, report = self.decode()
        self.assertNotIn('authored-secret-payload', text)
        self.assertEqual(report['boundary'], 'SOURCE_NOT_NATIVE')
        suite = report['suites'][0]
        self.assertEqual((suite['suite'], suite['outcome'], suite['error_type']), (relative, 'failed', 'UNKNOWN'))
        self.assertEqual(suite['cases'], [{'id': identity, 'outcome': 'failed', 'error_type': 'AssertionError'}])
        self.assertEqual(suite['captures'], ['suite-0/stdout.log', 'suite-0/stderr.log'])

    def test_malformed_case_metadata_stays_unknown_not_pass(self):
        relative = next(iter(SOURCE_SUITES))
        for bad in (None, {}, [], [{'id': 'authored-secret-payload', 'outcome': 'passed'}]):
            rows = copy.deepcopy(self.rows)
            rows[relative]['cases'] = bad
            text, report = self.decode(rows)
            self.assertNotIn('authored-secret-payload', text)
            self.assertEqual(report['suites'][0]['outcome'], 'UNKNOWN')
            self.assertTrue(all(row['outcome'] == 'UNKNOWN' for row in report['suites'][0]['cases']))
        for field, bad in [('total', True), ('passed', True), ('exit_code', False), ('exit_code', None)]:
            rows = copy.deepcopy(self.rows)
            rows[relative][field] = bad
            self.assertEqual(self.decode(rows)[1]['suites'][0]['outcome'], 'UNKNOWN')

    def test_missing_report_exposes_only_known_timeout_type_and_unknown_cases(self):
        relative = next(iter(SOURCE_SUITES))
        rows = {relative: {'error_type': 'TimeoutError', 'exit_code': None, 'message': 'authored-secret-payload'}}
        text, report = self.decode(rows)
        self.assertNotIn('authored-secret-payload', text)
        self.assertEqual(report['suites'][0]['error_type'], 'TimeoutError')
        self.assertTrue(all(suite['outcome'] == 'UNKNOWN' for suite in report['suites']))
        self.assertEqual(sum(len(suite['cases']) for suite in report['suites']), 20)

    def test_public_layout_is_bytes_only_fixed_inputs_and_exact_eol_counts(self):
        raw = b'a\r\nb\nc\rd'
        relative = PUBLIC_DIAGNOSTIC_INPUTS[0]
        row = public_input_metadata(relative, raw)
        self.assertEqual(row, {'input': relative, 'status': 'known', 'B': len(raw),
                               'sha256': hashlib.sha256(raw).hexdigest(), 'crlf': 1, 'lf_only': 1, 'cr_only': 1})
        for bad in (None, 'authored-secret-payload', bytearray(raw), b'x' * (PUBLIC_INPUT_CAP + 1)):
            self.assertEqual(public_input_metadata(relative, bad), {'input': relative, 'status': 'UNKNOWN'})
        with self.assertRaises(ValueError):
            public_input_metadata('foreign/auth.json', raw)
        text, report = self.decode(public_inputs={relative: raw, 'foreign/auth.json': b'authored-secret-payload'})
        self.assertNotIn('authored-secret-payload', text)
        self.assertNotIn('foreign/auth.json', text)
        self.assertEqual([item['input'] for item in report['public_inputs']], list(PUBLIC_DIAGNOSTIC_INPUTS))

    def test_secondary_formatter_stream_and_cancel_failures_are_nonthrowing(self):
        stream = io.StringIO()
        write_source_failure(self.rows, {}, {}, stream)
        self.assertEqual(stream.getvalue(), DIAGNOSTIC_UNKNOWN)
        class BrokenStream:
            def __init__(self, on_flush):
                self.writes = []
                self.on_flush = on_flush
            def write(self, text):
                self.writes.append(text)
                if not self.on_flush:
                    raise KeyboardInterrupt('authored-secondary')
            def flush(self):
                raise SystemExit('authored-secondary')
        for on_flush in (False, True):
            broken = BrokenStream(on_flush)
            write_source_failure(self.rows, self.rosters, {}, broken)
            self.assertEqual(len(broken.writes), 2)
            self.assertEqual(broken.writes[-1], DIAGNOSTIC_UNKNOWN)

    def test_real_strict_qualifier_primary_survives_each_secondary_failure(self):
        relative = next(iter(SOURCE_SUITES))
        for secondary in (RuntimeError('authored-secondary'), KeyboardInterrupt(), SystemExit(17)):
            primaries = []
            def validator(source, rows):
                try:
                    return native_pytest_args(source, rows)
                except BaseException as error:
                    primaries.append(error)
                    raise
            def reporter(source, rows):
                raise secondary
            rows = copy.deepcopy(self.rows)
            rows[relative]['passed'] -= 1
            try:
                self.qualifier(validator, reporter)(SOURCE, rows)
            except BaseException as caught:
                self.assertIs(caught, primaries[0])
                self.assertEqual(caught.args, ('source_suite_not_qualified:' + relative,))
            else:
                self.fail('strict failure continued')

    def test_real_metadata_validator_positive_and_bad_rows_keep_fail_closed(self):
        reports = []
        invoke = self.qualifier(native_pytest_args, lambda source, rows: reports.append(True))
        self.assertEqual(invoke(SOURCE, self.rows), ['--ignore=' + str(SOURCE / rel) for rel in SOURCE_SUITES])
        self.assertEqual(reports, [])
        relative = next(iter(SOURCE_SUITES))
        bad_inputs = []
        for field, bad in [('exit_code', 1), ('exit_code', False), ('total', 0), ('passed', True),
                           ('failed', 1), ('errors', 1), ('skipped', 1), ('sha256', '0' * 64), ('case_ids', [])]:
            rows = copy.deepcopy(self.rows)
            rows[relative][field] = bad
            bad_inputs.append(rows)
        bad_inputs.extend([{}, None])
        for rows in bad_inputs:
            with self.assertRaises((RuntimeError, TypeError)):
                invoke(SOURCE, rows)
        self.assertEqual(len(reports), len(bad_inputs))

    def test_primary_cancellation_identity_survives_secondary_cancel(self):
        primary = KeyboardInterrupt('authored-primary')
        def validator(source, rows):
            raise primary
        def reporter(source, rows):
            raise SystemExit('authored-secondary')
        try:
            self.qualifier(validator, reporter)(SOURCE, self.rows)
        except BaseException as caught:
            self.assertIs(caught, primary)
        else:
            self.fail('primary cancellation swallowed')

    def test_static_native_wiring_and_public_reader_do_not_execute_native(self):
        module = tree('packaging/run_native_regressions.py')
        main = next(n for n in module.body if isinstance(n, ast.FunctionDef) and n.name == 'main')
        calls = [n for n in ast.walk(main) if isinstance(n, ast.Call)]
        self.assertEqual(sum(isinstance(n.func, ast.Name) and n.func.id == 'qualified_native_args' for n in calls), 1)
        source = tree('scripts/ci_owned/source_suites.py')
        reader = next(n for n in source.body if isinstance(n, ast.FunctionDef) and n.name == 'emit_source_failure')
        self.assertIn('for relative in PUBLIC_DIAGNOSTIC_INPUTS:', ast.unparse(reader))
        self.assertIn('stream.read(PUBLIC_INPUT_CAP + 1)', ast.unparse(reader))
        self.assertNotIn('read_bytes', ast.unparse(reader))
        self.assertNotIn('subprocess', ast.unparse(reader))
        self.assertEqual(PUBLIC_DIAGNOSTIC_INPUTS, ('__init__.py', 'tests/fixtures/g4_original_boundary_gold.txt',
                                                   'tests/fixtures/g4_metadata_scope.txt'))


if __name__ == '__main__':
    raise SystemExit(run_unittest(PrerequisiteControls, expected=10))
