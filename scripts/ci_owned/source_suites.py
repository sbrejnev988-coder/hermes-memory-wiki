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
import subprocess
import sys
import time
import unittest

from fixture_prerequisites import SOURCE_SUITES, clean_environment, no_links, suite_case_ids


class CaseResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cases = {}
        self.subtests = []

    def startTest(self, test):
        super().startTest(test)
        self.cases[test.id()] = 'passed'

    def addFailure(self, test, error):
        super().addFailure(test, error)
        self.cases[test.id()] = 'failed'

    def addError(self, test, error):
        super().addError(test, error)
        self.cases[test.id()] = 'error'

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self.cases[test.id()] = 'skipped'

    def addExpectedFailure(self, test, error):
        super().addExpectedFailure(test, error)
        self.cases[test.id()] = 'failed'

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


def case_report(result):
    outcomes = list(result.cases.values())
    return {'schema': 'memory-stack.source-suites/v1', 'boundary': 'SOURCE_NOT_NATIVE',
            'total': result.testsRun, 'passed': outcomes.count('passed'),
            'failed': outcomes.count('failed'), 'errors': outcomes.count('error'),
            'skipped': outcomes.count('skipped'),
            'cases': [{'id': key, 'outcome': value} for key, value in result.cases.items()],
            'subtests': result.subtests}


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
            for key in ('total', 'passed', 'failed', 'errors', 'skipped'):
                row[key] = report[key]
        except (subprocess.TimeoutExpired, OSError, ValueError, KeyError, IndexError, RuntimeError) as error:
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
    from fixture_prerequisites import native_pytest_args
    rows = run_suites(args.source, args.output)
    native_pytest_args(args.source, rows)  # отказ, не зелёный статус при partial/fail
    print(json.dumps({'scope': 'SOURCE', 'suites': rows}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
