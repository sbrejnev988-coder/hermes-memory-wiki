"""SOURCE regressions for the migration/rebuild owner boundary.

Only exact selected bodies are compiled: no plugin, SDK, pytest or host boot.
The receiver and file-backed SQLite are explicitly generic fixtures. These
checks do NOT execute _migrate, journal replay/swap, privacy/ACL or native SPI.
The shipped companion pytest file retains those separate, NOT_RUN controls.
"""
from __future__ import annotations

import ast
import copy
from contextlib import contextmanager
from contextvars import ContextVar
import os
from pathlib import Path
import sqlite3
import sys
import threading
from types import ModuleType
import unittest


ROOT = Path(__file__).resolve().parents[1]
METHODS = (
    '_runtime_identity', '_connect', '_cols', '_require_claim_writer',
    '_quarantine_claim_connection', '_rollback_claim_transaction',
    '_release_connection_for_retry', '_shutdown_lifecycle',
    '_migration_connection', '_close_journal_rebuild_connection',
)


def source_contract(provider_raw=None, graph_raw=None):
    provider_raw = provider_raw if provider_raw is not None else (ROOT / '__init__.py').read_bytes()
    graph_raw = graph_raw if graph_raw is not None else (ROOT / 'code_knowledge_graph.py').read_bytes()
    pt, gt = ast.parse(provider_raw), ast.parse(graph_raw)
    cls = next(n for n in pt.body if isinstance(n, ast.ClassDef) and n.name == 'MemoryWikiProvider')
    methods = {n.name: n for n in cls.body if isinstance(n, ast.FunctionDef)}
    graph_names = {'_GraphCommitConnection', '_GraphWriterConnection',
                   '_graph_writer_identity', '_owns_graph_writer'}
    graph_nodes = [n for n in gt.body if isinstance(n, (ast.ClassDef, ast.FunctionDef)) and n.name in graph_names]
    assert len(graph_nodes) == len(graph_names)
    ns = dict(sqlite3=sqlite3, threading=threading, Path=Path, sys=sys, ModuleType=ModuleType,
              contextmanager=contextmanager, __name__='source_generic_sqlite',
              __file__=str(ROOT / '__init__.py'))
    exec(compile(ast.Module(body=copy.deepcopy(graph_nodes), type_ignores=[]),
                 'declared-graph-source.py', 'exec', flags=__import__('__future__').annotations.compiler_flag), ns)
    # The real source predicate rejects this generic, non-factory connection by
    # exact type. No authorizer, owner validator or SQL admission is replaced.
    ns['_owns_private_graph_writer'] = ns['_owns_graph_writer']
    receiver = ast.ClassDef(name='GenericSourceReceiver', bases=[], keywords=[],
                           body=[copy.deepcopy(methods[name]) for name in METHODS], decorator_list=[])
    exec(compile(ast.fix_missing_locations(ast.Module(body=[receiver], type_ignores=[])),
                 'declared-provider-source.py', 'exec', flags=__import__('__future__').annotations.compiler_flag), ns)
    return ns, methods


def error_tail(ns, methods):
    """Execute the unchanged outer handler/finally, not a synthetic recovery."""
    body = methods['_rebuild_from_journal_locked']
    choices = [n for n in body.body if isinstance(n, ast.Try)
               and any(isinstance(h.type, ast.Name) and h.type.id == 'BaseException'
                       and h.name == 'primary' for h in n.handlers)]
    assert len(choices) == 1
    tail = copy.deepcopy(choices[0])
    tail.body = ast.parse('raise incoming').body
    tail.orelse = []
    setup = ast.parse('''def invoke(self, incoming, original_db, _restore_pre_swap_bundle):
    pre_swap_root_staged = True
    previous_recovery_active = False
    background_worker_was_active = False
    rebuild_lock_held = False
''').body[0]
    setup.body.append(tail)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[setup], type_ignores=[])),
                 'declared-rebuild-error-tail.py', 'exec'), ns)
    return ns['invoke']


class FixtureConnection(sqlite3.Connection):
    """Only close-fault injection is synthetic; SQLite TX/authorizer are real."""
    close_error = None

    def close(self):
        if self.close_error is not None:
            raise self.close_error
        return super().close()


class TestJournalRebuildOwnerSource(unittest.TestCase):
    @classmethod
    def bind_sources(cls, provider_raw, graph_raw, scratch):
        cls._source_raw = provider_raw
        cls._graph_raw = graph_raw
        cls._scratch = Path(scratch)

    def setUp(self):
        raw = getattr(self, '_source_raw', None)
        graph = getattr(self, '_graph_raw', None)
        self.ns, self.methods = source_contract(raw, graph)
        # In SOURCE the permanent bootstrap provides this owned scratch root.
        # A standalone unittest invocation must also explicitly supply TMPDIR.
        scratch = getattr(self, '_scratch', None) or Path(os.environ['TMPDIR'])
        self.home = scratch / self._testMethodName
        self.home.mkdir(exist_ok=False)
        self.db = self.home / 'generic.sqlite3'
        self.c = sqlite3.connect(str(self.db), factory=FixtureConnection, cached_statements=0)
        self._closed_by_test = False
        self.c.execute('CREATE TABLE sample(value TEXT NOT NULL)')
        self.p = self.ns['GenericSourceReceiver']()
        p = self.p
        p.home = p.root = p.spool_dir = p.recovery_dir = self.home
        p.db_path = self.db
        p._conn = p._owned_conn = self.c
        p._lock = threading.RLock()
        p._lifecycle_lock = threading.Lock()
        p._lifecycle_state = 'ready'
        p._degraded = False
        p._background_worker = None
        p._claim_tx_connection = p._claim_tx_thread = None
        p._claim_tx_document_stage = p._claim_tx_graph_stage = p._claim_tx_event_job_stage = None
        p._transaction_quarantine = p._transaction_primary = None
        p._transaction_cleanup_notes = ()
        p._graph_reader_connections = {}
        p._prefetch_admission = threading.Lock()
        p._prefetch_attempt = None
        self.ns['_QDRANT_PROFILE_SCOPE'] = ContextVar('source_profile', default={})
        self.ns['_REQUEST_HOME'] = ContextVar('source_request_home', default=str(self.home))
        self.ns['_IMPORT_HERMES_HOME'] = self.home
        self.ns['_LOADED_CODE_IDENTITY'] = 'source-extracted-not-native'

    def tearDown(self):
        # Fixture-owned closure after the asserted retention snapshot is not
        # production recovery, and never resets a quarantine/owner field.
        if not self._closed_by_test:
            sqlite3.Connection.set_authorizer(self.c, None)
            sqlite3.Connection.close(self.c)

    def assertIdle(self):
        self.assertIs(self.p._conn, self.c)
        self.assertIs(self.p._owned_conn, self.c)
        self.assertFalse(self.c.in_transaction)
        self.assertIsNone(self.p._claim_tx_connection)
        self.assertIsNone(self.p._claim_tx_thread)
        self.assertIsNone(self.p._transaction_quarantine)
        self.assertEqual(self.p._lifecycle_state, 'ready')

    def unknown(self, primary):
        def deny_rollback(action, first, second, db, trigger):
            return sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_TRANSACTION and first == 'ROLLBACK' else sqlite3.SQLITE_OK
        with self.assertRaises(type(primary)) as caught:
            with self.p._migration_connection() as c:
                c.execute("INSERT INTO sample VALUES('uncommitted')")
                c.set_authorizer(deny_rollback)
                raise primary
        self.assertIs(caught.exception, primary)
        self.assertIs(self.p._transaction_primary, primary)
        self.assertIs(self.p._transaction_quarantine, self.c)
        self.assertIs(self.p._claim_tx_connection, self.c)
        self.assertEqual(self.p._claim_tx_thread, threading.get_ident())
        self.assertTrue(self.c.in_transaction)

    def test_generic_sqlite_migration_batches_keep_exact_registered_owner(self):
        with self.p._migration_connection() as c:
            self.assertIs(c, self.c)
            for i in range(2):
                c.executescript('CREATE TABLE IF NOT EXISTS other(id INTEGER);')
                self.assertFalse(c.in_transaction)
                c.execute('INSERT INTO sample VALUES(?)', (str(i),))
                self.assertTrue(c.in_transaction)
                self.assertIs(self.p._claim_tx_connection, c)
                self.assertEqual(self.p._claim_tx_thread, threading.get_ident())
                self.assertEqual(self.p._cols('sample'), {'value'})
        self.assertIdle()
        other = sqlite3.connect(str(self.db))
        try:
            self.assertEqual(other.execute('SELECT value FROM sample ORDER BY value').fetchall(), [('0',), ('1',)])
        finally:
            other.close()

    def test_generic_sqlite_known_rollback_keeps_primary_and_retires_owner(self):
        primary = ValueError('source-primary')
        with self.assertRaises(ValueError) as caught:
            with self.p._migration_connection() as c:
                c.execute("INSERT INTO sample VALUES('rollback')")
                self.p._cols('sample')
                raise primary
        self.assertIs(caught.exception, primary)
        self.assertIdle()
        self.assertEqual(self.c.execute('SELECT value FROM sample').fetchall(), [])
        self.assertIs(self.p._connect(), self.c)

    def test_generic_sqlite_real_rollback_denial_retains_unknown(self):
        primary = ValueError('rollback-denied')
        self.unknown(primary)
        self.assertIn('rollback_DatabaseError', self.p._transaction_cleanup_notes)
        for action in (self.p._connect, self.p._shutdown_lifecycle, self.p._close_journal_rebuild_connection):
            with self.assertRaises(RuntimeError):
                action()
        self.assertFalse(self.p._release_connection_for_retry(primary))
        self.assertIs(self.p._conn, self.c)
        self.assertIs(self.p._owned_conn, self.c)
        self.assertEqual(self.p.db_path, self.db)

    def test_extracted_rebuild_unknown_tail_preserves_primary_and_path(self):
        primary = ValueError('rebuild-primary')
        self.unknown(primary)
        restored = []
        invoke = error_tail(self.ns, self.methods)
        with self.assertRaises(ValueError) as caught:
            invoke(self.p, primary, self.home / 'must-not-rebind.sqlite3', lambda: restored.append(True))
        self.assertIs(caught.exception, primary)
        self.assertEqual(restored, [])
        self.assertEqual(self.p.db_path, self.db)
        self.assertIs(self.p._transaction_primary, primary)
        self.assertIs(self.p._conn, self.c)
        self.assertIs(self.p._owned_conn, self.c)
        self.assertIs(self.p._claim_tx_connection, self.c)
        self.assertEqual(self.p._lifecycle_state, 'quarantined')

    def test_extracted_rebuild_close_failure_preserves_cancellation(self):
        primary = KeyboardInterrupt('source-cancel')
        cleanup = OSError('fixture-close-refusal')
        self.c.close_error = cleanup
        restored = []
        invoke = error_tail(self.ns, self.methods)
        with self.assertRaises(KeyboardInterrupt) as caught:
            invoke(self.p, primary, self.home / 'must-not-rebind.sqlite3', lambda: restored.append(True))
        self.assertIs(caught.exception, primary)
        self.assertIs(self.p._transaction_primary, primary)
        self.assertIs(self.p._transaction_quarantine, self.c)
        self.assertIs(self.p._conn, self.c)
        self.assertIs(self.p._owned_conn, self.c)
        self.assertEqual(self.p.db_path, self.db)
        self.assertEqual(restored, [])
        self.assertEqual(self.c.execute('SELECT 1').fetchone(), (1,))
        self.assertTrue(any('outcome=UNKNOWN' in n for n in primary.__notes__))

    def test_generic_close_returns_before_detaching_both_owned_handles(self):
        self.p._close_journal_rebuild_connection()
        self._closed_by_test = True
        self.assertIsNone(self.p._conn)
        self.assertIsNone(self.p._owned_conn)
        with self.assertRaises(sqlite3.ProgrammingError):
            self.c.execute('SELECT 1')

    def test_generic_unregistered_pending_transaction_still_quarantines(self):
        self.c.execute('BEGIN IMMEDIATE')
        with self.assertRaisesRegex(RuntimeError, '^provider_transaction_owner_pending$'):
            with self.p._migration_connection():
                self.fail('unregistered transaction admitted')
        self.assertIs(self.p._transaction_quarantine, self.c)
        self.assertIs(self.p._conn, self.c)
        self.assertIsNone(self.p._claim_tx_connection)
        self.assertEqual(self.p._lifecycle_state, 'quarantined')

    def test_generic_foreign_thread_record_does_not_grant_migration(self):
        self.p._claim_tx_connection = self.c
        self.p._claim_tx_thread = -1
        with self.assertRaisesRegex(RuntimeError, '^migration_requires_idle_owner$'):
            with self.p._migration_connection():
                self.fail('foreign record admitted')
        self.assertIs(self.p._claim_tx_connection, self.c)
        self.assertEqual(self.p._claim_tx_thread, -1)
        self.assertFalse(self.c.in_transaction)

    def test_generic_registered_active_stage_is_not_joined_or_committed(self):
        self.c.execute('BEGIN IMMEDIATE')
        self.c.execute("INSERT INTO sample VALUES('external')")
        self.p._claim_tx_connection = self.c
        self.p._claim_tx_thread = threading.get_ident()
        with self.assertRaisesRegex(RuntimeError, '^migration_requires_idle_owner$'):
            with self.p._migration_connection():
                self.fail('caller transaction adopted')
        self.assertTrue(self.c.in_transaction)
        self.assertIs(self.p._claim_tx_connection, self.c)
        self.assertEqual(self.c.execute('SELECT value FROM sample').fetchall(), [('external',)])

    def test_generic_foreign_owned_handle_is_not_a_writer(self):
        self.p._owned_conn = object()  # Negative only; not authority or a connection.
        before = self.p._owned_conn
        with self.assertRaisesRegex(RuntimeError, '^claim_mutation_transaction_not_owned$'):
            with self.p._migration_connection():
                self.fail('foreign owned handle admitted')
        self.assertIs(self.p._owned_conn, before)
        self.assertIs(self.p._conn, self.c)
        self.assertIsNone(self.p._claim_tx_connection)

    def test_static_migration_uses_owned_scope_without_nested_commit(self):
        migrate = self.methods['_migrate']
        scope = migrate.body[0]
        self.assertIsInstance(scope, ast.With)
        self.assertEqual(ast.unparse(scope.items[0].context_expr), 'self._migration_connection()')
        self.assertEqual(ast.unparse(scope.items[0].optional_vars), 'c')
        self.assertFalse(any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                             and n.func.attr in {'commit', 'rollback'} for n in ast.walk(migrate)))
        self.assertTrue(any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                            and n.func.attr == 'executescript' for n in ast.walk(migrate)))

    def test_static_rebuild_lifecycle_and_cleanup_order_are_fail_closed(self):
        wrapper = self.methods['_rebuild_from_journal']
        text = ast.unparse(wrapper)
        self.assertIn('self._lifecycle_lock.acquire(blocking=False)', text)
        self.assertIn('self._lifecycle_lock.release()', text)
        rebuild = self.methods['_rebuild_from_journal_locked']
        outer = next(n for n in rebuild.body if isinstance(n, ast.Try)
                     and any(h.name == 'primary' for h in n.handlers))
        body_text = ast.unparse(outer)
        self.assertLess(body_text.index('self._background_worker.stop()'), body_text.index('self._lock.acquire()'))
        handler = next(h for h in outer.handlers if h.name == 'primary')
        self.assertEqual(ast.unparse(handler.type), 'BaseException')
        cleanup = handler.body[0]
        self.assertIsInstance(cleanup, ast.Try)
        self.assertEqual(ast.unparse(cleanup.body[0]), 'self._close_journal_rebuild_connection(primary)')
        cleanup_text = ast.unparse(cleanup)
        self.assertLess(cleanup_text.index('self._close_journal_rebuild_connection(primary)'),
                        cleanup_text.index('self.db_path = original_db'))
        self.assertLess(cleanup_text.index('_restore_pre_swap_bundle()'), cleanup_text.index('self._connect()'))
        self.assertIsInstance(handler.body[-1], ast.Raise)
        self.assertIsNone(handler.body[-1].exc)
        self.assertNotIn("self._lifecycle_state = 'ready'", body_text)
        self.assertNotIn('self._transaction_quarantine = None', body_text)
        self.assertIn('self._lock.release()', ast.unparse(outer.finalbody[0]))


if __name__ == '__main__':
    unittest.main()
