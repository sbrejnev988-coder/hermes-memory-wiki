"""Изолированный SOURCE roster; существующий unittest runner, не native gate.

Нужен отдельный процесс: G4 проверяет отсутствие SDK и ставит необратимые audit
hooks. Нельзя импортировать его в SDK pytest и объявить ту же границу сохранённой.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import time
import unittest

from fixture_prerequisites import SOURCE_SUITES, clean_environment, native_pytest_args, no_links, suite_case_ids

# Separate, additive diagnostic namespace; source-suites/v1 qualification fields
# and the strict native_pytest_args consumer are unchanged. Foreign class names,
# exception messages and subtest.id() are never diagnostic console inputs.
DIAGNOSTIC_SCHEMA = 'memory-stack.source-failure-diagnostic/v1'
CASE_DIAGNOSTIC_SCHEMA = 'memory-stack.source-case-errors/v1'
PUBLIC_DIAGNOSTIC_INPUTS = (
    '__init__.py',
    'tests/fixtures/g4_original_boundary_gold.txt',
    'tests/fixtures/g4_metadata_scope.txt',
)
PUBLIC_INPUT_CAP = 2_000_000
DIAGNOSTIC_CAP = 16_000
DIAGNOSTIC_UNKNOWN = 'SOURCE_FAILURE_DIAGNOSTIC {"schema":"memory-stack.source-failure-diagnostic/v1","boundary":"SOURCE_NOT_NATIVE","status":"UNKNOWN"}\n'
ERROR_TYPES = (
    (AssertionError, 'AssertionError'), (RuntimeError, 'RuntimeError'),
    (TypeError, 'TypeError'), (ValueError, 'ValueError'), (KeyError, 'KeyError'),
    (IndexError, 'IndexError'), (OSError, 'OSError'),
    (PermissionError, 'PermissionError'), (FileNotFoundError, 'FileNotFoundError'),
    (ImportError, 'ImportError'), (ModuleNotFoundError, 'ModuleNotFoundError'),
    (TimeoutError, 'TimeoutError'), (RecursionError, 'RecursionError'),
    (subprocess.TimeoutExpired, 'TimeoutExpired'),
    (KeyboardInterrupt, 'KeyboardInterrupt'), (SystemExit, 'SystemExit'),
)


def safe_error_type(error):
    """Only exact builtin identities; no foreign metaclass attributes/str/repr."""
    if type(error) is tuple and len(error) == 3:
        for cls, label in ERROR_TYPES:
            if error[0] is cls:
                return label
    return 'UNKNOWN'


def known_error_name(value):
    if type(value) is str and len(value) <= 32 and value in tuple(label for _, label in ERROR_TYPES):
        return value
    return 'UNKNOWN'


def public_input_metadata(relative, raw):
    """Pure byte-layout projection, only for the three fixed public inputs."""
    if type(relative) is not str or relative not in PUBLIC_DIAGNOSTIC_INPUTS:
        raise ValueError('nonpublic_source_diagnostic_refused')
    row = {'input': relative, 'status': 'UNKNOWN'}
    if type(raw) is bytes and len(raw) <= PUBLIC_INPUT_CAP:
        crlf = raw.count(b'\r\n')
        row.update(status='known', B=len(raw), sha256=hashlib.sha256(raw).hexdigest(),
                   crlf=crlf, lf_only=raw.count(b'\n') - crlf, cr_only=raw.count(b'\r') - crlf)
    return row


def source_failure_text(rows, rosters, public_inputs):
    """Bounded projection, not a qualifier. Rosters come from own source AST.

    Never serialize a child object, raw error text, arbitrary path or subtest ID.
    Missing/malformed case evidence stays UNKNOWN, even with healthy counts.
    """
    suites = []
    for index, (relative, (owner, count)) in enumerate(SOURCE_SUITES.items()):
        ids = rosters.get(relative) if type(rosters) is dict else None
        if (type(ids) is not list or len(ids) != count
                or any(type(value) is not str or len(value) > 192
                       or not re.fullmatch(r'__main__\.' + owner + r'\.test[A-Za-z0-9_]*', value) for value in ids)
                or len(set(ids)) != count):
            raise ValueError('diagnostic_source_roster_unknown')
        row = rows.get(relative) if type(rows) is dict else None
        row = row if type(row) is dict else {}
        cases = row.get('cases')
        valid = (type(cases) is list and len(cases) == count
                 and all(type(case) is dict and type(case.get('id')) is str
                         and case['id'] == identity and type(case.get('outcome')) is str
                         and case['outcome'] in ('passed', 'failed', 'error', 'skipped')
                         for case, identity in zip(cases, ids)))
        outcomes = [case['outcome'] for case in cases] if valid else ['UNKNOWN'] * count
        details = row.get('diagnostics')
        types = details.get('case_error_types') if (type(details) is dict
                and type(details.get('schema')) is str and details['schema'] == CASE_DIAGNOSTIC_SCHEMA) else None
        if (type(types) is not dict or len(types) > count
                or any(type(key) is not str or key not in ids for key in types)):
            types = {}
        exit_code = row.get('exit_code')
        if type(exit_code) is not int or not -(2 ** 31) <= exit_code < 2 ** 31:
            exit_code = 'UNKNOWN'
        counts = (('passed', 'passed'), ('failed', 'failed'), ('errors', 'error'), ('skipped', 'skipped'))
        consistent = (valid and type(row.get('total')) is int and row['total'] == count
                      and all(type(row.get(key)) is int and row[key] == outcomes.count(outcome)
                              for key, outcome in counts))
        outcome = 'UNKNOWN'
        if consistent and type(exit_code) is int:
            if 'error' in outcomes:
                outcome = 'error'
            elif 'failed' in outcomes:
                outcome = 'failed'
            elif 'skipped' in outcomes:
                outcome = 'skipped'
            elif exit_code == 0:
                outcome = 'passed'
        suites.append({'suite': relative, 'outcome': outcome, 'exit_code': exit_code,
                       'error_type': known_error_name(row.get('error_type')),
                       'captures': ['suite-' + str(index) + '/stdout.log', 'suite-' + str(index) + '/stderr.log'],
                       'cases': [{'id': identity, 'outcome': value,
                                  'error_type': known_error_name(types.get(identity))}
                                 for identity, value in zip(ids, outcomes) if value != 'passed']})
    inputs = public_inputs if type(public_inputs) is dict else {}
    report = {'schema': DIAGNOSTIC_SCHEMA, 'boundary': 'SOURCE_NOT_NATIVE',
              'result': 'source-results.json', 'suites': suites,
              'public_inputs': [public_input_metadata(relative, inputs.get(relative))
                                for relative in PUBLIC_DIAGNOSTIC_INPUTS]}
    text = 'SOURCE_FAILURE_DIAGNOSTIC ' + json.dumps(report, ensure_ascii=True, separators=(',', ':')) + '\n'
    if len(text.encode('ascii')) > DIAGNOSTIC_CAP:
        raise ValueError('source_diagnostic_too_large')
    return text


def write_source_failure(rows, rosters, public_inputs, stream):
    """Secondary reporting cannot replace a qualifier primary, even on cancel."""
    try:
        stream.write(source_failure_text(rows, rosters, public_inputs))
        stream.flush()
    except BaseException:
        try:
            stream.write(DIAGNOSTIC_UNKNOWN)
            stream.flush()
        except BaseException:
            pass


def emit_source_failure(source, rows):
    """Read only fixed own public source inputs; never read child logs or homes."""
    try:
        source = no_links(source)
        rosters = {relative: suite_case_ids(source, relative) for relative in SOURCE_SUITES}
        inputs = {}
        for relative in PUBLIC_DIAGNOSTIC_INPUTS:
            inputs[relative] = None
            try:
                path = no_links(source / relative)
                info = path.lstat()
                if stat.S_ISREG(info.st_mode) and info.st_size <= PUBLIC_INPUT_CAP:
                    with path.open('rb') as stream:
                        raw = stream.read(PUBLIC_INPUT_CAP + 1)
                    if len(raw) <= PUBLIC_INPUT_CAP:
                        inputs[relative] = raw
            except (OSError, ValueError):
                pass
        write_source_failure(rows, rosters, inputs, sys.stderr)
    except BaseException:
        # Protect the fallback recorder as well as the formatter/readers.
        try:
            sys.stderr.write(DIAGNOSTIC_UNKNOWN)
            sys.stderr.flush()
        except BaseException:
            pass


def qualified_native_args(source, rows):
    """The original strict qualifier owns admission; diagnostics grant nothing."""
    try:
        return native_pytest_args(source, rows)
    except BaseException:
        try:
            emit_source_failure(source, rows)
        except BaseException:
            pass
        raise


class CaseResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cases = {}
        self.subtests = []
        self.case_error_types = {}

    def startTest(self, test):
        super().startTest(test)
        self.cases[test.id()] = 'passed'

    def addFailure(self, test, error):
        super().addFailure(test, error)
        self.cases[test.id()] = 'failed'
        self.case_error_types[test.id()] = safe_error_type(error)

    def addError(self, test, error):
        super().addError(test, error)
        self.cases[test.id()] = 'error'
        self.case_error_types[test.id()] = safe_error_type(error)

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self.cases[test.id()] = 'skipped'

    def addExpectedFailure(self, test, error):
        super().addExpectedFailure(test, error)
        self.cases[test.id()] = 'failed'
        self.case_error_types[test.id()] = safe_error_type(error)

    def addUnexpectedSuccess(self, test):
        super().addUnexpectedSuccess(test)
        self.cases[test.id()] = 'failed'

    def addSubTest(self, test, subtest, error):
        super().addSubTest(test, subtest, error)
        outcome = 'passed' if error is None else ('failed' if issubclass(error[0], test.failureException) else 'error')
        self.subtests.append({'id': subtest.id(), 'outcome': outcome})
        if error is not None:
            if self.cases[test.id()] != 'error':
                self.cases[test.id()] = outcome
                self.case_error_types[test.id()] = safe_error_type(error)


def case_report(result):
    outcomes = list(result.cases.values())
    return {'schema': 'memory-stack.source-suites/v1', 'boundary': 'SOURCE_NOT_NATIVE',
            'total': result.testsRun, 'passed': outcomes.count('passed'),
            'failed': outcomes.count('failed'), 'errors': outcomes.count('error'),
            'skipped': outcomes.count('skipped'),
            'cases': [{'id': key, 'outcome': value} for key, value in result.cases.items()],
            'subtests': result.subtests,
            'diagnostics': {'schema': CASE_DIAGNOSTIC_SCHEMA,
                            'case_error_types': result.case_error_types}}


def run_unittest(test_class, *, expected):
    """Полный TestCase, включая subtest failures; никакого skip→PASS."""
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(test_class)
    result = unittest.TextTestRunner(verbosity=2, resultclass=CaseResult).run(suite)
    report = case_report(result)
    print(json.dumps(report, ensure_ascii=True), flush=True)
    return 0 if (result.wasSuccessful() and result.testsRun == expected
                 and report['passed'] == expected) else 1


def run_suites(source, root):
    source, root = Path(source).resolve(), no_links(root)
    root.mkdir(parents=True, exist_ok=False)
    rows = {}
    for index, (relative, (_, expected)) in enumerate(SOURCE_SUITES.items()):
        fixture = root / ('suite-' + str(index))
        fixture.mkdir()
        env = clean_environment(fixture, os.environ)
        entry = source / relative
        digest = hashlib.sha256(entry.read_bytes()).hexdigest()
        command = [sys.executable, '-I', '-B', '-S', str(entry)]
        started = time.monotonic()
        row = {'sha256': digest, 'exit_code': None, 'total': None, 'passed': None,
               'failed': None, 'errors': None, 'skipped': None}
        # Immutable logs exist even if a child fails before its case JSON.
        try:
            with (fixture / 'stdout.log').open('xb') as out, (fixture / 'stderr.log').open('xb') as err:
                child = subprocess.run(command, cwd=fixture, env=env, stdout=out, stderr=err,
                                       timeout=60, check=False, shell=False)
            row['exit_code'] = child.returncode
            raw = (fixture / 'stdout.log').read_bytes()
            if len(raw) > 96000:
                raise RuntimeError('source_report_too_large')
            reports = [json.loads(line) for line in raw.splitlines() if line.startswith(b'{')]
            report = reports[-1]
            if report['schema'] != 'memory-stack.source-suites/v1' or report['total'] != expected:
                raise RuntimeError('source_report_contract')
            ids = [case['id'] for case in report['cases']]
            if ids != suite_case_ids(source, relative):
                raise RuntimeError('source_case_identity_mismatch')
            outcomes = [case['outcome'] for case in report['cases']]
            if any(value not in ('passed', 'failed', 'error', 'skipped') for value in outcomes):
                raise RuntimeError('source_case_outcome_invalid')
            for key, outcome in [('passed', 'passed'), ('failed', 'failed'), ('errors', 'error'), ('skipped', 'skipped')]:
                if type(report[key]) is not int or report[key] != outcomes.count(outcome):
                    raise RuntimeError('source_case_counts_mismatch')
            row['case_ids'] = ids
            row['subtests'] = report['subtests']
            # Explicit additive diagnostics only; never consumed for admission.
            row['cases'] = report['cases']
            row['diagnostics'] = report.get('diagnostics')
            for key in ('total', 'passed', 'failed', 'errors', 'skipped'):
                row[key] = report[key]
        except (subprocess.TimeoutExpired, OSError, ValueError, TypeError, KeyError, IndexError, RuntimeError) as error:
            row['error_type'] = type(error).__name__
        row['elapsed_seconds'] = time.monotonic() - started
        rows[relative] = row
    (root / 'source-results.json').write_text(json.dumps(rows, indent=2) + '\n', encoding='utf-8')
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    rows = run_suites(args.source, args.output)
    qualified_native_args(args.source, rows)  # тот же отказ, плюс безопасная диагностика
    print(json.dumps({'scope': 'SOURCE', 'suites': rows}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
