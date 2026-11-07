"""D1 SOURCE lock-order regressions; ordinary pytest collection is inert.

Execute complete owning migrate/_journal_operation bodies on explicit synthetic
receivers with real threading.RLock/Event scheduling. Actor/manifest/connection
metadata and journal persistence are seams, not SDK authority. The migration
probe stops at _alias, BEFORE SQL, embeddings, Qdrant or disclosure. The journal
scope uses an in-process RLock, not the native cross-process file lock. This is
SOURCE concurrency proof only, not native migration, recovery or loaded proof.
Use source_suite(current_bytes, journal_excerpt_bytes, baseline_bytes).
"""
from __future__ import annotations

import __future__
import ast
from contextlib import contextmanager
import json
from pathlib import Path
import re
import threading
import traceback
import types
import unittest

__test__ = False
CASE_IDS = (
    'test_SOURCE_journal_first_serializes_migration_without_cycle',
    'test_SOURCE_legacy_countercontrol_exposes_cycle',
    'test_SOURCE_fatal_probe_releases_both_locks_and_keeps_identity',
    'test_SOURCE_busy_journal_owner_refuses_before_journal',
    'test_STATIC_only_acquisition_order_changed',
)


class ProbeStop(BaseException):
    """Stop the source-only probe before its first real I/O boundary."""


class WaitBound(BaseException):
    """A bounded test wait, never a changed production timeout."""


class Schedule:
    def __init__(self, arrange_writer=False):
        self.guard = threading.Lock()
        self.held, self.waiting, self.events = {}, {}, []
        self.cycle = False
        self.writer_has_journal = threading.Event()
        self.migration_at_journal = threading.Event()
        self.arrange_writer = arrange_writer
        self.timeouts = []

    def attempt(self, lock_name):
        role = threading.current_thread().name
        with self.guard:
            self.waiting[role] = lock_name
            if (self.held.get('journal') == 'journal-writer'
                    and self.held.get('provider') == 'migration'
                    and self.waiting.get('journal-writer') == 'provider'
                    and self.waiting.get('migration') == 'journal'):
                self.cycle = True
        return role

    def entered(self, name, role):
        with self.guard:
            self.waiting.pop(role, None)
            self.held[name] = role

    def exited(self, name, role):
        with self.guard:
            assert self.held.pop(name) == role


class BoundedRLock:
    """Real lock with a finite fixture-only timeout to reap the old cycle."""
    def __init__(self, name, schedule):
        self.name, self.schedule = name, schedule
        self.lock = threading.RLock()

    def __enter__(self):
        role = self.schedule.attempt(self.name)
        if not self.lock.acquire(timeout=1.5):
            with self.schedule.guard:
                self.schedule.waiting.pop(role, None)
                self.schedule.timeouts.append((role, self.name))
            raise WaitBound()
        self.schedule.entered(self.name, role)
        return self

    def __exit__(self, *_):
        role = threading.current_thread().name
        self.schedule.exited(self.name, role)
        self.lock.release()

    def free_from_this_thread(self):
        acquired = self.lock.acquire(blocking=False)
        if acquired:
            self.lock.release()
        return acquired


def _definitions(raw, wanted):
    parsed = ast.parse(raw)
    selected = []
    for node in parsed.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in wanted:
            selected.append(node)
        elif isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id in wanted for t in node.targets):
            selected.append(node)
    names = {n.name if isinstance(n, (ast.FunctionDef, ast.ClassDef)) else n.targets[0].id
             for n in selected}
    assert names == set(wanted)
    return ast.Module(body=selected, type_ignores=[])


def _load_migrate(raw, stop, schedule):
    owning = _definitions(raw, ('Refused', '_ERRORS', '_json', '_result', 'migrate'))
    namespace = {'json': json, 're': re}
    code = compile(owning, 'bound-provider-migration-source', 'exec',
                   flags=__future__.annotations.compiler_flag, dont_inherit=True)
    exec(code, namespace)

    def alias_probe(_module):
        schedule.events.append('migration-boundary')
        raise stop

    namespace.update(_actor=lambda receiver, module: ('synthetic-actor', id(receiver)),
                     _alias=alias_probe)
    assert namespace['migrate'].__globals__ is namespace
    return namespace['migrate']


def _load_journal(raw):
    parsed = ast.parse(raw)
    assert len(parsed.body) == 1 and isinstance(parsed.body[0], ast.ClassDef)
    methods = parsed.body[0].body
    assert len(methods) == 1 and methods[0].name == '_journal_operation'
    namespace = {'tool_error': lambda code: {'error': code}}
    exec(compile(ast.Module(body=methods, type_ignores=[]), 'bound-journal-operation-source',
                 'exec', flags=__future__.annotations.compiler_flag, dont_inherit=True), namespace)
    assert namespace['_journal_operation'].__globals__ is namespace
    return namespace['_journal_operation']


def _receiver(schedule, journal_raw):
    provider_lock = BoundedRLock('provider', schedule)
    journal_lock = BoundedRLock('journal', schedule)

    @contextmanager
    def journal_scope():
        role = threading.current_thread().name
        if role == 'migration':
            schedule.migration_at_journal.set()
        with journal_lock:
            if schedule.arrange_writer and role == 'journal-writer':
                schedule.writer_has_journal.set()
                if not schedule.migration_at_journal.wait(3):
                    raise WaitBound()
            yield

    receiver = types.SimpleNamespace(
        _lock=provider_lock, _journal_operation_scope=journal_scope,
        _claim_tx_connection=None, _conn=types.SimpleNamespace(in_transaction=False),
        _journal_operation_locked=lambda op, payload, fn: (fn(), {}))
    receiver._journal_operation = types.MethodType(_load_journal(journal_raw), receiver)
    return receiver, provider_lock, journal_lock


def _module():
    return types.SimpleNamespace(SEMANTIC_ENABLED=True, EMBED_CONTRACT_VALID=True,
        _embedding_manifest=lambda: {'provider': 'synthetic-openrouter'},
        _manifest_hash=lambda value: 'synthetic-manifest',
        _normalized_qdrant_endpoint=lambda: 'synthetic-endpoint-no-transport',
        _qdrant_collection=lambda: 'synthetic_base')


def _race(raw, journal_raw):
    schedule = Schedule(arrange_writer=True)
    receiver, provider_lock, journal_lock = _receiver(schedule, journal_raw)
    probe = ProbeStop()
    migrate = _load_migrate(raw, probe, schedule)
    outcomes = {}

    def effect():
        schedule.events.append('journal-effect')
        return 'synthetic-journal-result'

    def writer():
        try:
            outcomes['writer'] = receiver._journal_operation('synthetic-op', {}, effect)
        except BaseException as exc:
            outcomes['writer'] = exc

    def migration():
        try:
            outcomes['migration'] = migrate(receiver, _module())
        except BaseException as exc:
            outcomes['migration'] = exc

    threads = [threading.Thread(target=writer, name='journal-writer'),
               threading.Thread(target=migration, name='migration')]
    started = []
    try:
        threads[0].start(); started.append(threads[0])
        assert schedule.writer_has_journal.wait(3), 'writer_did_not_reach_journal'
        threads[1].start(); started.append(threads[1])
    finally:
        # Unblock fixture acquisition on every setup/primary path, then reap all
        # actually started threads; no daemon or leaked deadlock is acceptable.
        if len(started) != 2:
            schedule.migration_at_journal.set()
        for thread in started:
            thread.join(timeout=5)
        assert all(not thread.is_alive() for thread in started), 'thread_not_reaped'
    assert provider_lock.free_from_this_thread() and journal_lock.free_from_this_thread()
    assert schedule.held == {} and schedule.waiting == {}
    return schedule, outcomes, probe


def source_suite(current_raw, journal_raw, baseline_raw):
    """Explicit SOURCE factory; callers supply separately bound exact bytes."""
    class Cases(unittest.TestCase):
        def test_SOURCE_journal_first_serializes_migration_without_cycle(self):
            schedule, outcomes, probe = _race(current_raw, journal_raw)
            self.assertEqual(schedule.timeouts, [])
            self.assertFalse(schedule.cycle)
            self.assertEqual(outcomes['writer'], ('synthetic-journal-result', {}))
            self.assertIs(outcomes['migration'], probe)
            self.assertEqual(schedule.events, ['journal-effect', 'migration-boundary'])

        def test_SOURCE_legacy_countercontrol_exposes_cycle(self):
            schedule, outcomes, probe = _race(baseline_raw, journal_raw)
            self.assertTrue(schedule.cycle)
            self.assertTrue(schedule.timeouts)
            self.assertTrue(any(isinstance(value, WaitBound) for value in outcomes.values()))
            self.assertEqual(set(outcomes), {'writer', 'migration'})

        def test_SOURCE_fatal_probe_releases_both_locks_and_keeps_identity(self):
            schedule = Schedule()
            receiver, provider_lock, journal_lock = _receiver(schedule, journal_raw)
            stop = ProbeStop()
            migrate = _load_migrate(current_raw, stop, schedule)
            with self.assertRaises(ProbeStop) as caught:
                migrate(receiver, _module())
            self.assertIs(caught.exception, stop)
            self.assertEqual(schedule.events, ['migration-boundary'])
            self.assertEqual(schedule.held, {})
            self.assertEqual(schedule.waiting, {})
            self.assertTrue(provider_lock.free_from_this_thread())
            self.assertTrue(journal_lock.free_from_this_thread())

        def test_SOURCE_busy_journal_owner_refuses_before_journal(self):
            schedule = Schedule(arrange_writer=True)
            receiver, provider_lock, journal_lock = _receiver(schedule, journal_raw)
            receiver._claim_tx_connection = object()
            calls = []
            result = receiver._journal_operation('synthetic-op', {}, lambda: calls.append(True))
            self.assertEqual(result, ({'error': 'journal_mutation_requires_idle_owner'}, {}))
            self.assertEqual(calls, [])
            self.assertFalse(schedule.writer_has_journal.is_set())
            self.assertEqual(schedule.held, {})
            self.assertEqual(schedule.waiting, {})
            self.assertTrue(provider_lock.free_from_this_thread())
            self.assertTrue(journal_lock.free_from_this_thread())

        def test_STATIC_only_acquisition_order_changed(self):
            old = b'with provider._lock, provider._journal_operation_scope():'
            new = b'with provider._journal_operation_scope(), provider._lock:'
            self.assertEqual(baseline_raw.count(old), 1)
            self.assertEqual(current_raw, baseline_raw.replace(old, new, 1))

    return unittest.TestSuite(Cases(name) for name in CASE_IDS)


def _main():
    paths = DEVTOOLS_INPUTS
    suite = source_suite(
        devtools_read_bound(Path(paths['provider_migration.py'])),
        devtools_read_bound(Path(paths['provider_journal_operation.py'])),
        devtools_read_bound(Path(paths['provider_migration_before_d1.py'])))
    records, details = [], []

    class Result(unittest.TestResult):
        def startTest(self, test):
            super().startTest(test)
            devtools_case_started(test._testMethodName)

        def addSuccess(self, test):
            super().addSuccess(test)
            records.append({'id': test._testMethodName, 'outcome': 'passed'})

        def addFailure(self, test, err):
            super().addFailure(test, err)
            self.record(test, err, 'failed')

        def addError(self, test, err):
            super().addError(test, err)
            self.record(test, err, 'error')

        def record(self, test, err, outcome):
            records.append({'id': test._testMethodName, 'outcome': outcome})
            details.append({'id': test._testMethodName, 'type': err[0].__name__,
                'frames': [{'file': frame.filename, 'function': frame.name, 'line': frame.lineno}
                           for frame in traceback.extract_tb(err[2])[-8:]]})

    result = Result()
    suite.run(result)
    counts = {key: sum(row['outcome'] == outcome for row in records)
              for key, outcome in [('passed', 'passed'), ('failed', 'failed'),
                                   ('errors', 'error'), ('skipped', 'skipped')]}
    print(json.dumps({'schema': 'memory-stack.cases/v1', 'cases': records,
        'total': len(records), **counts, 'error_details': details,
        'scope': 'SOURCE_concurrency4_STATIC1_before_first_IO',
        'native_SDK_SQL_Qdrant_embeddings': 'NOT_RUN'}, separators=(',', ':')), flush=True)
    raise SystemExit(0 if result.wasSuccessful() and len(records) == len(CASE_IDS) else 1)


if __name__ == '__main__':
    _main()
