"""SOURCE tests of actual stdlib reporter/entry bodies, never pytest dispatch.

All reports/CallInfo and the dispatcher callback are explicitly synthetic data.
Real files remain in the test-owned TMPDIR for evidence readback. Fault actors
are local file/metadata/console actors, not replacement guards or SDK modules.
No assumption is made about an unrelated provider singleton during discovery.
"""
from __future__ import annotations

import ast
from enum import IntEnum
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import tempfile
from types import ModuleType, SimpleNamespace
import unittest

ROOT = Path(globals().get('COLLECTION_SOURCE_ROOT', Path(__file__).parent.parent))
REPORTER = ROOT / 'tests/helpers/collection_evidence.py'
NATIVE = ROOT / 'packaging/run_native_regressions.py'
COLD = ROOT / 'tests/cold_lane_entry.py'


def load_reporter():
    # This test-owned whole-module loader uses only the declared source file.
    # SourceFileLoader.exec_module also probes a bytecode-cache path, which is
    # intentionally outside the closed SOURCE packet's read allowlist.
    module = ModuleType('_collection_evidence_fixture')
    module.__file__ = str(REPORTER)
    exec(compile(REPORTER.read_bytes(), str(REPORTER), 'exec', dont_inherit=True),
         module.__dict__)
    return module


def extracted(path, name, namespace):
    tree = ast.parse(path.read_bytes(), filename=str(path))
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name]
    if len(nodes) != 1:
        raise AssertionError('Exact entry definition must be unique')
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), 'exec', dont_inherit=True), namespace)
    return namespace[name]


class SyntheticReport:
    def __init__(self, nodeid='tests/ошибка.py::collect[🌍]', text='ImportError: fixture cause\nfull traceback\n',
                 outcome='failed', when='collect'):
        self.nodeid, self.longrepr, self.longreprtext = nodeid, text, text
        self.outcome, self.when = outcome, when
        self.failed = outcome == 'failed'


class FileFault:
    """Refusing actor over an actual owned FileIO; never patches global os/open."""
    def __init__(self, raw, mode):
        self.raw, self.mode, self.writes = raw, mode, 0

    @property
    def closed(self):
        return self.raw.closed

    def fileno(self):
        return self.raw.fileno()

    def write(self, raw):
        self.writes += 1
        if self.mode == 'partial':
            if self.writes == 1:
                return self.raw.write(raw[:7])
            raise OSError('synthetic write refusal')
        if self.mode == 'zero':
            return 0
        return self.raw.write(raw)

    def flush(self):
        self.raw.flush()

    def close(self):
        if self.mode == 'close_before':
            raise OSError('synthetic close refusal before effect')
        self.raw.close()
        if self.mode == 'close_after':
            raise OSError('synthetic close refusal after effect')


class TestCollectionEvidence(unittest.TestCase):
    def setUp(self):
        self.module = load_reporter()
        self.root = Path(tempfile.mkdtemp(prefix='collection-' + self._testMethodName + '-',
            dir=os.environ.get('TMPDIR') or tempfile.gettempdir()))
        self.sink, self.number = io.StringIO(), 0
        self.reporters = []
        self.addCleanup(self.close_owned_handles)

    def tearDown(self):
        sinks = [self.sink]
        for reporter in self.reporters:
            if isinstance(reporter.stderr, io.StringIO) and all(reporter.stderr is not old for old in sinks):
                sinks.append(reporter.stderr)
        (self.root / 'reporter-console.log').write_text(
            '\n'.join(sink.getvalue() for sink in sinks), encoding='utf-8')

    def close_owned_handles(self):
        # Safety closure of explicitly retained UNKNOWN fixture handles does NOT
        # turn a previously persisted production cleanup refusal into success.
        for reporter in self.reporters:
            for stream in reporter._handles:
                raw = stream.raw if isinstance(stream, FileFault) else stream
                if not raw.closed:
                    raw.close()

    def reporter(self, label='run', module=None, **caps):
        self.number += 1
        reporter = (module or self.module).CollectionEvidence(
            self.root / (str(self.number) + '-' + label), stderr=self.sink, **caps)
        self.reporters.append(reporter)
        return reporter

    def rows(self, reporter):
        raw = (reporter.directory / 'errors.jsonl').read_bytes()
        self.assertTrue(raw.endswith(b'\n'))
        return [json.loads(line.decode('utf-8')) for line in raw.splitlines()]

    def status(self, reporter, *, complete):
        path = reporter.directory / 'status.json'
        value = json.loads(path.read_bytes().decode('utf-8'))
        self.assertEqual(value['complete'], complete)
        self.assertEqual((reporter.directory / 'complete').is_dir(), complete)
        self.assertEqual(value['schema'], self.module.SCHEMA)
        self.assertLessEqual(path.stat().st_size, self.module.STATUS_CAP)
        return value

    def fault(self, reporter, mode):
        raw = reporter._journal
        actor = FileFault(raw, mode)
        reporter._journal = actor
        reporter._handles[reporter._handles.index(raw)] = actor
        return raw

    def test_early_causal_capture_survives_sessionfinish_exception(self):
        reporter = self.reporter()
        report = SyntheticReport()
        original = RuntimeError('original later sessionfinish error')
        session = SimpleNamespace(testsfailed=6, exitstatus=2)
        def dispatch(args, plugins):
            self.assertEqual(args, ['-q', 'tests'])
            self.assertIs(plugins[-1], reporter)
            reporter.pytest_exception_interact(None, SimpleNamespace(
                excinfo=SimpleNamespace(value=ImportError('actual synthetic import cause'))), report)
            reporter.pytest_collectreport(report)
            rows = self.rows(reporter)  # DURABLE readback before any sessionfinish.
            self.assertEqual(rows[-1]['nodeid'], report.nodeid)
            self.assertEqual(rows[-1]['longrepr'], report.longreprtext)
            self.assertEqual(rows[-2]['exception_type'], 'builtins.ImportError')
            self.assertEqual(rows[-2]['message'], 'actual synthetic import cause')
            self.assertFalse((reporter.directory / 'status.json').exists())
            reporter.pytest_sessionfinish(session, 2)
            raise original
        with self.assertRaises(RuntimeError) as caught:
            reporter.run(dispatch, ['-q', 'tests'])
        self.assertIs(caught.exception, original)
        self.assertEqual(vars(session), {'testsfailed': 6, 'exitstatus': 2})
        value = self.status(reporter, complete=True)
        self.assertEqual(value['primary_type'], 'builtins.RuntimeError')
        self.assertIsNone(value['returned_exitstatus'])
        self.assertEqual(value['session_exitstatus'], 2)
        self.assertEqual(value['saved_collect_reports'], 1)
        self.assertEqual(self.rows(reporter)[-2]['longrepr'], report.longreprtext)

    def test_full_unicode_literal_roundtrip_and_console(self):
        reporter = self.reporter()
        text = '  cause\n\tкириллица / 🌍 / \\u1234 / " / \x00 / \ud800\n  '
        report = SyntheticReport(nodeid='../NOT-A-PATH::[\udfff🌍]', text=text)
        reporter.pytest_collectreport(report)
        self.assertIs(reporter.run(lambda *a, **kw: 2, []), 2)
        row = self.rows(reporter)[1]
        self.assertEqual(row['longrepr'], text)
        self.assertEqual(row['nodeid'], report.nodeid)
        self.assertEqual(row['longrepr_type'], 'builtins.str')
        self.assertEqual(row['report_type'], __name__ + '.SyntheticReport')
        echoes = [json.loads(line[len(self.module.PREFIX):]) for line in self.sink.getvalue().splitlines()]
        self.assertEqual(echoes[0], row)
        self.status(reporter, complete=True)

    def test_failed_reports_only_without_dedup_or_outcome_change(self):
        reporter = self.reporter()
        for outcome in ('passed', 'skipped', 'failed', 'failed'):
            reporter.pytest_collectreport(SyntheticReport(nodeid='same-node', outcome=outcome))
        class ExitCode(IntEnum):
            INTERRUPTED = 2
        result = reporter.run(lambda *a, **kw: ExitCode.INTERRUPTED, [])
        self.assertIs(result, ExitCode.INTERRUPTED)
        value = self.status(reporter, complete=True)
        self.assertEqual((value['failed_collect_reports'], value['saved_collect_reports']), (2, 2))
        self.assertEqual([r['nodeid'] for r in self.rows(reporter)[1:]], ['same-node', 'same-node'])
        self.assertEqual(value['returned_exitstatus'], 2)

    def test_exact_serialized_utf8_event_boundary_and_plus_one_refusal(self):
        report = SyntheticReport(text='🌍' * 300)
        generous = self.reporter()
        generous.pytest_collectreport(report)
        raw = (generous.directory / 'errors.jsonl').read_bytes().splitlines(keepends=True)[1]
        generous.run(lambda *a, **kw: 2, [])
        for cap, accepted in ((len(raw), True), (len(raw) - 1, False)):
            reporter = self.reporter(event_cap=cap)
            reporter.pytest_collectreport(report)
            before_finish = self.rows(reporter)
            if accepted:
                self.assertEqual(before_finish[1]['longrepr'], report.longreprtext)
            else:
                self.assertEqual(before_finish[-1]['event'], 'reporting_refused')
                self.assertEqual(before_finish[-1]['refusal']['code'], 'serialized_byte_cap')
                self.assertFalse(any(r['event'] == 'collection_error' for r in before_finish))
            self.assertEqual(reporter.run(lambda *a, **kw: 2, []), 2)
            value = self.status(reporter, complete=accepted)
            self.assertEqual(value['uncaptured_collect_reports'], 0 if accepted else 1)

    def test_exact_total_journal_boundary_has_reserved_refusal_not_truncation(self):
        report = SyntheticReport(text='z' * 5_000)
        generous = self.reporter()
        generous.pytest_collectreport(report)
        lines = (generous.directory / 'errors.jsonl').read_bytes().splitlines(keepends=True)
        header, row = json.loads(lines[0]), lines[1]
        generous.run(lambda *a, **kw: 2, [])
        cap = 8_000
        for _ in range(4):
            header['journal_cap'] = cap
            cap = len(self.module.json_bytes(header, 1024)) + len(row) + self.module.TAIL_RESERVE
        for text, accepted in ((report.longreprtext, True), (report.longreprtext + 'x', False)):
            reporter = self.reporter(journal_cap=cap)
            reporter.pytest_collectreport(SyntheticReport(text=text))
            reporter.pytest_sessionfinish(SimpleNamespace(), 2)
            reporter.run(lambda *a, **kw: 2, [])
            value = self.status(reporter, complete=accepted)
            self.assertLessEqual((reporter.directory / 'errors.jsonl').stat().st_size, cap)
            if not accepted:
                self.assertEqual(value['refusals'][0]['code'], 'journal_byte_cap')
                self.assertEqual(self.rows(reporter)[1]['event'], 'reporting_refused')
                self.assertEqual(value['uncaptured_collect_reports'], 1)

    def test_render_and_missing_excinfo_refusals_are_explicit(self):
        reporter = self.reporter()
        class BrokenReport:
            failed = True
            @property
            def longreprtext(self):
                raise LookupError('synthetic rendering refusal')
        reporter.pytest_collectreport(BrokenReport())
        self.assertEqual(self.rows(reporter)[-1]['refusal']['type'], 'builtins.LookupError')
        report = SyntheticReport()
        reporter.pytest_exception_interact(None, SimpleNamespace(excinfo=None), report)
        reporter.pytest_collectreport(report)
        reporter.run(lambda *a, **kw: 2, [])
        value = self.status(reporter, complete=False)
        self.assertEqual(value['failed_collect_reports'], 2)
        self.assertEqual(value['saved_collect_reports'], 1)
        self.assertEqual(value['exception_details'], 0)
        self.assertEqual(value['refusal_count'], 2)

    def test_oversized_input_and_refusal_ledger_are_bounded(self):
        reporter = self.reporter(event_cap=512)
        for _ in range(12):
            reporter.pytest_collectreport(SyntheticReport(text='x' * 513))
        reporter.run(lambda *a, **kw: 2, [])
        value = self.status(reporter, complete=False)
        self.assertEqual(value['uncaptured_collect_reports'], 12)
        self.assertEqual(value['refusal_count'], 12)
        self.assertEqual(len(value['refusals']), 8)
        self.assertEqual(value['refusals_omitted'], 4)
        self.assertEqual(value['refusals'][0]['code'], 'json_character_cap')
        self.assertEqual(len(self.rows(reporter)), 2)  # Header + first durable refusal.

    def test_exclusive_namespace_preserves_foreign_evidence(self):
        target = self.root / 'existing'
        evidence = target / 'collection-evidence'
        evidence.mkdir(parents=True)
        foreign = evidence / 'errors.jsonl'
        foreign.write_bytes(b'foreign original evidence\n')
        reporter = self.module.CollectionEvidence(target, stderr=self.sink)
        self.reporters.append(reporter)
        self.assertEqual(reporter.run(lambda *a, **kw: 0, []), 0)
        self.assertEqual(foreign.read_bytes(), b'foreign original evidence\n')
        self.assertEqual(list(evidence.iterdir()), [foreign])
        self.assertIsNone(reporter.directory)
        self.assertIn('builtins.FileExistsError', self.sink.getvalue())
        self.assertFalse(reporter.status()['complete'])

    def test_root_file_and_unsafe_lexical_tokens_refuse_before_effect(self):
        root_file = self.root / 'file'
        root_file.write_bytes(b'preserve file')
        tokens = [root_file, 'relative-root', str(self.root) + '/../escape',
                  str(self.root) + '/bad.', str(self.root) + '/bad ',
                  str(self.root) + '/CON.txt', str(self.root) + '/x:ads',
                  '\\\\server\\share', 'C:relative', str(self.root) + '/line\nfeed']
        for token in tokens:
            reporter = self.module.CollectionEvidence(token, stderr=self.sink)
            self.reporters.append(reporter)
            self.assertEqual(reporter.run(lambda *a, **kw: 2, []), 2)
            self.assertGreater(reporter.refusal_count, 0)
            self.assertIsNone(reporter.directory)
        self.assertEqual(root_file.read_bytes(), b'preserve file')
        self.assertEqual(list(self.root.iterdir()), [root_file])

    def test_link_reparse_and_changed_identity_metadata_deny_actual_guard(self):
        # The SOURCE fence forbids making real links. Supply only no-follow stat
        # data; execute the actual path/identity guards unchanged.
        for mode in ('symlink', 'reparse'):
            module = load_reporter()
            target = self.root / mode
            target.mkdir()
            def lstat(path, target=target, mode=mode):
                info = os.lstat(path)
                if Path(path) == target:
                    data = {name: getattr(info, name) for name in ('st_mode', 'st_dev', 'st_ino')}
                    data['st_mode'] = stat.S_IFLNK if mode == 'symlink' else info.st_mode
                    data['st_file_attributes'] = 0x400 if mode == 'reparse' else 0
                    return SimpleNamespace(**data)
                return info
            module.os = SimpleNamespace(**{**vars(os), 'lstat': lstat})
            reporter = module.CollectionEvidence(target, stderr=self.sink)
            self.reporters.append(reporter)
            reporter.run(lambda *a, **kw: 2, [])
            self.assertIsNone(reporter.directory)
            self.assertEqual(reporter.refusals[0]['code'], 'unsafe_directory')
            self.assertEqual(list(target.iterdir()), [])
        reporter = self.reporter()
        module = self.module
        def changed(path):
            info = os.lstat(path)
            if Path(path) == reporter.directory:
                return SimpleNamespace(st_mode=info.st_mode, st_dev=info.st_dev,
                                       st_ino=info.st_ino + 1, st_file_attributes=0)
            return info
        module.os = SimpleNamespace(**{**vars(os), 'lstat': changed})
        before = (reporter.directory / 'errors.jsonl').read_bytes()
        reporter.pytest_collectreport(SyntheticReport())
        reporter.run(lambda *a, **kw: 2, [])
        self.assertEqual((reporter.directory / 'errors.jsonl').read_bytes(), before)
        self.assertEqual(reporter.refusals[0]['code'], 'directory_identity_changed')
        self.assertFalse((reporter.directory / 'complete').exists())
        self.assertFalse(reporter.status()['complete'])

    def test_partial_write_is_preserved_with_exact_incomplete_facts(self):
        reporter = self.reporter()
        before = (reporter.directory / 'errors.jsonl').read_bytes()
        self.fault(reporter, 'partial')
        reporter.pytest_collectreport(SyntheticReport())
        reporter.run(lambda *a, **kw: 2, [])
        raw = (reporter.directory / 'errors.jsonl').read_bytes()
        self.assertEqual(raw[:len(before)], before)
        self.assertEqual(len(raw), len(before) + 7)
        value = self.status(reporter, complete=False)
        self.assertEqual(value['journal_bytes_confirmed_written'], len(raw))
        self.assertEqual(value['journal_bytes_fsynced'], len(before))
        self.assertEqual(value['saved_collect_reports'], 0)
        self.assertEqual(value['refusals'][0]['type'], 'builtins.OSError')
        self.assertTrue(value['cleanup_complete'])

    def test_zero_progress_refuses_without_fake_repair(self):
        reporter = self.reporter()
        before = (reporter.directory / 'errors.jsonl').read_bytes()
        self.fault(reporter, 'zero')
        reporter.pytest_collectreport(SyntheticReport())
        reporter.run(lambda *a, **kw: 2, [])
        self.assertEqual((reporter.directory / 'errors.jsonl').read_bytes(), before)
        value = self.status(reporter, complete=False)
        self.assertEqual(value['refusals'][0]['code'], 'write_no_progress_or_invalid_count')

    def test_fsync_refusal_keeps_full_raw_but_never_claims_durable_success(self):
        reporter = self.reporter()
        fd, original = reporter._journal.fileno(), os.fsync
        seen = []
        def fsync(candidate):
            if candidate == fd and not seen:
                seen.append(candidate)
                raise OSError('synthetic fsync refusal')
            return original(candidate)
        self.module.os = SimpleNamespace(**{**vars(os), 'fsync': fsync})
        reporter.pytest_collectreport(SyntheticReport())
        reporter.run(lambda *a, **kw: 2, [])
        value = self.status(reporter, complete=False)
        self.assertEqual(len(self.rows(reporter)), 2)
        self.assertGreater(value['journal_bytes_confirmed_written'], value['journal_bytes_fsynced'])
        self.assertEqual(value['saved_collect_reports'], 0)
        self.assertEqual(value['refusals'][0]['type'], 'builtins.OSError')

    def test_close_refusals_distinguish_retained_unknown_from_closed_error(self):
        for mode, known in (('close_before', False), ('close_after', True)):
            reporter = self.reporter(mode)
            raw = self.fault(reporter, mode)
            primary = KeyboardInterrupt('original primary cancellation')
            def dispatch(*args, **kwargs):
                reporter.pytest_collectreport(SyntheticReport())
                raise primary
            with self.assertRaises(KeyboardInterrupt) as caught:
                reporter.run(dispatch, [])
            self.assertIs(caught.exception, primary)
            value = self.status(reporter, complete=False)
            self.assertEqual(value['cleanup_complete'], known)
            self.assertEqual(raw.closed, known)
            self.assertEqual(value['primary_type'], 'builtins.KeyboardInterrupt')
            self.assertEqual(value['refusals'][0]['stage'], 'cleanup_close')
            self.assertEqual(value['saved_collect_reports'], 1)

    def test_stderr_short_write_is_not_swallowed_success(self):
        reporter = self.reporter()
        class ShortConsole(io.StringIO):
            def write(self, text):
                super().write(text[:3])
                return 3
        reporter.stderr = ShortConsole()
        reporter.pytest_collectreport(SyntheticReport())
        reporter.run(lambda *a, **kw: 0, [])
        value = self.status(reporter, complete=False)
        self.assertEqual(value['returned_exitstatus'], 0)  # Telemetry failure is separate.
        self.assertEqual(value['refusals'][0]['code'], 'stderr_short_write')
        self.assertEqual(self.rows(reporter)[1]['event'], 'collection_error')

    def test_terminal_collision_preserves_foreign_status_and_late_refusal(self):
        reporter = self.reporter()
        foreign = reporter.directory / 'status.json'
        foreign.write_bytes(b'foreign status must survive')
        reporter.pytest_collectreport(SyntheticReport())
        self.assertEqual(reporter.run(lambda *a, **kw: 2, []), 2)
        self.assertEqual(foreign.read_bytes(), b'foreign status must survive')
        value = json.loads((reporter.directory / 'refusal.json').read_bytes())
        self.assertFalse(value['complete'])
        self.assertEqual(value['refusals'][-1]['stage'], 'terminal')
        self.assertEqual(value['refusals'][-1]['type'], 'builtins.FileExistsError')
        self.assertFalse((reporter.directory / 'complete').exists())
        self.assertIn('reporting_refused', self.sink.getvalue())

    def test_phases_bounds_collision_and_finalize_failure_preserve_outcome(self):
        for mode in ('cap', 'collision', 'callback'):
            reporter = self.reporter(mode, phase_cap=128)
            if mode == 'collision':
                (reporter.root / 'phases.json').write_bytes(b'foreign phases')
            def finalize():
                if mode == 'callback':
                    raise SystemExit(91)
                reporter.write_phases({'payload': 'x' * 129} if mode == 'cap' else {'phases': []})
            self.assertEqual(reporter.run(lambda *a, **kw: 2, [], finalize=finalize), 2)
            value = self.status(reporter, complete=False)
            self.assertEqual(value['returned_exitstatus'], 2)
            self.assertEqual(value['refusals'][0]['stage'], 'finalize' if mode == 'callback' else 'phases')
            if mode == 'collision':
                self.assertEqual((reporter.root / 'phases.json').read_bytes(), b'foreign phases')
            elif mode == 'cap':
                self.assertFalse((reporter.root / 'phases.json').exists())

    def test_cold_entry_actual_recorder_and_finalizer_keep_causal_evidence(self):
        runroot = self.root / 'cold'
        runroot.mkdir()
        reporter = self.module.CollectionEvidence(runroot / 'public', stderr=self.sink)
        self.reporters.append(reporter)
        run_tests = extracted(COLD, 'run_tests', {})
        report, primary = SyntheticReport(), RuntimeError('late sessionfinish failure')
        def dispatch(args, plugins):
            self.assertEqual(args[:2], ['-q', 'tests/actual-target.py'])
            self.assertIn('--basetemp=' + str(runroot / 'pytest-temp'), args)
            recorder, causal = plugins
            recorder.pytest_collection_modifyitems(None, None, [SimpleNamespace(nodeid='collected')])
            recorder.pytest_runtest_logreport(SimpleNamespace(nodeid='collected', when='setup', outcome='passed'))
            recorder.pytest_collectreport(report)
            causal.pytest_collectreport(report)
            self.assertEqual(self.rows(reporter)[1]['longrepr'], report.longreprtext)
            recorder.pytest_sessionfinish(None, 2)
            causal.pytest_sessionfinish(None, 2)
            raise primary
        with self.assertRaises(RuntimeError) as caught:
            run_tests(dispatch, ['tests/actual-target.py'], runroot, reporter)
        self.assertIs(caught.exception, primary)
        phases = json.loads((runroot / 'public/phases.json').read_bytes())
        self.assertEqual(phases, {'collected': ['collected'], 'phases': [
            {'nodeid': 'collected', 'when': 'setup', 'outcome': 'passed', 'wasxfail': False}],
            'collection_errors': [report.nodeid], 'session_finished': True, 'exitstatus': 2})
        value = self.status(reporter, complete=True)
        self.assertEqual(value['phase_evidence'], 'complete')
        self.assertEqual(value['primary_type'], 'builtins.RuntimeError')

    def test_cold_entry_phase_refusal_never_replaces_original_primary(self):
        reporter = self.reporter()
        (reporter.root / 'phases.json').write_bytes(b'foreign phases')
        run_tests = extracted(COLD, 'run_tests', {})
        primary = RuntimeError('original dispatcher error')
        def dispatch(args, plugins):
            plugins[-1].pytest_collectreport(SyntheticReport())
            raise primary
        # run_tests uses reporter.root for phase persistence, the real runroot only
        # for pytest arguments; this is an explicit local synthetic composition.
        with self.assertRaises(RuntimeError) as caught:
            run_tests(dispatch, ['tests/target.py'], reporter.root.parent, reporter)
        self.assertIs(caught.exception, primary)
        value = self.status(reporter, complete=False)
        self.assertEqual(value['phase_evidence'], 'refused')
        self.assertEqual(value['saved_collect_reports'], 1)
        self.assertEqual((reporter.root / 'phases.json').read_bytes(), b'foreign phases')

    def test_native_loader_actual_body_and_shared_wiring_without_bootstrap(self):
        import importlib
        loader = extracted(NATIVE, 'collection_reporter', {'Path': Path, 'importlib': importlib})
        reporter = loader(ROOT, self.root / 'native-home')
        reporter.stderr = self.sink
        self.reporters.append(reporter)
        reporter.pytest_collectreport(SyntheticReport())
        self.assertEqual(reporter.run(lambda *a, **kw: 2, []), 2)
        self.status(reporter, complete=True)
        # Static wiring only; the guarded native main/whole plugin is NOT run.
        native_tree = ast.parse(NATIVE.read_bytes())
        main = next(node for node in native_tree.body if isinstance(node, ast.FunctionDef) and node.name == 'main')
        returned = main.body[-1].value
        self.assertEqual(ast.unparse(returned.func), 'reporter.run')
        self.assertEqual(ast.unparse(returned.args[0]), 'pytest.main')
        cold_tree = ast.parse(COLD.read_bytes())
        cold_main = next(node for node in cold_tree.body if isinstance(node, ast.FunctionDef) and node.name == 'main')
        self.assertEqual(ast.unparse(cold_main.body[-1].value), 'run_tests(pytest.main, targets, runroot, reporter)')


if __name__ == '__main__':
    unittest.main()
