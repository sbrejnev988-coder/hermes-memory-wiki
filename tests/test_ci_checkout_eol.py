"""Explicit, stdlib-only Git checkout metadata regression; not a SOURCE sandbox.

Run this file directly with --git <EXACT_GIT> --fixture-root <NEW_OWNED_ROOT>.
No product import, SDK, pytest, network, ambient Git configuration or cleanup
of prior data. Fixtures, Git intents and raw captures are retained for readback.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import time
import unittest

__test__ = False
POLICY = b'* text=auto eol=lf\n'
PUBLIC = {
    '__init__.py': (
        '16f06dbffaeccfcce7d34c7180c9929e14d7046fa3d3a1dbf276f35b6007a469',
        '4cd2aeb3d83f996bfc465ca9761ee1e014e37b303f9cf3c5cf056046b5926245'),
    'tests/fixtures/g4_original_boundary_gold.txt': (
        'bea163fe1ccbfd1963946e255abe9affcd73a148d1be9dae1a891b2f6b5476b8',
        'a4da8a8125ae9b5c68438a34478126e704696a5890ad1de1e1fc2f8788d5f61d'),
    'tests/fixtures/g4_metadata_scope.txt': (
        '260e167dfccf4abcd129baf18edfe777198ac841147f53df16e237cfa3fb937f',
        '5eb0562cd949ccbf358a883003718dd6939d91231aabab63a062acbe99e483d4'),
}
BINARY = b'\x00\x01public-binary\r\nkeep-LF\nkeep-CR\rend\xff'
UNUSUAL = 'UTF-8: ёж / 雪\nno-final-newline'.encode('utf-8')
SCENARIOS = (
    ('baseline_hostile', None, 'true', 'crlf'),
    ('candidate_hostile', POLICY, 'true', 'crlf'),
    ('candidate_false_crlf', POLICY, 'false', 'crlf'),
    ('candidate_input_lf', POLICY, 'input', 'lf'),
    ('missing_eol_hostile', b'* text=auto\n', 'true', 'crlf'),
)
METHODS = (
    'test_01_baseline_hostile_matches_observed_crlf',
    'test_02_candidate_hostile_preserves_exact_public_bytes',
    'test_03_healthy_false_and_input_preserve_exact_bytes',
    'test_04_binary_nul_is_never_line_normalized',
    'test_05_utf8_without_final_newline_is_preserved',
    'test_06_missing_eol_mutant_and_isolation_controls',
)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def layout(raw):
    crlf = raw.count(b'\r\n')
    return {'B': len(raw), 'sha256': digest(raw), 'CRLF': crlf,
            'LF_only': raw.count(b'\n') - crlf, 'CR_only': raw.count(b'\r') - crlf}


def encode(value):
    return (json.dumps(value, ensure_ascii=True, sort_keys=True,
                       separators=(',', ':'), allow_nan=False) + '\n').encode('utf-8')


def no_links(path, *, missing_leaf=False):
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts or str(path).startswith(('\\\\', '//')):
        raise ValueError('absolute_nontraversing_local_path_required')
    for part in reversed((path, *path.parents)):
        try:
            s = part.lstat()
        except FileNotFoundError:
            if missing_leaf and part == path:
                continue
            raise
        if stat.S_ISLNK(s.st_mode) or getattr(s, 'st_file_attributes', 0) & 0x400:
            raise ValueError('link_or_reparse_refused')
    return path


def save(path, value, *, raw=False):
    no_links(path.parent)
    with path.open('xb') as f:
        f.write(value if raw else encode(value))
        f.flush()
        os.fsync(f.fileno())


class CheckoutEolTests(unittest.TestCase):
    __test__ = False
    git_executable = None
    fixture_root = None
    commands = []
    observations = {}

    @classmethod
    def setUpClass(cls):
        git = no_links(Path(cls.git_executable))
        if not stat.S_ISREG(git.lstat().st_mode):
            raise ValueError('Git_regular_executable_required')
        root = no_links(Path(cls.fixture_root), missing_leaf=True)
        if root.exists():
            raise FileExistsError('fixture_root_must_be_new')
        root.mkdir()
        cls.deadline = time.monotonic() + 120
        cls.commands = []
        cls.observations = {}
        cls.root = root
        cls.repo = root / 'repository'
        home, temp = root / 'home', root / 'tmp'
        for p in (home, temp, home / 'local', home / 'roaming', root / 'empty-template', root / 'captures'):
            p.mkdir()
        global_config, system_config = home / 'global.config', home / 'system.config'
        save(global_config, b'', raw=True)
        save(system_config, b'', raw=True)
        cls.env = {
            'HOME': str(home), 'USERPROFILE': str(home), 'HERMES_HOME': str(home),
            'LOCALAPPDATA': str(home / 'local'), 'APPDATA': str(home / 'roaming'),
            'XDG_CONFIG_HOME': str(home), 'TMP': str(temp), 'TEMP': str(temp), 'TMPDIR': str(temp),
            'GIT_CONFIG_GLOBAL': str(global_config), 'GIT_CONFIG_SYSTEM': str(system_config),
            'GIT_CONFIG_NOSYSTEM': '1', 'GIT_ATTR_NOSYSTEM': '1',
            'GIT_TERMINAL_PROMPT': '0', 'GIT_PAGER': '', 'GIT_OPTIONAL_LOCKS': '0',
            'GIT_ALLOW_PROTOCOL': '', 'PATH': str(git.parent),
        }
        for key in ('SystemRoot', 'WINDIR'):
            if key in os.environ:
                cls.env[key] = os.environ[key]
        source = no_links(Path(__file__).absolute().parent.parent)
        policy = no_links(source / '.gitattributes').read_bytes()
        if policy != POLICY:
            raise AssertionError('shipped_policy_is_not_exact_canonical_LF_policy')
        cls.inputs = {}
        for rel, (canonical_sha, crlf_sha) in PUBLIC.items():
            p = no_links(source / rel)
            if p.lstat().st_size > 2000000:
                raise ValueError('public_input_cap')
            raw = p.read_bytes()
            if digest(raw) != canonical_sha or b'\r' in raw or b'\n' not in raw:
                raise AssertionError('canonical_public_input_changed:' + rel)
            if digest(raw.replace(b'\n', b'\r\n')) != crlf_sha:
                raise AssertionError('observed_CRLF_binding_changed:' + rel)
            cls.inputs[rel] = raw
        cls.inputs['binary-nul.dat'] = BINARY
        cls.inputs['unusual-utf8.txt'] = UNUSUAL
        cls.run_git('init', ['init', '--initial-branch=fixture',
                            '--template=' + str(root / 'empty-template'), str(cls.repo)], cwd=root)
        for rel, raw in cls.inputs.items():
            p = cls.repo / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            save(p, raw, raw=True)
        cls.run_git('add_public', ['add', '--', *cls.inputs])
        previous = None
        for name, attributes, autocrlf, eol in SCENARIOS:
            if attributes != previous:
                p = cls.repo / '.gitattributes'
                # Only this newly created own fixture is modified, never source/gold.
                with p.open('wb') as f:
                    f.write(attributes)
                cls.run_git('add_' + name, ['add', '--', '.gitattributes'])
                previous = attributes
            output = root / name
            output.mkdir()
            cls.run_git('checkout_' + name,
                        ['checkout-index', '--all', '--force', '--prefix=' + output.as_posix() + '/'],
                        autocrlf=autocrlf, eol=eol)
            cls.observations[name] = {rel: layout(no_links(output / rel).read_bytes())
                                      for rel in cls.inputs}
        save(root / 'observations.json', cls.observations)

    @classmethod
    def run_git(cls, label, args, *, cwd=None, autocrlf='false', eol='lf'):
        if len(cls.commands) >= 9:
            raise ValueError('Git_command_budget_exhausted')
        remaining = cls.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('packet_deadline')
        argv = [cls.git_executable, '--no-optional-locks', '-c', 'gc.auto=0',
                '-c', 'maintenance.auto=false', '-c', 'core.autocrlf=' + autocrlf,
                '-c', 'core.eol=' + eol, '-c', 'user.name=Checkout Fixture',
                '-c', 'user.email=checkout-fixture@example.invalid',
                '-C', str(cls.repo if cwd is None else cwd), *args]
        sequence = len(cls.commands) + 1
        stem = cls.root / 'captures' / ('%02d_%s' % (sequence, label))
        event = {'seq': sequence, 'label': label, 'argv': argv, 'shell': False,
                 'timeout_seconds': min(10, remaining), 'autocrlf': autocrlf, 'eol': eol}
        save(stem.with_suffix('.intent.json'), event)
        cls.commands.append(event)
        started = time.monotonic()
        try:
            p = subprocess.run(argv, cwd=str(cls.root), env=cls.env, stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False,
                               timeout=event['timeout_seconds'])
            out, err, code, timed = p.stdout, p.stderr, p.returncode, False
        except subprocess.TimeoutExpired as exc:
            out, err, code, timed = exc.stdout or b'', exc.stderr or b'', None, True
        event.update(exit_code=code, timed_out=timed, elapsed_seconds=time.monotonic()-started,
                     capture_complete=not timed, direct_child_reaped=not timed,
                     process_tree_containment='NOT_CLAIMED',
                     stdout=layout(out), stderr=layout(err))
        save(stem.with_suffix('.stdout.bin'), out, raw=True)
        save(stem.with_suffix('.stderr.bin'), err, raw=True)
        save(stem.with_suffix('.return.json'), event)
        if timed or code != 0 or len(out) > 16000 or len(err) > 16000:
            raise RuntimeError('Git_metadata_command_failed:' + label)
        return out

    def bytes_at(self, scenario, rel):
        return no_links(self.root / scenario / rel).read_bytes()

    def test_01_baseline_hostile_matches_observed_crlf(self):
        for rel, raw in self.inputs.items():
            if rel in PUBLIC:
                actual = self.bytes_at('baseline_hostile', rel)
                self.assertNotEqual(actual, raw, rel)
                self.assertEqual(actual, raw.replace(b'\n', b'\r\n'), rel)
                self.assertEqual(digest(actual), PUBLIC[rel][1], rel)
        self.assertFalse((self.root / 'baseline_hostile' / '.gitattributes').exists())

    def test_02_candidate_hostile_preserves_exact_public_bytes(self):
        for rel in PUBLIC:
            actual = self.bytes_at('candidate_hostile', rel)
            self.assertEqual(actual, self.inputs[rel], rel)
            self.assertEqual(digest(actual), PUBLIC[rel][0], rel)
            self.assertNotEqual(actual, self.bytes_at('baseline_hostile', rel), rel)
        self.assertEqual(self.bytes_at('candidate_hostile', '.gitattributes'), POLICY)

    def test_03_healthy_false_and_input_preserve_exact_bytes(self):
        for scenario in ('candidate_false_crlf', 'candidate_input_lf'):
            for rel, raw in self.inputs.items():
                self.assertEqual(self.bytes_at(scenario, rel), raw, (scenario, rel))
            self.assertEqual(self.bytes_at(scenario, '.gitattributes'), POLICY)

    def test_04_binary_nul_is_never_line_normalized(self):
        self.assertIn(b'\x00', BINARY)
        self.assertNotEqual(BINARY.replace(b'\r\n', b'\n'), BINARY)
        for scenario, _, _, _ in SCENARIOS:
            self.assertEqual(self.bytes_at(scenario, 'binary-nul.dat'), BINARY, scenario)

    def test_05_utf8_without_final_newline_is_preserved(self):
        self.assertFalse(UNUSUAL.endswith(b'\n'))
        self.assertIn('雪'.encode('utf-8'), UNUSUAL)
        for scenario in ('candidate_hostile', 'candidate_false_crlf', 'candidate_input_lf'):
            self.assertEqual(self.bytes_at(scenario, 'unusual-utf8.txt'), UNUSUAL, scenario)
        for scenario in ('baseline_hostile', 'missing_eol_hostile'):
            self.assertEqual(self.bytes_at(scenario, 'unusual-utf8.txt'),
                             UNUSUAL.replace(b'\n', b'\r\n'), scenario)

    def test_06_missing_eol_mutant_and_isolation_controls(self):
        for rel in PUBLIC:
            actual = self.bytes_at('missing_eol_hostile', rel)
            self.assertNotEqual(actual, self.inputs[rel], rel)
            self.assertEqual(actual, self.bytes_at('baseline_hostile', rel), rel)
            self.assertNotEqual(actual, self.bytes_at('candidate_hostile', rel), rel)
        self.assertEqual(self.bytes_at('missing_eol_hostile', '.gitattributes'), b'* text=auto\r\n')
        self.assertEqual(len(self.commands), 9)
        self.assertTrue(all(c['exit_code'] == 0 and c['capture_complete'] for c in self.commands))
        self.assertEqual(self.env['GIT_CONFIG_NOSYSTEM'], '1')
        for key in ('GIT_CONFIG_GLOBAL', 'GIT_CONFIG_SYSTEM'):
            p = no_links(Path(self.env[key]))
            self.assertTrue(p.is_relative_to(self.root))
            self.assertEqual(p.read_bytes(), b'')
        self.assertNotIn('PYTHONPATH', self.env)
        self.assertNotIn('GIT_CONFIG_COUNT', self.env)
        self.assertFalse((self.repo / '.git' / 'info' / 'attributes').exists())


class MetadataResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cases = []

    def addSuccess(self, test):
        super().addSuccess(test)
        self.cases.append({'id': test.id(), 'outcome': 'passed'})

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.cases.append({'id': test.id(), 'outcome': 'failed'})

    def addError(self, test, err):
        super().addError(test, err)
        self.cases.append({'id': test.id(), 'outcome': 'error'})

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self.cases.append({'id': test.id(), 'outcome': 'skipped'})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--git', required=True, help='existing exact absolute Git executable')
    parser.add_argument('--fixture-root', required=True, help='new owned fixture directory; retained, not deleted')
    args = parser.parse_args()
    CheckoutEolTests.git_executable = str(no_links(Path(args.git)))
    CheckoutEolTests.fixture_root = str(no_links(Path(args.fixture_root), missing_leaf=True))
    suite = unittest.TestSuite(CheckoutEolTests(name) for name in METHODS)
    started = time.monotonic()
    result = unittest.TextTestRunner(verbosity=2, resultclass=MetadataResult).run(suite)
    expected = [__name__ + '.CheckoutEolTests.' + name for name in METHODS]
    complete = [c['id'] for c in result.cases] == expected and result.testsRun == len(METHODS)
    properties = {}
    for name, rows in CheckoutEolTests.observations.items():
        if all(rel in rows for rel in PUBLIC):
            properties[name] = {
                'all_three_canonical': all(rows[rel]['sha256'] == PUBLIC[rel][0] for rel in PUBLIC),
                'all_three_observed_crlf': all(rows[rel]['sha256'] == PUBLIC[rel][1] for rel in PUBLIC),
            }
    imports = ('argparse', 'hashlib', 'json', 'os', 'pathlib', 'stat', 'subprocess', 'sys', 'time', 'unittest')
    report = {'schema': 'memory-stack.git-checkout-metadata/v1', 'scope': 'actual-local-Git-metadata',
              'platform': sys.platform, 'python': sys.version, 'executable': sys.executable,
              'isolated': sys.flags.isolated, 'no_site': sys.flags.no_site,
              'stdlib_import_origins': {name: getattr(sys.modules[name], '__file__', None) for name in imports},
              'nonstdlib_modules': sorted(name for name in sys.modules
                                         if name.split('.')[0] not in sys.stdlib_module_names
                                         and name != '__main__'),
              'expected': expected,
              'cases': result.cases, 'total': result.testsRun, 'failed': len(result.failures),
              'errors': len(result.errors), 'skipped': len(result.skipped),
              'roster_complete': complete, 'Git_commands': len(CheckoutEolTests.commands),
              'elapsed_seconds': time.monotonic()-started,
              'canonical_properties_observed': properties,
              'fixtures_retained': True, 'cleanup_deletion': False,
              'process_tree_containment': 'NOT_CLAIMED'}
    # Full stdout plus durable JSON; a failed roster/exit never qualifies as PASS.
    raw = encode(report)
    sys.stdout.buffer.write(raw)
    sys.stdout.buffer.flush()
    root = Path(args.fixture_root)
    if root.exists():
        save(root / 'report.json', report)
    return 0 if result.wasSuccessful() and complete else 1


if __name__ == '__main__':
    raise SystemExit(main())
