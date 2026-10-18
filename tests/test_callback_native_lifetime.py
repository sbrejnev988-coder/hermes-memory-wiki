"""JRO-C01/C02: real factory/MRO callback delivery before owning cleanup.

No authorizer, factory, ACL, SDK or provider is replaced. The shipped genuine
fixture owns its synthetic home and in-process plain-text parser. Raw sqlite3
base descriptors intentionally have stdlib exception semantics, not Python
primary delivery; they must not leave a cause for an unrelated wrapped call.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sqlite3
import sys
import threading

import pytest

_SPEC = importlib.util.spec_from_file_location('callback_document_native_peer',
    Path(__file__).with_name('test_document_native_commit_fence.py'))
peer = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = peer
_SPEC.loader.exec_module(peer)
fx = peer.fx
derived_case = fx.derived_case


class Cancel(BaseException):
    pass


class PrivateFixture(fx.Fixture):
    """Only test-owned safety closure after the recorded UNKNOWN snapshot."""
    writer = None

    def _finish(self, primary):
        w = self.writer
        if w is None:
            return super()._finish(primary)
        if self.p._transaction_quarantine is not w:
            self.code._close_graph_writer_connection(w, True)
            return super()._finish(primary)
        p = self.p
        owner = (p._conn, p._owned_conn, p._claim_tx_connection,
                 p._claim_tx_thread, p._claim_tx_document_stage,
                 p._transaction_quarantine, p._transaction_primary)
        # Never reset quarantine/owner, never use this as recovery evidence.
        sqlite3.Connection.set_authorizer(w, None)
        sqlite3.Connection.rollback(w)
        sqlite3.Connection.close(w)
        sqlite3.Connection.close(self.conn)
        assert all(a is b for a, b in zip(owner, (
            p._conn, p._owned_conn, p._claim_tx_connection, p._claim_tx_thread,
            p._claim_tx_document_stage, p._transaction_quarantine, p._transaction_primary)))
        assert p._graph_writer_connections[w] is w._graph_lifetime
        self._emit(dict(event='fixture_private_safety_close_NOT_production_recovery',
                        original_owner_primary_admissions_still_retained=True))
        self._diag.close()
        self._scopes.close()
        self._native.reset_hermes_home_override(self._native_token)
        sys.modules['__main__']._memory_wiki_instance = self._main_before
        for loaded in tuple(sys.modules):
            if loaded == self._namespace or loaded.startswith(self._namespace + '.'):
                sys.modules.pop(loaded, None)
        self._mp.undo()


def rows_table(c):
    with c.p._claim_transaction(c.conn):
        c.conn.execute('CREATE TABLE jro_callback_rows(value TEXT NOT NULL)')
        c.conn.execute("INSERT INTO jro_callback_rows VALUES('before')")


def issued(c):
    w, owned = c.code._open_graph_writer_connection(c.p)
    assert owned and type(w) is c.code._GraphWriterConnection
    assert type(w).__mro__[:3] == (c.code._GraphWriterConnection,
                                  c.code._GraphCommitConnection, sqlite3.Connection)
    assert c.code._owns_graph_writer(c.p, w)
    assert c.p._graph_writer_connections[w] is w._graph_lifetime
    return w


@pytest.mark.parametrize('route', ['connection', 'prior_cursor', 'returned_cursor', 'executemany', 'context'])
def test_private_noncommit_primary_precedes_successful_rollback(derived_case, route):
    with PrivateFixture('private-cause-' + route) as c:
        rows_table(c)
        before = peer.whole_state(c)
        w = c.writer = issued(c)
        cursor = w.execute('SELECT 1') if route == 'returned_cursor' else w.cursor()
        primary = Cancel('private-noncommit-original')
        events, reentry, stages = [], [], []

        def authorizer(action, first, second, db, trigger):
            if action in (sqlite3.SQLITE_READ, sqlite3.SQLITE_UPDATE) and first == 'jro_callback_rows':
                assert c.code._graph_writer_identity(c.p, w)
                assert w._graph_inflight is not None and w._graph_native_operation is not None
                events.append('origin')
                for operation in (lambda: w.execute('SELECT 1'),
                                  lambda: w.set_authorizer(None), w.close):
                    with pytest.raises(RuntimeError, match='^graph_writer_operation_in_flight$'):
                        operation()
                    reentry.append('refused')
                raise primary
            if action == sqlite3.SQLITE_TRANSACTION and first == 'ROLLBACK':
                # The originating cause was already delivered, not adopted as
                # this new superclass rollback call's cleanup failure.
                assert w._graph_commit_error is None
                assert w._graph_native_operation[0] is None
                events.append('rollback-permitted')
            return sqlite3.SQLITE_OK

        w.set_authorizer(authorizer)
        try:
            with pytest.raises(Cancel) as caught:
                with (w if route == 'context' else c.p._claim_transaction(w)):
                    stages.append(c.p._claim_tx_document_stage)
                    if route == 'executemany':
                        w.executemany('UPDATE jro_callback_rows SET value=?', [('after',)])
                    elif route in ('prior_cursor', 'returned_cursor'):
                        cursor.execute('SELECT value FROM jro_callback_rows')
                    else:
                        w.execute('SELECT value FROM jro_callback_rows')
            assert caught.value is primary
            assert isinstance(primary.__cause__, sqlite3.DatabaseError)
            assert events == ['origin', 'rollback-permitted'] and len(reentry) == 3
            assert not w.in_transaction and w._graph_state == 'expired'
            assert w._graph_primary is primary and w._graph_inflight is None
            assert w._graph_native_operation is None and w._graph_commit_error is None
            assert c.p._claim_tx_connection is None and c.p._claim_tx_document_stage is None
            assert stages[0][2] == [] and c.p._transaction_quarantine is None
            assert c.p._transaction_primary is None and c.p._lifecycle_state == 'ready'
            assert not any('UNKNOWN' in note for note in getattr(primary, '__notes__', ()))
            assert peer.whole_state(c) == before
            with pytest.raises(RuntimeError, match='^graph_writer_lifetime_expired$'):
                w.execute('SELECT 1')
        finally:
            cursor.close()
        c.code._close_graph_writer_connection(w, True)
        c.writer = None
        assert w not in c.p._graph_writer_connections and w._graph_state == 'closed'
        healthy = issued(c)
        try:
            seen = []
            healthy.set_authorizer(lambda *args: seen.append(args[0]) or sqlite3.SQLITE_OK)
            with c.p._claim_transaction(healthy):
                healthy.execute("INSERT INTO jro_callback_rows VALUES('healthy')")
            assert seen and healthy._graph_state == 'expired' and not healthy.in_transaction
        finally:
            c.code._close_graph_writer_connection(healthy, True)
        assert c.conn.execute('SELECT COUNT(*) FROM jro_callback_rows').fetchone()[0] == 2
        peer.retired(c)
        c._emit(dict(event='JRO_C01_native_known', route=route, exact_primary=True,
                     actual_rollback=True, no_false_quarantine=True, next_factory_healthy=True))


def test_private_real_rollback_DENY_retains_original_owner_and_admission(derived_case):
    with PrivateFixture('private-real-unknown') as c:
        rows_table(c)
        source = c.ingest()
        before = peer.whole_state(c)
        w = c.writer = issued(c)
        primary = Cancel('private-origin-before-real-rollback-DENY')
        events, stages, obligations = [], [], []

        def authorizer(action, first, second, db, trigger):
            if action == sqlite3.SQLITE_READ and first == 'jro_callback_rows':
                events.append('origin')
                raise primary
            if action == sqlite3.SQLITE_TRANSACTION and first == 'ROLLBACK':
                assert w._graph_commit_error is None
                events.append('rollback-DENY')
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        with pytest.raises(Cancel) as caught:
            with c.p._claim_transaction(w):
                chunk = dict(w.execute('SELECT * FROM document_chunks WHERE source_id=?',
                                       (source['source_id'],)).fetchone())
                admission = c.doc._DocumentEmbeddingAdmission(c.p, w, chunk,
                    c.doc._document_embedding_actor(c.p))
                c.doc._assert_ingest_authority(c.p, w, source['source_id'], admission, before=True)
                with c.doc._document_write_transaction(c.p, w,
                        _document_ingest=(source['source_id'], admission)):
                    stage = c.p._claim_tx_document_stage
                    stages.append(stage)
                    obligations.extend(stage[2])
                    assert len(obligations) == 1 and obligations[0][1] is admission
                    w.execute("INSERT INTO jro_callback_rows VALUES('uncommitted')")
                    w.set_authorizer(authorizer)
                    w.execute('SELECT value FROM jro_callback_rows')
        assert caught.value is primary and isinstance(primary.__cause__, sqlite3.DatabaseError)
        assert events == ['origin', 'rollback-DENY']
        assert w.in_transaction and w._graph_state == 'quarantined'
        assert w._graph_primary is primary and c.p._transaction_primary is primary
        assert c.p._transaction_quarantine is w and c.p._claim_tx_connection is w
        assert c.p._claim_tx_thread == threading.get_ident()
        assert c.p._claim_tx_document_stage is stages[0]
        assert tuple(stages[0][2]) == tuple(obligations) and stages[0][2][0] is obligations[0]
        assert c.p._graph_writer_connections[w] is w._graph_lifetime
        assert w._graph_inflight is None and w._graph_native_operation is None
        assert w._graph_commit_error is None and c.p._lifecycle_state == 'quarantined'
        assert any('UNKNOWN' in note for note in primary.__notes__)
        assert peer.whole_state(c) == before
        for operation in (c.p._connect, lambda: issued(c),
                          lambda: c.code._open_graph_reader_connection(c.p),
                          lambda: w.execute('SELECT 1')):
            with pytest.raises(RuntimeError):
                operation()
        assert not c.p._release_connection_for_retry(primary)
        assert c.p._transaction_primary is primary and c.p._claim_tx_document_stage is stages[0]
        assert c.p._graph_writer_connections[w] is w._graph_lifetime
        c._emit(dict(event='JRO_C01_native_UNKNOWN', actual_rollback_DENY=True,
                     exact_primary_owner_registry_admission_retained=True, durable_equal=True))


def test_shared_cursor_nested_context_and_raw_boundaries(derived_case):
    with fx.Fixture('shared-cause-boundaries') as c:
        rows_table(c)
        for route in ('connection', 'prior_cursor', 'returned_cursor', 'executemany'):
            before = peer.whole_state(c)
            cursor = c.conn.execute('SELECT 1') if route == 'returned_cursor' else c.conn.cursor()
            assert type(cursor) is c.code._GraphCommitCursor
            primary = Cancel('shared-original-' + route)
            nested = []
            in_callback = []
            raw_primary = Cancel('nested-raw-not-the-outer-cause')

            def authorizer(action, first, second, db, trigger):
                if action in (sqlite3.SQLITE_READ, sqlite3.SQLITE_UPDATE) and first == 'jro_callback_rows':
                    if in_callback:
                        raise raw_primary
                    outer = c.conn._graph_native_operation
                    assert outer is not None
                    in_callback.append(True)
                    try:
                        with pytest.raises(sqlite3.DatabaseError):
                            sqlite3.Connection.execute(c.conn, 'SELECT value FROM jro_callback_rows')
                    finally:
                        in_callback.pop()
                    assert outer[0] is None and c.conn._graph_commit_error is None
                    assert c.conn.execute('SELECT 1').fetchone()[0] == 1
                    assert c.conn._graph_native_operation is outer
                    nested.append('healthy-inner')
                    raise primary
                return sqlite3.SQLITE_OK

            c.conn.set_authorizer(authorizer)
            try:
                with pytest.raises(Cancel) as caught:
                    with c.p._claim_transaction(c.conn):
                        if route == 'executemany':
                            c.conn.executemany('UPDATE jro_callback_rows SET value=?', [('after',)])
                        else:
                            target = c.conn if route == 'connection' else cursor
                            target.execute('SELECT value FROM jro_callback_rows')
                assert caught.value is primary and nested == ['healthy-inner']
                assert isinstance(primary.__cause__, sqlite3.DatabaseError)
            finally:
                cursor.close()
                c.conn.set_authorizer(None)
            assert c.conn._graph_native_operation is None and c.conn._graph_commit_error is None
            assert peer.whole_state(c) == before
            peer.retired(c)

        primary = Cancel('shared-native-context-COMMIT')
        commits, rollbacks = [], []
        def context_authorizer(action, first, second, db, trigger):
            if action == sqlite3.SQLITE_TRANSACTION and first == 'COMMIT':
                commits.append(first)
                raise primary
            if action == sqlite3.SQLITE_TRANSACTION and first == 'ROLLBACK':
                rollbacks.append(first)
            return sqlite3.SQLITE_OK
        before = peer.whole_state(c)
        c.conn.set_authorizer(context_authorizer)
        try:
            with pytest.raises(Cancel) as caught:
                with c.conn:
                    c.conn.execute("INSERT INTO jro_callback_rows VALUES('context-rollback')")
            assert caught.value is primary and commits == ['COMMIT'] and rollbacks == ['ROLLBACK']
        finally:
            c.conn.set_authorizer(None)
        assert c.conn._graph_commit_error is None and c.conn._graph_native_operation is None
        assert peer.whole_state(c) == before
        peer.retired(c)

        # Explicit raw descriptors/custom cursors bypass Python wrappers. They
        # keep stdlib DatabaseError, but must not poison a later wrapped call.
        for route in ('base-descriptor', 'custom-raw-cursor'):
            primary = Cancel('raw-stdlib-semantics')
            calls = []
            def raw_authorizer(action, first, second, db, trigger):
                if action == sqlite3.SQLITE_READ and first == 'jro_callback_rows':
                    calls.append('raw')
                    raise primary
                return sqlite3.SQLITE_OK
            c.conn.set_authorizer(raw_authorizer)
            cursor = c.conn.cursor(factory=sqlite3.Cursor)
            try:
                with pytest.raises(sqlite3.DatabaseError):
                    if route == 'base-descriptor':
                        sqlite3.Connection.execute(c.conn, 'SELECT value FROM jro_callback_rows')
                    else:
                        cursor.execute('SELECT value FROM jro_callback_rows')
                assert calls == ['raw'] and c.conn._graph_commit_error is None
                c.conn.rollback()  # Not the old raw callback's error delivery.
                assert c.conn.execute('SELECT 1').fetchone()[0] == 1
            finally:
                cursor.close()
                c.conn.set_authorizer(None)
        with c.p._claim_transaction(c.conn):
            c.conn.execute("INSERT INTO jro_callback_rows VALUES('next-healthy')")
        assert c.conn.execute('SELECT COUNT(*) FROM jro_callback_rows').fetchone()[0] == 2
        peer.retired(c)
        c._emit(dict(event='native_shared_nested_context_raw_controls',
                     exact_wrapped_primaries=True, raw_cause_not_replayed=True, next_healthy=True))
