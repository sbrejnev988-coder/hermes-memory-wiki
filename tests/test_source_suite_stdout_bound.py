"""Parent stdout-report read regressions: stdlib unittest / ordinary pytest.

Collection is inert. Only setUp reads/extracts the exact shipped tooling; no
provider, SDK-absence requirement, SQL or real subprocess is used. The completed
subprocess seam produces synthetic reports, never genuine native qualification.
"""
from __future__ import annotations

import ast
import builtins
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch


class _ReadObserver:
    """Own real file, passive read-size/closure witness; no permission stand-in."""

    def __init__(self, stream, *, bounded=True, failure=None):
        self.stream = stream
        self.bounded = bounded
        self.failure = failure
        self.requested = []
        self.returned = []
        self.closed = False

    def __enter__(self):
        self.stream.__enter__()
        return self

    def __exit__(self, *error):
        try:
            return self.stream.__exit__(*error)
        finally:
            self.closed = self.stream.closed

    def read(self, size=-1):
        self.requested.append(size)
        if self.bounded and (type(size) is not int or not 0 < size <= 96001):
            raise AssertionError('unbounded_stdout_read')
        if self.failure is not None:
            raise self.failure
        raw = self.stream.read(size)
        self.returned.append(len(raw))
        return raw

    def readall(self):
        raise AssertionError('readall_stdout_refused')


class StdoutBoundTests(unittest.TestCase):
    def setUp(self):
        # Ordinary pytest can run this without any SDK or external peer/setup.
        self.source = Path(__file__).resolve().parents[1]
        self.raw = (self.source / 'scripts/ci_owned/source_suites.py').read_bytes()
        self.fixture_raw = (self.source / 'scripts/ci_owned/fixture_prerequisites.py').read_bytes()
        self.test_raw = Path(__file__).read_bytes()
        fixture = {'__name__': 'owned_stdout_fixture', '__file__': str(self.source / 'scripts/ci_owned/fixture_prerequisites.py')}
        exec(compile(self.fixture_raw, fixture['__file__'], 'exec', dont_inherit=True), fixture)
        self.fixture = fixture
        self.target = self.target_from_bytes(self.raw)
        self.original_open = Path.open
        self.tmp = tempfile.TemporaryDirectory(prefix='source-stdout-bound-')
        self.addCleanup(self.tmp.cleanup)  # Only this newly created exact subtree.
        self.root = Path(self.tmp.name)
        self.calls = []
        self.readers = []
        self.loads = []
        self.native_calls = []
        self.diagnostics = []
        self.runs = 0
        self.observations = []

    def target_from_bytes(self, raw):
        path = str(self.source / 'scripts/ci_owned/source_suites.py')
        tree = ast.parse(raw, filename=path)
        names = ('run_suites', 'qualified_native_args')
        nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
        self.assertEqual([n.name for n in nodes], ['qualified_native_args', 'run_suites'])
        namespace = {'Path': Path, 'hashlib': hashlib, 'os': os, 'sys': sys, 'time': time,
                     'json': json, 'subprocess': subprocess,
                     **{n: self.fixture[n] for n in ('SOURCE_SUITES', 'no_links', 'clean_environment', 'suite_case_ids', 'native_pytest_args')}}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), path, 'exec', dont_inherit=True), namespace)
        return namespace

    def payloads(self, *, size=None, mutate=None):
        payloads, reports = [], []
        for index, (relative, (_, count)) in enumerate(self.fixture['SOURCE_SUITES'].items()):
            report = {'schema': 'memory-stack.source-suites/v1', 'boundary': 'SOURCE_NOT_NATIVE',
                      'total': count, 'passed': count, 'failed': 0, 'errors': 0, 'skipped': 0,
                      'cases': [{'id': identity, 'outcome': 'passed'} for identity in self.fixture['suite_case_ids'](self.source, relative)],
                      'subtests': [], 'diagnostics': {'schema': 'memory-stack.source-case-errors/v1', 'case_error_types': {}}}
            if mutate is not None and index == 0:
                mutate(report)
            raw = json.dumps(report, separators=(',', ':'), ensure_ascii=True).encode('ascii') + b'\n'
            if size is not None:
                self.assertLessEqual(len(raw), size)
                # Valid JSON line followed by ignored blank padding, not an empty report.
                raw += b' ' * (size - len(raw))
            payloads.append(raw)
            reports.append(report)
        return payloads, reports

    def run_reports(self, payloads=None, *, target=None, bounded=True,
                    fail_read=None, process_error=None, returncode=0):
        if payloads is None:
            payloads, _ = self.payloads()
        self.runs += 1
        root = self.root / ('run-' + str(self.runs))
        self.assertFalse(root.exists())
        target = self.target if target is None else target
        calls, readers, loads = [], [], []

        def completed(command, *, cwd, env, stdout, stderr, timeout, check, shell):
            index = len(calls)
            relative = list(self.fixture['SOURCE_SUITES'])[index]
            self.assertEqual(command, [sys.executable, '-I', '-B', '-S', str(self.source / relative)])
            self.assertEqual(cwd, root / ('suite-' + str(index)))
            self.assertEqual((timeout, check, shell), (60, False, False))
            self.assertFalse(stdout.closed)
            self.assertFalse(stderr.closed)
            for key in ('HOME', 'USERPROFILE', 'LOCALAPPDATA', 'APPDATA', 'HERMES_HOME', 'TEMP', 'TMP', 'TMPDIR'):
                self.assertTrue(Path(env[key]).is_relative_to(cwd))
            self.assertNotIn('PATH', env)
            self.assertNotIn('PYTHONPATH', env)
            calls.append({'command': command, 'timeout': timeout, 'synthetic': True})
            if process_error is not None and index == 0:
                raise process_error
            stdout.write(payloads[index])
            stderr.write(b'')
            return SimpleNamespace(returncode=returncode)

        def opened(path, mode='r', *args, **kwargs):
            stream = self.original_open(path, mode, *args, **kwargs)
            if path.name == 'stdout.log' and path.is_relative_to(root) and mode == 'rb':
                index = int(path.parent.name.removeprefix('suite-'))
                observer = _ReadObserver(stream, bounded=bounded,
                                         failure=fail_read if index == 0 else None)
                readers.append(observer)
                return observer
            return stream

        def decoded(raw):
            loads.append(len(raw))
            return json.loads(raw)

        def qualified(source, rows):
            self.native_calls.append('original_metadata_validator')
            return self.fixture['native_pytest_args'](source, rows)

        def diagnostic(source, rows):
            self.diagnostics.append('synthetic_diagnostic_observer')

        # Only a local function namespace has a synthetic subprocess facade.
        # Neither subprocess.run nor Path.open remains patched after this call.
        target.update(subprocess=SimpleNamespace(run=completed, TimeoutExpired=subprocess.TimeoutExpired),
                      json=SimpleNamespace(loads=decoded, dumps=json.dumps),
                      native_pytest_args=qualified, emit_source_failure=diagnostic)
        with patch.object(Path, 'open', opened):
            rows = target['run_suites'](self.source, root)
        self.assertIs(Path.open, self.original_open)
        self.assertEqual(len(calls), 3)
        self.assertEqual(list(rows), list(self.fixture['SOURCE_SUITES']))
        self.assertEqual(json.loads((root / 'source-results.json').read_bytes()), rows)
        self.assertTrue(all(r.closed and r.stream.closed for r in readers))
        self.calls, self.readers, self.loads = calls, readers, loads
        self.observations.append({'sizes': [len(p) for p in payloads],
                                  'requested': [r.requested for r in readers],
                                  'returned': [r.returned for r in readers],
                                  'streams_closed': all(r.closed for r in readers),
                                  'decode_calls': len(loads), 'synthetic_completed_calls': len(calls),
                                  'row_errors': [row.get('error_type') for row in rows.values()]})
        return rows

    def assert_healthy(self, rows, reports):
        for (relative, row), report in zip(rows.items(), reports):
            self.assertNotIn('error_type', row)
            self.assertEqual(row['exit_code'], 0)
            self.assertEqual(row['sha256'], hashlib.sha256((self.source / relative).read_bytes()).hexdigest())
            self.assertEqual(row['case_ids'], [c['id'] for c in report['cases']])
            for key in ('total', 'passed', 'failed', 'errors', 'skipped', 'cases', 'subtests', 'diagnostics'):
                self.assertEqual(row[key], report[key])
            self.assertIsInstance(row['elapsed_seconds'], float)
        self.assertEqual([r.requested for r in self.readers], [[96001]] * 3)
        self.assertEqual(self.target['qualified_native_args'](self.source, rows),
                         ['--ignore=' + str(self.source / relative) for relative in self.fixture['SOURCE_SUITES']])
        self.assertEqual(self.diagnostics, [])

    def test_01_nonempty_report_and_original_rows(self):
        payloads, reports = self.payloads()
        self.assertTrue(all(p.startswith(b'{') for p in payloads))
        self.assert_healthy(self.run_reports(payloads), reports)
        self.assertEqual(len(self.loads), 3)

    def test_02_exact_96000_valid_report(self):
        payloads, reports = self.payloads(size=96000)
        self.assertEqual([len(p) for p in payloads], [96000] * 3)
        self.assert_healthy(self.run_reports(payloads), reports)
        self.assertEqual([r.returned for r in self.readers], [[96000]] * 3)

    def test_03_96001_valid_prefix_refuses_before_decode(self):
        exact, _ = self.payloads(size=96000)
        payloads = [p + b'\xff' for p in exact]
        rows = self.run_reports(payloads)
        self.assertEqual([r.requested for r in self.readers], [[96001]] * 3)
        self.assertEqual([r.returned for r in self.readers], [[96001]] * 3)
        self.assertEqual(self.loads, [])  # Invalid UTF-8 must not reach JSON decode.
        self.assertEqual(self.native_calls, [])
        for row in rows.values():
            self.assertEqual(row['error_type'], 'RuntimeError')
            self.assertEqual(row['exit_code'], 0)
            self.assertIsNone(row['total'])
            self.assertNotIn('cases', row)
        with self.assertRaisesRegex(RuntimeError, '^source_suite_not_qualified:'):
            self.target['qualified_native_args'](self.source, rows)

    def test_04_read_observer_rejects_readall_and_unbounded(self):
        path = self.root / 'observer.bin'
        path.write_bytes(b'abc')
        with _ReadObserver(path.open('rb')) as observer:
            for size in (-1, 0, 96002):
                with self.subTest(size=size):
                    with self.assertRaisesRegex(AssertionError, '^unbounded_stdout_read$'):
                        observer.read(size)
            with self.assertRaisesRegex(AssertionError, '^readall_stdout_refused$'):
                observer.readall()
            self.assertEqual(observer.read(96001), b'abc')
        self.assertTrue(observer.closed)
        payloads, reports = self.payloads()
        self.assert_healthy(self.run_reports(payloads), reports)

    def test_05_read_failure_retains_row_and_closes_stream(self):
        rows = self.run_reports(fail_read=OSError('owned read failure'))
        first, *rest = rows.values()
        self.assertEqual(first['error_type'], 'OSError')
        self.assertEqual(first['exit_code'], 0)
        self.assertIsNone(first['total'])
        self.assertEqual(len(self.loads), 2)
        self.assertEqual([r.requested for r in self.readers], [[96001]] * 3)
        self.assertEqual(self.readers[0].returned, [])
        self.assertTrue(all('error_type' not in row for row in rest))
        with self.assertRaisesRegex(RuntimeError, '^source_suite_not_qualified:'):
            self.target['qualified_native_args'](self.source, rows)

    def test_06_original_schema_identity_outcome_count_refusals(self):
        def schema(r):
            r['schema'] = 'wrong'
        def total(r):
            r['total'] -= 1
        def identity(r):
            r['cases'][0]['id'] += '_foreign'
        def outcome(r):
            r['cases'][0]['outcome'] = 'unknown'
        def count(r):
            r['passed'] -= 1
        for label, mutation, decoded in [('schema', schema, True), ('total', total, True),
                                          ('identity', identity, True), ('outcome', outcome, True), ('counts', count, True)]:
            with self.subTest(refusal=label):
                payloads, _ = self.payloads(mutate=mutation)
                rows = self.run_reports(payloads)
                first = next(iter(rows.values()))
                self.assertEqual(first['error_type'], 'RuntimeError')
                self.assertIsNone(first['total'])
                self.assertEqual(bool(self.loads), decoded)
                self.assertEqual(len(self.loads), 3)
                with self.assertRaisesRegex(RuntimeError, '^source_suite_not_qualified:'):
                    self.target['qualified_native_args'](self.source, rows)

    def test_07_malformed_and_missing_report_refusals(self):
        for bad, error in [(b'{invalid}\n', 'JSONDecodeError'), (b'ordinary output only\n', 'IndexError')]:
            with self.subTest(error=error):
                payloads, _ = self.payloads()
                payloads[0] = bad
                rows = self.run_reports(payloads)
                self.assertEqual(next(iter(rows.values()))['error_type'], error)
                self.assertTrue(all(r.closed for r in self.readers))
                with self.assertRaisesRegex(RuntimeError, '^source_suite_not_qualified:'):
                    self.target['qualified_native_args'](self.source, rows)

    def test_08_lawful_outcomes_nonzero_and_process_refusals(self):
        for outcome, counter in [('failed', 'failed'), ('error', 'errors'), ('skipped', 'skipped')]:
            with self.subTest(outcome=outcome):
                def mutation(r):
                    r['cases'][0]['outcome'] = outcome
                    r['passed'] -= 1
                    r[counter] += 1
                payloads, reports = self.payloads(mutate=mutation)
                rows = self.run_reports(payloads, returncode=1 if outcome != 'skipped' else 0)
                first = next(iter(rows.values()))
                self.assertNotIn('error_type', first)
                self.assertEqual(first['cases'], reports[0]['cases'])
                self.assertEqual(first[counter], 1)
                with self.assertRaisesRegex(RuntimeError, '^source_suite_not_qualified:'):
                    self.target['qualified_native_args'](self.source, rows)
        with self.subTest(exit_code='nonzero_with_valid_report'):
            rows = self.run_reports(returncode=7)
            self.assertTrue(all(r['exit_code'] == 7 and 'error_type' not in r for r in rows.values()))
            with self.assertRaisesRegex(RuntimeError, '^source_suite_not_qualified:'):
                self.target['qualified_native_args'](self.source, rows)
        for error in (subprocess.TimeoutExpired(['synthetic'], 60), OSError('owned process refusal')):
            with self.subTest(process_error=type(error).__name__):
                rows = self.run_reports(process_error=error)
                first = next(iter(rows.values()))
                self.assertEqual(first['error_type'], type(error).__name__)
                self.assertIsNone(first['exit_code'])
                self.assertIsNone(first['total'])
                self.assertEqual(len(self.readers), 2)
                with self.assertRaisesRegex(RuntimeError, '^source_suite_not_qualified:'):
                    self.target['qualified_native_args'](self.source, rows)

    def test_09_original_qualifier_primary_identity(self):
        payloads, reports = self.payloads()
        rows = self.run_reports(payloads)
        self.assert_healthy(rows, reports)
        refused = copy.deepcopy(rows)
        next(iter(refused.values()))['sha256'] = '0' * 64
        for secondary in (KeyboardInterrupt(), SystemExit(19)):
            with self.subTest(secondary=type(secondary).__name__):
                original = []
                def qualifier(source, result):
                    try:
                        return self.fixture['native_pytest_args'](source, result)
                    except RuntimeError as error:
                        original.append(error)
                        raise
                def diagnostic(source, result):
                    raise secondary
                self.target.update(native_pytest_args=qualifier, emit_source_failure=diagnostic)
                with self.assertRaises(RuntimeError) as caught:
                    self.target['qualified_native_args'](self.source, refused)
                self.assertEqual(len(original), 1)
                self.assertIs(caught.exception, original[0])
                self.assertTrue(str(caught.exception).startswith('source_suite_not_qualified:'))
        with self.assertRaisesRegex(RuntimeError, '^source_suite_roster_incomplete$'):
            self.fixture['native_pytest_args'](self.source, {})

    def test_10_static_collection_and_exact_read_contract(self):
        tree = ast.parse(self.raw)
        run = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'run_suites')
        outer = next(n for n in ast.walk(run) if isinstance(n, ast.Try))
        bounded = next(n for n in outer.body if isinstance(n, ast.With)
                       and len(n.items) == 1 and isinstance(n.items[0].context_expr, ast.Call))
        self.assertEqual(ast.unparse(bounded.items[0].context_expr), "(fixture / 'stdout.log').open('rb')")
        self.assertEqual(ast.unparse(bounded.body[0]), 'raw = stream.read(96001)')
        guard = next(n for n in outer.body if isinstance(n, ast.If))
        self.assertEqual(ast.unparse(guard.test), 'len(raw) > 96000')
        self.assertEqual(ast.unparse(guard.body[0]), "raise RuntimeError('source_report_too_large')")
        reports = next(n for n in outer.body if isinstance(n, ast.Assign)
                       and any(isinstance(t, ast.Name) and t.id == 'reports' for t in n.targets))
        self.assertLess(bounded.lineno, guard.lineno)
        self.assertLess(guard.lineno, reports.lineno)
        entry_read = [n for n in ast.walk(run) if isinstance(n, ast.Call)
                      and isinstance(n.func, ast.Attribute) and n.func.attr == 'read_bytes']
        self.assertEqual([ast.unparse(n) for n in entry_read], ['entry.read_bytes()'])
        code = compile(self.test_raw, __file__, 'exec', dont_inherit=True)
        real_exec = builtins.exec
        namespace = {'__name__': 'owned_inert_collection', '__file__': __file__}
        with patch.object(Path, 'open', side_effect=AssertionError('collection_file_io')), \
             patch.object(tempfile, 'TemporaryDirectory', side_effect=AssertionError('collection_fixture')), \
             patch.object(sys, 'addaudithook', side_effect=AssertionError('collection_hook')), \
             patch.object(subprocess, 'run', side_effect=AssertionError('collection_process')), \
             patch.object(builtins, 'exec', side_effect=AssertionError('collection_nested_exec')):
            real_exec(code, namespace)
        self.assertEqual(unittest.defaultTestLoader.getTestCaseNames(namespace['StdoutBoundTests']),
                         unittest.defaultTestLoader.getTestCaseNames(type(self)))
        self.assertNotIn('__test__', namespace)
        self.assertNotIn('__test__', namespace['StdoutBoundTests'].__dict__)
        self.observations.append({'STATIC_only': True, 'collection_inert': True})


if __name__ == '__main__':
    unittest.main(verbosity=2)
