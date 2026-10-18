"""CI reporting tooling controls; no SDK/plugin/bootstrap or hosted execution.

Standalone stdlib UNIT plus reusable real-pytest fixtures. The external bounded
supervisor calls run_fixture once per cold child; this file spawns no processes.
"""
from enum import IntEnum
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

SOURCE = Path(__file__).absolute().parents[2]
PHASE_KEYS = {'collected', 'phases', 'collection_errors', 'session_finished', 'exitstatus'}
FIXTURE_SOURCES = {
    'collection_error': 'raise RuntimeError("owned collection dispatch failure")\n',
    # Keep a real parser SyntaxError without exercising CPython's optional
    # generic-keyword-typo compiler probes on pseudo filenames under this fence.
    'syntax_error': 'value = "unterminated\n',
    'healthy': 'def test_first():\n    assert 2 > 1\n\ndef test_second():\n    assert "owned".upper() == "OWNED"\n',
}


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    # Whole exact file; no ancestor package setup or implicit cache loader reads.
    exec(compile(path.read_bytes(), str(path), 'exec', dont_inherit=True), module.__dict__)
    return module


def run_fixture(kind, *, source, root):
    """Actual pytest9 dispatcher and renderer, in an owned non-package root."""
    import pytest
    if pytest.__version__ != '9.1.1' or kind not in FIXTURE_SOURCES:
        raise RuntimeError('fixture_contract_mismatch')
    source, root = Path(source), Path(root)
    tests, public = root / 'tests', root / 'public'
    tests.mkdir()
    public.mkdir()
    (tests / ('test_' + kind + '.py')).write_text(FIXTURE_SOURCES[kind], encoding='utf-8')
    regression = []
    if kind == 'healthy':
        # Carry the full shipped UNIT controls into this actual pytest child.
        # No extra standalone child, altered assertions or ancestor package.
        for relative in ('tests/ci_owned/collection_dispatch_cases.py',
                         'tests/helpers/collection_evidence.py',
                         'scripts/ci_owned/ci_child.py', 'scripts/ci_owned/ci_output_admission.py',
                         '.github/workflows/memory-wiki-synthetic.yml'):
            destination = root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes((source / relative).read_bytes())
        regression = [str(tests / 'ci_owned/collection_dispatch_cases.py')]
    ini = tests / 'pytest.ini'
    ini.write_text('[pytest]\n', encoding='utf-8')
    child = load(source / 'scripts/ci_owned/ci_child.py', '_dispatch_fixture_child')
    # pytest9.1 normalizes overlapping directory/file arguments by dropping
    # the child file, which would silently omit this non-test_* control file.
    fixture_file = tests / ('test_' + kind + '.py')
    args = ['-q', str(fixture_file), *regression, '-c', str(ini), '--rootdir=' + str(tests),
            '--confcutdir=' + str(tests), '--import-mode=importlib', '--capture=sys',
            '-p', 'no:junitxml', '-p', 'no:cacheprovider', '--tb=short',
            '--basetemp=' + str(root / 'pytest-temp'), '-o', 'log_file=' + str(public / 'pytest-detail.log')]
    # Deliberately no SDK origins or fake receipt: only this shared reporting
    # boundary is exercised. Stock JUnit is excluded, not monkeypatched, because
    # its hostname probe is outside the network-denying tooling envelope.
    outcome = child.dispatch_pytest(pytest.main, args, source=source, out=public)
    if kind == 'healthy':
        expected = {'test_healthy.py::test_first', 'test_healthy.py::test_second'}
        expected |= {'ci_owned/collection_dispatch_cases.py::DispatchControls::' + name
                     for name in unittest.defaultTestLoader.getTestCaseNames(DispatchControls)}
        phases = json.loads((public / 'phases.json').read_bytes())
        if (set(phases['collected']) != expected or len(phases['collected']) != len(expected)
                or len(phases['phases']) != 3 * len(expected)
                or any(row['outcome'] != 'passed' for row in phases['phases'])):
            raise AssertionError('healthy_fixture_or_control_roster_incomplete')
    return outcome


class DispatchControls(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix=self._testMethodName + '-',
            dir=os.environ.get('DEVTOOLS_TEST_ROOT')))
        self.child = load(SOURCE / 'scripts/ci_owned/ci_child.py', '_unit_ci_child')
        self.admission = load(SOURCE / 'scripts/ci_owned/ci_output_admission.py', '_unit_ci_admission')

    def lane(self, label='lane'):
        root = self.root / label
        root.mkdir()
        for name in ('receipt.json', 'source-inventory.json'):
            (root / name).write_bytes(b'{}')
        return root

    def returned(self, args, *, plugins):
        # Explicit synthetic UNIT inputs; real pytest is only run_fixture.
        for plugin in plugins:
            plugin.pytest_sessionfinish(None, self.outcome)
        return self.outcome

    def complete(self, label='lane'):
        class Exit(IntEnum):
            OK = 0
        self.outcome = Exit.OK
        root = self.lane(label)
        factory = self.child.collection_reporter
        reporter = factory(SOURCE, root)
        reporter.stderr = io.StringIO()
        self.child.collection_reporter = lambda *args: reporter
        try:
            self.assertIs(self.child.dispatch_pytest(self.returned, [], source=SOURCE, out=root), self.outcome)
        finally:
            self.child.collection_reporter = factory
        return root

    def refused(self, root, code):
        with self.assertRaises(self.admission.AdmissionError) as caught:
            self.admission.admit(root, 'native')
        self.assertEqual(caught.exception.code, code)

    def reseal(self, root, status):
        directory = root / 'collection-evidence'
        (directory / 'status.json').write_text(json.dumps(status), encoding='utf-8')
        members = {}
        for name in ('errors.jsonl', 'status.json'):
            raw = (directory / name).read_bytes()
            members[name] = {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
        (directory / 'complete.json').write_text(json.dumps({
            'schema': 'memory-stack.collection-transfer/v1', 'complete': True, 'members': members}), encoding='utf-8')

    def test_return_identity_phase_schema_and_sealed_positive(self):
        root = self.complete()
        phases = json.loads((root / 'phases.json').read_bytes())
        self.assertEqual(set(phases), PHASE_KEYS)
        self.assertEqual(phases, {'collected': [], 'phases': [], 'collection_errors': [],
            'session_finished': True, 'exitstatus': 0})
        result = self.admission.admit(root, 'native')
        self.assertTrue(result['collection_complete'])
        self.assertEqual(result['files'], 6)
        self.assertEqual(list((root / 'collection-evidence/complete').iterdir()), [])
        self.assertNotIn('accepted', result)

    def test_exact_primary_survives_reporting_and_seal_failure(self):
        root = self.lane()
        reporter = self.child.collection_reporter(SOURCE, root)
        reporter.stderr = io.StringIO()
        primary = BaseException('owned primary identity')
        def broken(*args, **kwargs):
            raise primary
        def refused_status():
            raise KeyboardInterrupt('owned secondary seal')
        reporter.status = refused_status
        self.child.collection_reporter = lambda *args: reporter
        with self.assertRaises(BaseException) as caught:
            self.child.dispatch_pytest(broken, [], source=SOURCE, out=root)
        self.assertIs(caught.exception, primary)
        self.assertFalse((root / 'collection-evidence/complete.json').exists())
        self.refused(root, 'collection_incomplete')

    def test_finalizer_refusal_preserves_original_intenum_return(self):
        root = self.lane()
        reporter = self.child.collection_reporter(SOURCE, root)
        reporter.stderr = io.StringIO()
        def refuse(value):
            raise KeyboardInterrupt('owned phases refusal')
        reporter.write_phases = refuse
        self.child.collection_reporter = lambda *args: reporter
        class Exit(IntEnum):
            OK = 0
        self.outcome = Exit.OK
        self.assertIs(self.child.dispatch_pytest(self.returned, [], source=SOURCE, out=root), self.outcome)
        self.assertFalse((root / 'collection-evidence/complete.json').exists())
        self.refused(root, 'collection_incomplete')

    def test_transfer_close_error_never_commits_seal(self):
        root = self.lane()
        reporter = self.child.collection_reporter(SOURCE, root)
        reporter.stderr = io.StringIO()
        close = reporter._close
        def refused_close(stream, stage):
            closed = close(stream, stage)
            if Path(stream.name).name == 'pending.json':
                reporter._problem('artifact_close', OSError('owned close diagnostic'))
            return closed
        reporter._close = refused_close
        self.child.collection_reporter = lambda *args: reporter
        self.outcome = 0
        self.assertIs(self.child.dispatch_pytest(self.returned, [], source=SOURCE, out=root), self.outcome)
        self.assertTrue((root / 'collection-evidence/pending.json').is_file())
        self.assertFalse((root / 'collection-evidence/complete.json').exists())
        self.refused(root, 'collection_incomplete')

    def test_missing_reporter_does_not_call_pytest(self):
        root = self.lane()
        called = []
        with self.assertRaises(FileNotFoundError):
            self.child.dispatch_pytest(lambda *a, **k: called.append(True), [], source=self.root, out=root)
        self.assertEqual(called, [])
        self.assertFalse((root / 'phases.json').exists())
        (root / 'phases.json').write_bytes(b'{}')
        self.refused(root, 'collection_missing')

    def test_missing_marker_status_and_refusal_never_green(self):
        for index, missing in enumerate(('complete', 'complete.json', 'status.json')):
            root = self.complete('missing-' + str(index))
            path = root / 'collection-evidence' / missing
            path.rmdir() if path.is_dir() else path.unlink()
            self.refused(root, 'collection_incomplete')
        root = self.complete('refusal')
        (root / 'collection-evidence/refusal.json').write_bytes(b'{}')
        self.refused(root, 'collection_refused')

    def test_invalid_status_even_with_matching_transfer_is_refused(self):
        mutations = [('complete', False), ('session_finished', False), ('refusal_count', 1),
                     ('journal_bytes_fsynced', 0), ('returned_exitstatus', True),
                     ('primary_type', 'builtins.KeyboardInterrupt'), ('cleanup_complete', False)]
        for index, (key, value) in enumerate(mutations):
            root = self.complete('invalid-' + str(index))
            status = json.loads((root / 'collection-evidence/status.json').read_bytes())
            status[key] = value
            self.reseal(root, status)
            self.refused(root, 'collection_invalid_status_or_transfer')
        root = self.complete('missing-field')
        status = json.loads((root / 'collection-evidence/status.json').read_bytes())
        del status['phase_evidence']
        self.reseal(root, status)
        self.refused(root, 'collection_invalid_status_or_transfer')

    def test_changed_journal_and_malformed_status_are_refused(self):
        root = self.complete('drift')
        with (root / 'collection-evidence/errors.jsonl').open('ab') as stream:
            stream.write(b'{}\n')
        self.refused(root, 'collection_invalid_status_or_transfer')
        for index, raw in enumerate((b'[]', b'{', b'{"complete":true,"complete":true}')):
            root = self.complete('malformed-' + str(index))
            (root / 'collection-evidence/status.json').write_bytes(raw)
            self.refused(root, 'collection_invalid_status_or_transfer')

    def test_metadata_caps_unknown_and_nonregular_before_payload_read(self):
        opened, active = [], [True]
        def observe(event, args):
            if active[0] and event == 'open' and isinstance(args[0], (str, bytes, os.PathLike)):
                opened.append(os.fsdecode(args[0]))
        # Build all fixtures first; observer checks admission, not setup writes.
        roots = []
        root = self.complete('unknown')
        (root / 'collection-evidence/foreign.json').write_bytes(b'{}')
        roots.append((root, 'unknown_collection_member'))
        root = self.complete('nonregular')
        (root / 'collection-evidence/complete.json').unlink()
        (root / 'collection-evidence/complete.json').mkdir()
        roots.append((root, 'nonregular_member'))
        for index, name in enumerate(('errors.jsonl', 'status.json', 'complete.json')):
            root = self.complete('cap-' + str(index))
            (root / 'collection-evidence' / name).write_bytes(b'x' * (self.admission.COLLECTION_CAPS[name] + 1))
            roots.append((root, 'collection_member_too_large'))
        root = self.complete('top-cap')
        (root / 'pytest.log').write_bytes(b'x' * 9)
        sys.addaudithook(observe)
        try:
            for root, code in roots:
                self.refused(root, code)
            with self.assertRaises(self.admission.AdmissionError) as caught:
                self.admission.admit(root=self.root / 'top-cap', mode='native', limits={'log_member': 8})
            self.assertEqual(caught.exception.code, 'member_too_large')
            self.assertEqual(opened, [])
        finally:
            active[0] = False

    def test_downloaded_explicit_transfer_without_empty_directory(self):
        template = self.complete('template')
        matrix = self.root / 'matrix'
        matrix.mkdir()
        for group in self.admission.GROUPS:
            root = matrix / group
            root.mkdir()
            for name in ('receipt.json', 'source-inventory.json', 'launches.json', 'bindings.json', 'native-origins.json', 'phases.json'):
                (root / name).write_bytes(b'{}')
            directory = root / 'collection-evidence'
            directory.mkdir()
            for name in ('errors.jsonl', 'status.json', 'complete.json'):
                (directory / name).write_bytes((template / 'collection-evidence' / name).read_bytes())
        result = self.admission.admit(matrix, 'downloaded')
        self.assertEqual((result['groups'], result['files'], result['collection_complete']), (16, 144, True))
        directory = matrix / self.admission.GROUPS[-1] / 'collection-evidence'
        (directory / 'complete.json').unlink()
        with self.assertRaises(self.admission.AdmissionError) as caught:
            self.admission.admit(matrix, 'downloaded')
        self.assertEqual(caught.exception.code, 'collection_incomplete')

    def test_existing_capacity_limits_and_refusal_cli_preserved(self):
        root = self.lane('pre-pytest')
        result = self.admission.admit(root, 'native', limits={'json_member': 2, 'lane_total': 4})
        self.assertEqual((result['files'], result['bytes'], result['collection_complete']), (2, 4, False))
        self.assertEqual(self.admission.DEFAULT_LIMITS['lane_total'], 24000000)
        self.assertEqual(self.admission.DEFAULT_LIMITS['decision'], 4096)
        self.assertEqual(self.admission.COLLECTION_TOTAL, 2018432)
        (root / 'phases.json').write_bytes(b'{}')
        decision = self.root / 'decision/ci-output-admission.json'
        output = self.root / 'github-output'
        output.write_bytes(b'')
        self.assertEqual(self.admission.main(['native', '--root', str(root), '--decision', str(decision), '--github-output', str(output)]), 1)
        self.assertEqual(output.read_bytes(), b'admitted=false\nrefusal=true\n')
        refusal = json.loads(decision.read_bytes())
        self.assertEqual(refusal['code'], 'collection_missing')
        self.assertFalse(refusal['native_proof'])
        self.assertLessEqual(decision.stat().st_size, 4096)

    def test_workflow_upload_is_exact_diagnostics_allowlist(self):
        workflow = (SOURCE / '.github/workflows/memory-wiki-synthetic.yml').read_text(encoding='utf-8')
        block = workflow.split('Retain only admitted explicit safe evidence, including failures', 1)[1].split('- name: Retain tiny refusal', 1)[0]
        paths = [line.strip() for line in block.splitlines() if '/gate/public/' in line]
        prefix = '${{ runner.temp }}/memory-wiki-synthetic/gate/public/'
        expected = {prefix + name for name in self.admission.NATIVE_NAMES}
        expected |= {prefix + 'collection-evidence/' + name for name in ('errors.jsonl', 'status.json', 'complete.json', 'refusal.json')}
        self.assertEqual(set(paths), expected)
        self.assertEqual(len(paths), len(expected))
        self.assertFalse(any('*' in path for path in paths))


if __name__ == '__main__':
    unittest.main()
