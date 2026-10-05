"""Source-only hosted CI receipts. This is not a local containment controller."""
from pathlib import Path, PurePosixPath, PureWindowsPath
import os
import json
import subprocess
import time
import sys
import hashlib
import re
import argparse
import importlib.metadata
import xml.etree.ElementTree as ET

CORE_SHA = 'd526f14714ce8a95cafd7f3a95d1eab5b6e0b910'
BASELINE_SHA = '438e0b57cb44470c2d47b9210941bea177d379f1'
DEPENDENCIES = {'pytest': '9.1.1', 'PyYAML': '6.0.3', 'ruamel.yaml': '0.18.16', 'openai': '2.24.0', 'httpx': '0.28.1', 'pydantic': '2.13.4', 'python-dotenv': '1.2.2', 'tzdata': '2025.3', 'requests': '2.33.0', 'truststore': '0.10.4', 'packaging': '26.0'}


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def execute_child(command, cwd, env, out, timeout, run=subprocess.run):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    receipt = {'command': list(command), 'timeout_seconds': timeout, 'accepted': False,
               'status': 'incomplete', 'containment': 'ephemeral hosted job; not local Job proof',
               'descendant_cleanup_proven': False, 'returncode': None}
    start = time.monotonic()
    try:
        with (out / 'pytest.log').open('wb') as log:
            completed = run(command, cwd=str(cwd), env=env, stdout=log, stderr=subprocess.STDOUT, timeout=timeout, check=False)
        receipt['returncode'] = completed.returncode
        receipt['status'] = 'process_exited'
        if (out / 'junit.xml').is_file():
            receipt['junit'] = junit_summary(out / 'junit.xml')
            receipt['accepted'] = completed.returncode == 0 and receipt['junit']['all_passed']
            receipt['status'] = 'passed' if receipt['accepted'] else 'failed_or_skipped'
    except subprocess.TimeoutExpired:
        receipt['status'] = 'incomplete_timeout'
    except Exception as exc:
        receipt['status'] = 'incomplete_error'
        receipt['error_type'] = type(exc).__name__
    finally:
        receipt['duration_seconds'] = time.monotonic() - start
        write_json(out / 'execution.json', receipt)
    return receipt



def clean_environment(ambient, runroot, core, source):
    runroot, core, source = (Path(p).resolve() for p in (runroot, core, source))
    # Explicit allowlist, never os.environ.copy(): no provider/token/auth/profile data.
    env = {k: ambient[k] for k in ('PATH', 'SystemRoot', 'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'PATHEXT', 'PROCESSOR_ARCHITECTURE', 'NUMBER_OF_PROCESSORS') if k in ambient}
    home = runroot / 'synthetic-home'
    temp = runroot / 'synthetic-temp'
    for directory in (home, temp, runroot / 'recovery-fixtures', runroot / 'bindings', runroot / 'launches'):
        directory.mkdir(parents=True, exist_ok=True)
    env.update({
        'HOME': str(home), 'USERPROFILE': str(home), 'APPDATA': str(home / 'AppData/Roaming'),
        'LOCALAPPDATA': str(home / 'AppData/Local'), 'XDG_CONFIG_HOME': str(home / 'config'),
        'XDG_CACHE_HOME': str(home / 'cache'), 'XDG_DATA_HOME': str(home / 'data'),
        'HERMES_HOME': str(home / 'hermes'), 'TEMP': str(temp), 'TMP': str(temp), 'TMPDIR': str(temp),
        'PYTHONPATH': os.pathsep.join((str(source / 'scripts/ci_owned'), str(core), str(source))),
        'PYTHONUTF8': '1', 'PYTHONDONTWRITEBYTECODE': '1', 'PYTEST_DISABLE_PLUGIN_AUTOLOAD': '1',
        'PYTHON_DOTENV_DISABLED': '1',
        'HERMES_SECURITY_STRICT': '0', 'MEMORY_WIKI_SEMANTIC': '0',
        'MEMORY_WIKI_DOCUMENT_AUTO_SCAN_CACHE': '0',
        'RECOVERY_DIAGNOSTIC_OUT': str(runroot / 'recovery-fixtures'),
        'MW_CI_CORE': str(core), 'MW_CI_SOURCE': str(source), 'MW_CI_RUNROOT': str(runroot),
        'MW_CI_BINDINGS': str(runroot / 'bindings'),
    })
    return env


def source_inventory(root, expected_sha):
    if not re.fullmatch('[0-9a-f]{40}', expected_sha):
        raise ValueError('Expected SHA must be literal lowercase 40-hex; never normalized')
    root = Path(root).resolve(strict=True)
    def git(*args):
        return subprocess.check_output(['git', '-C', str(root), *args], timeout=30)
    actual = git('rev-parse', 'HEAD').decode().strip()
    if actual != expected_sha:
        raise RuntimeError('Source SHA mismatch')
    if git('diff', '--name-only', 'HEAD', '--').strip():
        raise RuntimeError('Tracked source is dirty')
    files = {}
    for entry in git('ls-tree', '-rz', 'HEAD').split(b'\0'):
        if not entry:
            continue
        metadata, name = entry.split(b'\t', 1)
        mode, kind, blob = metadata.decode().split()
        relative = name.decode('utf-8')
        path = root / relative
        if kind != 'blob' or path.is_symlink() or not path.is_file():
            raise RuntimeError('Nonregular tracked source: ' + relative)
        data = path.read_bytes()
        files[relative] = {'git_blob': blob, 'mode': mode, 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}
    encoded = json.dumps(files, sort_keys=True, separators=(',', ':')).encode()
    return {'sha': actual, 'files': files, 'raw_tree_sha256': hashlib.sha256(encoded).hexdigest()}


def binding_coverage(launches, bindings, contract):
    """Compare real launch identities, not just the receipt files that survived.

    This pure validator can be unit-tested with synthetic dictionaries. Such
    tests do not establish that the hosted recorder/native SDK actually ran.
    """
    errors, killed = [], []
    def refuse(code, identity=''):
        errors.append(code + (':' + identity if identity else ''))
    try:
        launched = {row['launch_id']: row for row in launches}
        received = {row['launch_id']: row for row in bindings}
        if not launched or len(launched) != len(launches) or len(received) != len(bindings):
            refuse('empty_or_duplicate_identity')
        if set(launched) != set(received):
            refuse('launch_receipt_identity_set_mismatch')
        controller = 'controller-' + contract['run_id']
        primaries = [row for row in launches if row.get('owner_id') == controller]
        if len(primaries) != 1 or primaries[0].get('role') != 'plugin':
            refuse('missing_or_invalid_primary')
        for identity, launch in launched.items():
            if not re.fullmatch('[0-9a-f]{32}', identity):
                refuse('invalid_launch_identity', identity)
            owner = launch.get('owner_id')
            seen = {identity}
            while owner != controller:
                if owner not in launched or owner in seen:
                    refuse('unrecognized_or_cyclic_owner', identity)
                    break
                seen.add(owner)
                owner = launched[owner].get('owner_id')
            role = launch.get('role')
            if role not in ('plugin', 'plugin_capable', 'nonplugin_worker'):
                refuse('unrecognized_process_role', identity)
            if launch.get('status') != 'exited' or type(launch.get('pid')) is not int or launch['pid'] <= 0 or type(launch.get('returncode')) is not int:
                refuse('launch_not_observed_exited', identity)
            if launch.get('same_interpreter') is not True or launch.get('site_enabled') is not True or launch.get('executable') != contract['executable']:
                refuse('foreign_or_no_site_interpreter', identity)
            if launch.get('run_id') != contract['run_id']:
                refuse('foreign_run', identity)
            binding = received.get(identity)
            if binding is None:
                continue
            for field in ('run_id', 'owner_id', 'role', 'command_sha256', 'executable'):
                if binding.get(field) != launch.get(field):
                    refuse('binding_identity_' + field, identity)
            # Windows venv launchers may start the actual interpreter as their
            # direct child. The unique per-launch nonce still must match exactly.
            pid_matches = binding.get('pid') == launch.get('pid')
            launcher_matches = contract.get('platform') == 'win32' and launch.get('venv_launcher') is True and binding.get('ppid') == launch.get('pid') and type(binding.get('pid')) is int and binding['pid'] > 0
            if not (pid_matches or launcher_matches):
                refuse('binding_pid_mismatch', identity)
            for field in ('source_sha', 'core_sha', 'memory_provider_origin', 'memory_provider_sha256'):
                if binding.get(field) != contract[field]:
                    refuse('native_contract_' + field, identity)
            if binding.get('started') is not True or binding.get('native_class_module') != 'agent.memory_provider' or binding.get('violations') != []:
                refuse('native_bootstrap_or_violation', identity)
            classes = binding.get('plugin_classes')
            if not isinstance(classes, list):
                refuse('malformed_plugin_classes', identity)
                continue
            for cls in classes:
                path_type = PureWindowsPath if contract.get('platform') == 'win32' else PurePosixPath
                source_origin = cls.get('origin_role') == 'source' and cls.get('origin') == contract['source_origin']
                byte_copy = (cls.get('origin_role') == 'synthetic_installed_byte_copy'
                             and bool(contract.get('runroot')) and bool(contract.get('source_sha256'))
                             and path_type(cls.get('origin', '')).is_relative_to(path_type(contract['runroot']))
                             and cls.get('source_sha256') == contract['source_sha256'])
                if cls.get('native_MRO') is not True or not (source_origin or byte_copy):
                    refuse('plugin_origin_or_MRO', identity)
            if (role == 'plugin' or binding.get('plugin_attempted') is True) and not any(cls.get('native_MRO') is True and (role != 'plugin' or cls.get('module') == 'memory_wiki') for cls in classes):
                refuse('plugin_role_without_MRO', identity)
            if role == 'nonplugin_worker' and classes:
                refuse('nonplugin_role_loaded_plugin', identity)
            state = binding.get('state')
            finished = binding.get('finished') is True and state == 'finished'
            expectation = launch.get('expectation')
            expected_kill = (role == 'nonplugin_worker' and launch.get('lifecycle') == 'may_terminate'
                             and isinstance(expectation, dict) and expectation.get('explicit') is True
                             and bool(expectation.get('reason'))
                             and expectation.get('command_sha256') == launch.get('command_sha256')
                             and binding.get('nonplugin_guard_armed') is True and not classes
                             and state == 'native_ready' and binding.get('finished') is False
                             and type(launch.get('returncode')) is int and launch['returncode'] not in (0, 86))
            if not finished and not expected_kill:
                refuse('unfinished_or_abnormal_bootstrap', identity)
            if expected_kill:
                killed.append(identity)
            if launch.get('returncode') != 0 and not expected_kill:
                refuse('unexpected_process_exit', identity)
            if launch.get('returncode') == 86:
                refuse('abnormal_bootstrap_exit', identity)
    except (KeyError, TypeError, ValueError, AttributeError):
        refuse('malformed_binding_inventory')
    return {'verified': bool(launches) and not errors, 'errors': sorted(set(errors)),
            'launches': len(launches), 'receipts': len(bindings),
            'explicit_nonplugin_terminations': killed}


def verify_lane_bindings(launches, bindings, contract, origins):
    result = binding_coverage(launches, bindings, contract)
    base = origins.get('modules', {}).get('agent.memory_provider', {})
    if (origins.get('native_MRO') is not True or base.get('origin') != contract.get('memory_provider_origin')
            or base.get('sha256') != contract.get('memory_provider_sha256')):
        result['verified'] = False
        result['errors'].append('primary_native_origins_mismatch')
    return result


def matrix_coverage(records, source_sha, versions=('3.11', '3.12', '3.13', '3.14')):
    expected = {(platform, version, stage) for platform in ('linux', 'win32') for version in versions for stage in ('full', 'recovery')}
    keyed = {(r['platform'], r['python'], r['stage']): r for r in records}
    if len(keyed) != len(records) or set(keyed) != expected:
        raise RuntimeError('Missing, duplicate or unexpected matrix lane')
    if len({r['source_digest'] for r in records}) != 1:
        raise RuntimeError('Matrix source bytes differ')
    for r in records:
        if r['source_sha'] != source_sha or r['core_sha'] != CORE_SHA or not r['complete'] or not r['bindings_verified'] or r['failed'] or r['errors']:
            raise RuntimeError('Failed/incomplete/unbound matrix lane')
        if set(r['passed']) & set(r['skipped']) or set(r['collected']) != set(r['passed']) | set(r['skipped']):
            raise RuntimeError('Unaccounted or multiply classified collected nodes')
        if r['stage'] == 'recovery' and r['skipped']:
            raise RuntimeError('Recovery assertion skipped')
    coverage = []
    for version in versions:
        for stage in ('full', 'recovery'):
            pair = [keyed[(platform, version, stage)] for platform in ('linux', 'win32')]
            nodes = set(pair[0]['collected'])
            if not nodes or nodes != set(pair[1]['collected']):
                raise RuntimeError('Cross-platform collection mismatch')
            passed = set(pair[0]['passed']) | set(pair[1]['passed'])
            if nodes != passed:
                raise RuntimeError('Collected node never actually passed on either platform')
            coverage.append({'python': version, 'stage': stage, 'collected': len(nodes), 'actual_pass_union': len(passed)})
    return {'accepted': True, 'source_sha': source_sha, 'core_sha': CORE_SHA, 'lanes': len(records),
            'platform_skips': sum(len(r['skipped']) for r in records), 'coverage': coverage,
            'skip_counted_as_pass': False, 'local_Job_cap_proven': False}


def classify_phases(data):
    result = {'collected': data['collected'], 'passed': [], 'skipped': [], 'failed': [], 'errors': list(data['collection_errors']), 'complete': False}
    if len(set(data['collected'])) != len(data['collected']):
        raise RuntimeError('Duplicate collected node')
    for node in data['collected']:
        rows = [r for r in data['phases'] if r['nodeid'] == node]
        by_phase = {r['when']: r for r in rows}
        if len(rows) != len(by_phase):
            result['errors'].append(node)
        elif any(r['outcome'] == 'failed' for r in rows):
            result['failed' if by_phase.get('call', {}).get('outcome') == 'failed' else 'errors'].append(node)
        elif any(r.get('wasxfail') for r in rows):
            result['errors'].append(node)
        elif len(rows) >= 2 and any(r['outcome'] == 'skipped' for r in rows) and by_phase.get('teardown', {}).get('outcome') == 'passed':
            result['skipped'].append(node)
        elif set(by_phase) == {'setup', 'call', 'teardown'} and all(r['outcome'] == 'passed' for r in rows):
            result['passed'].append(node)
        else:
            result['errors'].append(node)
    result['complete'] = bool(data['collected']) and data['session_finished'] and data['exitstatus'] == 0 and not result['failed'] and not result['errors']
    return result


def prepare_runtime(purelib, scripts, config):
    target = Path(purelib) / '_memory_wiki_synthetic_ci.pth'
    if target.exists():
        raise RuntimeError('Do not overwrite another runtime hook')
    target.write_text(str(Path(scripts).resolve()) + '\n' + 'import ci_bootstrap; ci_bootstrap.configure(' + repr(str(Path(config).resolve())) + ')\n', encoding='utf-8')
    return target


def require_hosted(env):
    if env.get('GITHUB_ACTIONS') != 'true' or env.get('RUNNER_ENVIRONMENT') != 'github-hosted':
        raise RuntimeError('Native FULL/recovery is admitted only on ephemeral GitHub-hosted runners')


def junit_summary(path):
    root = ET.parse(path).getroot()
    cases = list(root.iter('testcase'))
    counts = {name: sum(case.find(tag) is not None for case in cases)
              for name, tag in [('failed', 'failure'), ('errors', 'error'), ('skipped', 'skipped')]}
    counts['tests'] = len(cases)
    counts['passed'] = sum(not any(case.find(tag) is not None for tag in ('failure', 'error', 'skipped')) for case in cases)
    counts['all_passed'] = bool(cases) and counts['passed'] == len(cases)
    suites = list(root.iter('testsuite'))
    for key, actual in [('tests', len(cases)), ('failures', counts['failed']), ('errors', counts['errors']), ('skipped', counts['skipped'])]:
        if all(key in suite.attrib for suite in suites) and sum(int(s.attrib[key]) for s in suites) != actual:
            raise ValueError('JUnit declared/observed mismatch: ' + key)
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('preflight', 'run', 'aggregate'))
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--sha', required=True)
    parser.add_argument('--core', type=Path)
    parser.add_argument('--run-root', type=Path, required=True)
    parser.add_argument('--stage', choices=('full', 'recovery'))
    parser.add_argument('--receipts', type=Path)
    args = parser.parse_args()
    source = args.source.resolve(strict=True)
    root = args.run_root.resolve()
    public = root / 'public'
    public.mkdir(parents=True, exist_ok=True)
    receipt = {'source_sha': args.sha, 'core_sha': CORE_SHA, 'baseline_sha': BASELINE_SHA,
               'platform': sys.platform, 'python': '.'.join(map(str, sys.version_info[:2])),
               'interpreter': {'executable': sys.executable, 'version': sys.version, 'prefix': sys.prefix, 'base_prefix': sys.base_prefix},
               'stage': args.stage, 'complete': False, 'bindings_verified': False,
               'collected': [], 'passed': [], 'skipped': [], 'failed': [], 'errors': [],
               'accepted': False, 'source_digest': None,
               'local_Job_cap_proven': False, 'source_only_synthetic': True,
               'security_mode': 'offline test policy0; not strict trust or live security proof'}
    try:
        inventory = source_inventory(source, args.sha)
        receipt['source_digest'] = inventory['raw_tree_sha256']
        write_json(public / 'source-inventory.json', inventory)
        if args.mode == 'aggregate':
            if args.receipts is None:
                raise RuntimeError('Aggregate requires downloaded explicit lane receipts')
            records = []
            for path in args.receipts.glob('*/receipt.json'):
                lane = json.loads(path.read_text(encoding='utf-8'))
                contract = lane['binding_contract']
                if contract['source_sha'] != args.sha or contract['core_sha'] != CORE_SHA or contract['source_sha256'] != inventory['files']['__init__.py']['sha256']:
                    raise RuntimeError('Downloaded binding contract differs from exact source/core')
                read = lambda name: json.loads((path.parent / name).read_text(encoding='utf-8'))
                proof = verify_lane_bindings(read('launches.json'), read('bindings.json'), contract, read('native-origins.json'))
                # Never trust a downloaded bindings_verified boolean in isolation.
                lane['bindings_verified'] = proof['verified']
                records.append(lane)
            if any(r['source_digest'] != inventory['raw_tree_sha256'] for r in records):
                raise RuntimeError('Downloaded receipts are not bound to aggregate checkout bytes')
            result = matrix_coverage(records, args.sha)
            receipt.update({'accepted': True, 'complete': True, 'bindings_verified': True, 'status': 'matrix_actual_pass_coverage_verified', 'stage': 'matrix'})
            write_json(public / 'matrix-coverage.json', result)
            print(json.dumps(result))
            return 0
        if args.core is None:
            raise RuntimeError('Core path required')
        core = args.core.resolve(strict=True)
        actual_core = subprocess.check_output(['git', '-C', str(core), 'rev-parse', 'HEAD'], timeout=30, text=True).strip()
        origin = subprocess.check_output(['git', '-C', str(core), 'remote', 'get-url', 'origin'], timeout=30, text=True).strip()
        if actual_core != CORE_SHA or origin not in ('https://github.com/NousResearch/hermes-agent', 'https://github.com/NousResearch/hermes-agent.git'):
            raise RuntimeError('Native core is not the verified immutable official checkout')
        subprocess.run(['git', '-C', str(core), 'diff', '--quiet', 'HEAD', '--'], timeout=30, check=True)
        receipt['native_core_origin'] = origin
        if args.mode == 'preflight':
            receipt['status'] = 'metadata_preflight_only_no_native_import'
            print(json.dumps({'status': receipt['status'], 'source_sha': args.sha, 'core_sha': CORE_SHA, 'tracked_files': len(inventory['files'])}))
            return 0
        require_hosted(os.environ)
        if args.stage is None or sys.prefix == sys.base_prefix:
            raise RuntimeError('Run requires explicit stage and an ephemeral dependency venv')
        receipt['dependencies'] = {name: importlib.metadata.version(name) for name in DEPENDENCIES}
        if receipt['dependencies'] != DEPENDENCIES:
            raise RuntimeError('CI dependency versions differ from declared native import contract')
        # New disposable synthetic environment; never collect ambient credentials.
        env = clean_environment(os.environ, root, core, source)
        config = root / 'runtime.json'
        from ci_process import LaunchRecorder
        import uuid
        base_file = (core / 'agent/memory_provider.py').resolve(strict=True)
        contract = {'core': str(core), 'source': str(source), 'bindings': str(root / 'bindings'),
                    'runroot': str(root), 'core_sha': CORE_SHA, 'source_sha': args.sha,
                    'run_id': uuid.uuid4().hex, 'platform': sys.platform, 'executable': str(Path(sys.executable).resolve()),
                    'memory_provider_origin': str(base_file),
                    'memory_provider_sha256': hashlib.sha256(base_file.read_bytes()).hexdigest(),
                    'source_origin': str((source / '__init__.py').resolve(strict=True)),
                    'source_sha256': inventory['files']['__init__.py']['sha256'], 'hosted_ephemeral': True}
        receipt['binding_contract'] = contract
        if any(any((root / name).iterdir()) for name in ('bindings', 'launches')):
            raise RuntimeError('Refuse stale native binding/launch evidence; no cleanup or reset')
        write_json(config, contract)
        import sysconfig
        purelib = Path(sysconfig.get_path('purelib')).resolve(strict=True)
        if not purelib.is_relative_to(Path(sys.prefix).resolve()):
            raise RuntimeError('Refuse shared/system site-packages')
        prepare_runtime(purelib, source / 'scripts/ci_owned', config)
        command = [sys.executable, '-B', str(source / 'scripts/ci_owned/ci_child.py'), args.stage]
        recorder = LaunchRecorder(contract, 'controller-' + contract['run_id']).install()
        try:
            with recorder.expect_primary(command):
                execution = execute_child(command, source, env, public, 1800 if args.stage == 'full' else 600)
        finally:
            recorder.uninstall()
        receipt['execution'] = execution
        if (public / 'phases.json').is_file():
            classified = classify_phases(json.loads((public / 'phases.json').read_text(encoding='utf-8')))
            receipt.update(classified)
        bindings = [json.loads(p.read_text(encoding='utf-8')) for p in (root / 'bindings').glob('*.json')]
        write_json(public / 'bindings.json', bindings)
        launches = [json.loads(p.read_text(encoding='utf-8')) for p in (root / 'launches').glob('*.json')]
        write_json(public / 'launches.json', launches)
        origins = json.loads((public / 'native-origins.json').read_text(encoding='utf-8')) if (public / 'native-origins.json').is_file() else {}
        proof = verify_lane_bindings(launches, bindings, contract, origins)
        write_json(public / 'binding-coverage.json', proof)
        receipt['bindings_verified'] = proof['verified']
        receipt['binding_errors'] = proof['errors']
        if source_inventory(source, args.sha) != inventory:
            raise RuntimeError('Tracked source bytes changed during test execution')
        subprocess.run(['git', '-C', str(core), 'diff', '--quiet', 'HEAD', '--'], timeout=30, check=True)
        summary = execution.get('junit', {})
        counts_match = (summary.get('tests') == len(receipt['collected']) and summary.get('passed') == len(receipt['passed']) and summary.get('skipped') == len(receipt['skipped']))
        receipt['complete'] = receipt['complete'] and execution['returncode'] == 0 and counts_match and receipt['bindings_verified']
        if args.stage == 'recovery':
            receipt['complete'] = receipt['complete'] and len(receipt['collected']) == 6 and not receipt['skipped']
            names = ('scanner-control', 'public-tool-error-decoded', 'raised-mutation-error-decoded', 'success-summary-decoded', 'char-overflow-state', 'list-overflow-state')
            observations = {name: json.loads((root / 'recovery-fixtures' / (name + '.json')).read_text(encoding='utf-8')) for name in names if (root / 'recovery-fixtures' / (name + '.json')).is_file()}
            write_json(public / 'recovery-observations.json', observations)
            receipt['complete'] = receipt['complete'] and len(observations) == len(names)
        receipt['accepted'] = receipt['complete'] and not receipt['skipped']
        receipt['status'] = ('passed' if receipt['accepted'] else 'completed_with_skips_requires_matrix_coverage') if receipt['complete'] else 'failed_or_incomplete'
        print(json.dumps({'status': receipt['status'], 'collected': len(receipt['collected']), 'passed': len(receipt['passed']), 'skipped': len(receipt['skipped'])}))
        # Lane completion is not a full green assertion: aggregate requires real
        # complementary OS passes for every skipped node and every Python version.
        return 0 if receipt['complete'] else 1
    except Exception as exc:
        receipt['status'] = 'blocked_or_failed'
        receipt['error_type'] = type(exc).__name__
        receipt['error'] = str(exc)
        receipt['complete'] = False
        print('CI gate refused: ' + str(exc), file=sys.stderr)
        return 1
    finally:
        write_json(public / 'receipt.json', receipt)


if __name__ == '__main__':
    raise SystemExit(main())
