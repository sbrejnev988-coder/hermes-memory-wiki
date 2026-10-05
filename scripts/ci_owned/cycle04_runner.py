"""Конечный stdlib unit gate: нет ожидания marker, native SDK или запуска argv тестов."""
from pathlib import Path
import argparse
import datetime
import hashlib
import importlib.util
import io
import json
import os
import stat
import subprocess
import sys
import tempfile
import time
import unittest
import xml.etree.ElementTree as ET

N = Path(__file__).resolve().parents[2]
P = N.parents[1]
E = P / 'evidence/release-ci-binding-fix-cycle04-20261004'
B = P / 'continuation/release-ci-binding-fix-cycle03-20261004'
OLD = P / 'continuation/release-ci-binding-fix-20261004'
REG = json.loads((E / 'cycle-04-registration.json').read_text(encoding='utf-8'))
DENIALS = []
EXECUTED_SOURCE = set()


def digest(path):
    data = Path(path).read_bytes()
    return {'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}


def composite(files):
    return hashlib.sha256(json.dumps(files, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()


def inventory(root):
    root = Path(root)
    files = {}
    stack = [root]
    while stack:
        for entry in os.scandir(stack.pop()):
            info = entry.stat(follow_symlinks=False)
            if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 1024:
                raise RuntimeError('Reparse запрещён в immutable/owned inventory')
            if stat.S_ISDIR(info.st_mode):
                stack.append(Path(entry.path))
            elif stat.S_ISREG(info.st_mode):
                files[Path(entry.path).relative_to(root).as_posix()] = digest(entry.path)
            else:
                raise RuntimeError('Нерегулярный artifact')
    return dict(sorted(files.items()))


def save(path, value):
    with Path(path).open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def load_file(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def full_resources():
    helper = load_file(E / 'cycle04_prepare.py', 'cycle04_resource_helper')
    return helper.resources()


class RetainedTemporaryDirectory(tempfile.TemporaryDirectory):
    """Сохраняет existing unit fixtures без изменения assertion bodies и без cleanup."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._finalizer.detach()

    def cleanup(self):
        self._finalizer.detach()


class Result(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.rows = {}
        self.subtests = []

    def startTest(self, test):
        super().startTest(test)
        self.rows[test.id()] = {'status': None, 'message': '', 'started': time.monotonic()}

    def record(self, test, status, message):
        row = self.rows[test.id()]
        if row['status'] != 'error' or status == 'error':
            row['status'] = status
        row['message'] += message

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.record(test, 'failure', self._exc_info_to_string(err, test))

    def addError(self, test, err):
        super().addError(test, err)
        self.record(test, 'error', self._exc_info_to_string(err, test))

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self.record(test, 'skipped', reason)

    def addExpectedFailure(self, test, err):
        super().addExpectedFailure(test, err)
        self.record(test, 'error', 'xfail запрещён для этого gate\n')

    def addUnexpectedSuccess(self, test):
        super().addUnexpectedSuccess(test)
        self.record(test, 'error', 'XPASS запрещён для этого gate\n')

    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        status = None if err is None else ('failure' if issubclass(err[0], test.failureException) else 'error')
        self.subtests.append({'method': test.id(), 'subtest': subtest.id(), 'status': status or 'passed'})
        if status:
            self.record(test, status, self._exc_info_to_string(err, subtest))

    def stopTest(self, test):
        self.rows[test.id()]['seconds'] = time.monotonic() - self.rows[test.id()].pop('started')
        super().stopTest(test)


def install_guard(runroot, extra_read_files=()):
    read_roots = [N, E, Path(sys.base_prefix)] + [Path(root) for root in REG['prior_CI_roots_and_evidence_immutable']]
    read_roots += [Path(path) for path in extra_read_files]
    immutable = [E / 'owner-decision.json', E / 'cycle-04-registration.json']
    executed_roots = [N, OLD / 'scripts/ci_owned', Path(sys.base_prefix)]
    def allowed(path, roots):
        return any(path.is_relative_to(root) for root in roots)
    def refusal(event, reason):
        DENIALS.append({'event': event, 'reason_ru': reason, 'refused': True})
        raise PermissionError(reason)
    def pathcheck(value, writing=False):
        path = Path(os.fsdecode(value)).resolve()
        if 'site-packages' in path.parts:
            refusal('open', 'Запрещены borrowed site-packages')
        if writing:
            if not path.is_relative_to(runroot) or path in immutable:
                refusal('open', 'Запись только в текущие owned evidence/fixtures')
        elif not allowed(path, read_roots):
            refusal('open', 'Private/core/чужой файл вне frozen inputs')
        return path
    def guard(event, args):
        if event == 'import':
            name = args[0]
            if name.split('.')[0] in ('agent', 'hermes_cli', 'hermes', 'gateway', 'memory_wiki', 'openai', 'httpx', 'requests', 'dotenv', 'pytest'):
                refusal(event, 'Native/plugin/provider import запрещён')
        if event == 'exec':
            name = args[0].co_filename
            if not name.startswith('<'):
                path = Path(name).resolve()
                if not allowed(path, executed_roots) and path != E / 'cycle04_prepare.py':
                    refusal(event, 'Нет выполнения synthetic fixtures или постороннего source')
                if path.is_relative_to(N) or path.is_relative_to(OLD / 'scripts/ci_owned') or path == E / 'cycle04_prepare.py':
                    EXECUTED_SOURCE.add(str(path))
        if event.startswith('socket.') or event in ('subprocess.Popen', '_winapi.CreateProcess', 'os.system', 'os.posix_spawn', 'os.fork', 'os.forkpty', 'os.exec', 'os.spawn', 'ctypes.dlopen', 'ctypes.dlsym'):
            refusal(event, 'Нет сети, child/native/runtime launch в unit worker')
        if event in ('os.remove', 'os.rmdir', 'shutil.rmtree'):
            refusal(event, 'Cleanup не разрешён')
        if event == 'open' and not isinstance(args[0], int):
            flags = args[2]
            pathcheck(args[0], bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)))
        if event in ('os.mkdir', 'os.rename', 'os.chmod', 'os.link', 'os.symlink', 'os.truncate', 'os.utime'):
            values = args[:2] if event in ('os.rename', 'os.link', 'os.symlink') else args[:1]
            for value in values:
                if isinstance(value, (str, bytes, os.PathLike)):
                    pathcheck(value, True)
    sys.addaudithook(guard)
    controls = [('subprocess.Popen', ('never-launched', [])), ('_winapi.CreateProcess', ()),
                ('socket.connect', (None, ('synthetic.invalid', 443))), ('socket.getaddrinfo', ('synthetic.invalid', 443)),
                ('import', ('agent.memory_provider',)), ('import', ('openai',)),
                ('open', ('C:/ci-cycle04-forbidden/auth.json', 'r', 0)),
                ('open', (str(N / 'scripts/ci_owned/ci_process.py'), 'w', os.O_WRONLY)),
                ('open', (str(immutable[0]), 'w', os.O_WRONLY)),
                ('open', (str(OLD / 'scripts/ci_owned/ci_process.py'), 'w', os.O_WRONLY)),
                ('os.remove', (str(runroot / 'never-created'),))]
    for event, args in controls:
        try:
            sys.audit(event, *args)
        except PermissionError:
            DENIALS[-1]['synthetic_event_only'] = True
        else:
            raise AssertionError('Guard пропустил negative control: ' + event)


def synthetic_metadata_adapter(metadata, expected):
    """Старый unit git-stdout fixture; не public Git readback и не native proof."""
    def output(command, **kwargs):
        if command[:3] != ['git', '-C', str(metadata.resolve())]:
            raise PermissionError('Нет иных git/runtime команд')
        tail = command[3:]
        if tail == ['rev-parse', 'HEAD']:
            return (expected + '\n').encode()
        if tail == ['diff', '--name-only', 'HEAD', '--']:
            return b''
        if tail != ['ls-tree', '-rz', 'HEAD']:
            raise PermissionError('Unknown metadata unit command')
        return ('100644 blob ' + '0' * 40 + '\t__init__.py\0').encode()
    return output


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('gate', choices=['exit-before-red', 'exit-partial-green', 'entry-red', 'entry-green', 'final-green'])
    args = parser.parse_args()
    assert sys.flags.isolated and sys.flags.no_site and sys.dont_write_bytecode
    assert sys.version_info[:3] == (3, 14, 7)
    runroot = E / 'gates' / args.gate
    assert runroot.is_dir() and not (runroot / 'result.json').exists()
    fixtures = runroot / 'fixtures'
    fixtures.mkdir()
    keep = {name: os.environ[name] for name in ('SystemRoot', 'SYSTEMROOT', 'WINDIR') if name in os.environ}
    os.environ.clear()
    os.environ.update(keep)
    for name in ('HOME', 'USERPROFILE', 'APPDATA', 'LOCALAPPDATA', 'HERMES_HOME', 'TEMP', 'TMP', 'TMPDIR'):
        os.environ[name] = str(fixtures)
    os.environ['MW_CI_UNIT_FIXTURES'] = str(fixtures)
    tempfile.tempdir = str(fixtures)
    tempfile.TemporaryDirectory = RetainedTemporaryDirectory
    before = inventory(N)
    baseline = inventory(B)
    assert baseline == REG['baseline_files']
    install_guard(runroot)
    sys.path.insert(0, str(N / 'tests/ci_owned'))
    binding = load_file(N / 'tests/ci_owned/binding_cases.py', 'binding_cases')
    if args.gate == 'exit-before-red':
        binding.SCRIPTS = OLD / 'scripts/ci_owned'
    names = ['exit_cases.py'] if args.gate.startswith('exit-') else (['entry_cases.py'] if args.gate.startswith('entry-') else ['contract_cases.py', 'binding_cases.py', 'exit_cases.py', 'entry_cases.py'])
    modules = [binding if name == 'binding_cases.py' else load_file(N / 'tests/ci_owned' / name, Path(name).stem) for name in names]
    metadata = fixtures / 'synthetic-git-output-data'
    if args.gate == 'final-green':
        metadata.mkdir()
        old_fixture = E.parent / 'release-ci-binding-fix-cycle03-20261004/fixtures-exit-red/synthetic-git-output-data/__init__.py'
        (metadata / '__init__.py').write_bytes(old_fixture.read_bytes())
        os.environ['MW_CI_METADATA_SOURCE'] = str(metadata)
        os.environ['MW_CI_METADATA_SHA'] = '438e0b57cb44470c2d47b9210941bea177d379f1'
    suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromModule(module) for module in modules)
    expected_methods = suite.countTestCases()
    stream = io.StringIO()
    original = subprocess.check_output
    started = time.monotonic()
    try:
        if args.gate == 'final-green':
            subprocess.check_output = synthetic_metadata_adapter(metadata, os.environ['MW_CI_METADATA_SHA'])
        result = unittest.TextTestRunner(stream=stream, verbosity=2, resultclass=Result).run(suite)
    finally:
        subprocess.check_output = original
    elapsed = time.monotonic() - started
    assert inventory(N) == before, 'Source изменён во время gate'
    assert inventory(B) == baseline, 'Baseline изменён'
    counts = {'tests': len(result.rows), 'failures': sum(row['status'] == 'failure' for row in result.rows.values()),
              'errors': sum(row['status'] == 'error' for row in result.rows.values()),
              'skipped': sum(row['status'] == 'skipped' for row in result.rows.values())}
    counts['passed'] = counts['tests'] - counts['failures'] - counts['errors'] - counts['skipped']
    assert counts['tests'] == result.testsRun == expected_methods
    xml = ET.Element('testsuites')
    group = ET.SubElement(xml, 'testsuite', name=args.gate, time=str(elapsed), **{key: str(value) for key, value in counts.items() if key != 'passed'})
    for name, row in result.rows.items():
        case = ET.SubElement(group, 'testcase', name=name, classname=name.rsplit('.', 1)[0], time=str(row['seconds']))
        if row['status']:
            ET.SubElement(case, row['status']).text = row['message']
    ET.ElementTree(xml).write(runroot / 'junit.xml', encoding='utf-8', xml_declaration=True)
    with (runroot / 'tests.log').open('x', encoding='utf-8', newline='\n') as log:
        log.write(stream.getvalue())
    code = 0 if counts['passed'] == counts['tests'] and result.wasSuccessful() else 1
    observations = [row for module in modules for row in getattr(module, 'OBSERVATIONS', [])]
    receipt = {'schema': 'ci-cycle04-actual-unit-result-v1', 'gate': args.gate,
               'at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
               'command': [sys.executable, '-I', '-S', '-B', str(Path(__file__).resolve()), args.gate],
               'counts': counts, 'unit_result_code': code, 'duration_seconds': elapsed,
               'method_ids': sorted(result.rows), 'subtests': result.subtests,
               'assertion_failure_events': len(result.failures), 'assertion_error_events': len(result.errors),
               'complete_JUnit': True, 'source_unchanged_during_gate': True,
               'source_files': before, 'source_fingerprint': composite(before),
               'predicate_source_root': str(OLD if args.gate == 'exit-before-red' else N),
               'executed_source_files': {path: digest(path) for path in sorted(EXECUTED_SOURCE)},
               'runner': digest(__file__), 'prepare_helper': digest(E / 'cycle04_prepare.py'),
               'tests_log': digest(runroot / 'tests.log'), 'JUnit': digest(runroot / 'junit.xml'),
               'denials': list(DENIALS), 'observations': observations,
               'native_runtime_MRO_proof': False, 'synthetic_unit_data_only': True,
               'actual_test_command_launches': 0, 'recorder_install': False, 'bootstrap_configure': False,
               'metadata_transport_ru': 'Только final: старый synthetic git stdout adapter и byte-exact fixture; не public Git/native proof.',
               'cleanup': False, 'site_packages_imported': False}
    save(runroot / 'result.json', receipt)
    print(json.dumps({'gate': args.gate, 'unit_result_code': code, 'counts': counts, 'source_fingerprint': composite(before)}))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
