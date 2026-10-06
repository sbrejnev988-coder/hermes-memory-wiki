"""Одна конечная foreground-команда; записывает фактический exit unit worker после завершения."""
from pathlib import Path
import datetime
import json
import os
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cycle04_runner import E, N, digest, inventory, composite, save, full_resources


def main():
    gate = sys.argv[1]
    assert gate in ('exit-before-red', 'exit-partial-green', 'entry-red', 'entry-green', 'final-green')
    assert sys.flags.isolated and sys.flags.no_site and sys.dont_write_bytecode
    runroot = E / 'gates' / gate
    runroot.mkdir(parents=True, exist_ok=False)
    before = inventory(N)
    before_resources = full_resources()
    command = [sys.executable, '-I', '-S', '-B', str(N / 'scripts/ci_owned/cycle04_runner.py'), gate]
    env = {name: os.environ[name] for name in ('SystemRoot', 'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'PATHEXT') if name in os.environ}
    for name in ('HOME', 'USERPROFILE', 'APPDATA', 'LOCALAPPDATA', 'HERMES_HOME', 'TEMP', 'TMP', 'TMPDIR'):
        env[name] = str(runroot)
    receipt = {'schema': 'ci-cycle04-finite-command-v1', 'gate': gate, 'command': command,
               'control_command': [sys.executable, '-I', '-S', '-B', str(Path(__file__).resolve()), gate],
               'cwd': str(runroot), 'outer_timeout_seconds': 60, 'at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
               'timed_out': False, 'actual_exit': None, 'complete': False,
               'python': sys.executable, 'version': sys.version, 'environment_keys': sorted(env),
               'credential_environment_inherited': False, 'resources_before': before_resources,
               'source_files_before': before, 'source_fingerprint': composite(before),
               'launcher': digest(__file__), 'runner': digest(N / 'scripts/ci_owned/cycle04_runner.py'),
               'test_command_processes_launched': 0, 'native_runtime_proof': False,
               'actual_isolated_unit_workers_launched': 1}
    start = time.monotonic()
    code = 2
    try:
        with (runroot / 'stdout.log').open('xb') as out, (runroot / 'stderr.log').open('xb') as err:
            try:
                completed = subprocess.run(command, cwd=runroot, env=env, stdout=out, stderr=err,
                                           timeout=60, check=False, shell=False)
                receipt['actual_exit'] = completed.returncode
                code = completed.returncode
            except subprocess.TimeoutExpired:
                receipt['timed_out'] = True
                code = 124
        if (runroot / 'result.json').is_file() and (runroot / 'junit.xml').is_file():
            result = json.loads((runroot / 'result.json').read_text(encoding='utf-8'))
            xml = ET.parse(runroot / 'junit.xml').getroot()
            cases = list(xml.iter('testcase'))
            counts = {'tests': len(cases), 'failures': sum(case.find('failure') is not None for case in cases),
                      'errors': sum(case.find('error') is not None for case in cases),
                      'skipped': sum(case.find('skipped') is not None for case in cases)}
            counts['passed'] = counts['tests'] - counts['failures'] - counts['errors'] - counts['skipped']
            groups = list(xml.iter('testsuite'))
            assert all(sum(int(group.attrib[key]) for group in groups) == counts[key] for key in ('tests', 'failures', 'errors', 'skipped'))
            assert counts == result['counts']
            assert receipt['actual_exit'] == result['unit_result_code']
            assert result['command'] == command and result['source_files'] == before
            receipt.update(complete=not receipt['timed_out'], JUnit_counts=counts,
                           JUnit_header_matches_leaves=True, exit_matches_unit_result=True,
                           result=digest(runroot / 'result.json'), JUnit=digest(runroot / 'junit.xml'), tests_log=digest(runroot / 'tests.log'))
        assert inventory(N) == before
        receipt['source_unchanged'] = True
    except BaseException as exc:
        receipt['controller_error_type'] = type(exc).__name__
        receipt['controller_error_ru'] = str(exc)
        code = 2
    finally:
        receipt['duration_seconds'] = time.monotonic() - start
        receipt['control_returncode'] = code
        receipt['stdout'] = digest(runroot / 'stdout.log')
        receipt['stderr'] = digest(runroot / 'stderr.log')
        receipt['resources_after'] = full_resources()
        save(runroot / 'command.json', receipt)
    print(json.dumps({'gate': gate, 'actual_exit': receipt['actual_exit'], 'control_returncode': code,
                      'complete': receipt['complete'], 'JUnit_counts': receipt.get('JUnit_counts'),
                      'source_fingerprint': composite(before), 'controller_error': receipt.get('controller_error_ru')}))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
