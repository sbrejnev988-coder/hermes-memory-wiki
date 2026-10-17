"""C1-NATIVE-FENCE-01: genuine direct SPI, file SQLite, actual native callbacks.

Supported default document commits remain healthy. Critical authorizer callbacks
cannot safely reenter full original SQL/path/policy guards; that lifetime must
be explicitly refused (callback restrictions are never silently disabled).
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys

import pytest

_SPEC = importlib.util.spec_from_file_location('document_native_fixture',
    Path(__file__).with_name('ci_owned') / 'derived_claim_materialization_fixture.py')
fx = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = fx
_SPEC.loader.exec_module(fx)
derived_case = fx.derived_case


def whole_state(c):
    """Independent reader of the entire durable user write-set, not public status."""
    reader = sqlite3.connect(str(c.path))
    try:
        tables = [r[0] for r in reader.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        images = {}
        for table in tables:
            # Names originate only from this own SQLite schema, not tool input.
            rows = reader.execute('SELECT * FROM "' + table.replace('"', '""') + '"').fetchall()
            typed = [[(type(value).__name__, value.hex() if type(value) is bytes else value)
                      for value in row] for row in rows]
            images[table] = dict(count=len(rows), sha256=hashlib.sha256(
                json.dumps(sorted(typed, key=repr), separators=(',', ':')).encode()).hexdigest())
    finally:
        reader.close()
    ordinal = getattr(c, '_native_whole_reads', 0) + 1
    c._native_whole_reads = ordinal
    raw = (json.dumps(images, sort_keys=True, indent=2) + '\n').encode()
    path = c.dir / ('durable-write-set-' + str(ordinal) + '.json')
    path.write_bytes(raw)
    c._emit(dict(event='native_fence_independent_whole_write_set', path=path.name,
                 tables=len(images), sha256=hashlib.sha256(raw).hexdigest()))
    return images


def claim_effects_unchanged(before, after):
    for table in ('claims', 'evidence', 'memory_mutations', 'claim_write_fingerprints',
                  'index_outbox', 'claims_fts'):
        assert before[table] == after[table], table


def retired(c):
    assert not c.conn.in_transaction and c.p._transaction_quarantine is None
    assert c.p._claim_tx_document_stage is None and c.p._claim_tx_connection is None
    assert c.conn._document_commit_image is None and c.conn._document_commit_flight is None


@pytest.mark.parametrize('route', ['direct', 'joined'])
def test_actual_native_OK_actor_drift_cannot_commit(derived_case, route):
    """The same safety oracle runs on pristine e1d4 and on the correction."""
    with fx.Fixture('native-actor-' + route) as c:
        source = c.ingest()
        before = whole_state(c)
        seen, stages = [], []
        original_session = c.p.session_id
        def authorizer(op, one, two, db, trigger):
            stage = c.p._claim_tx_document_stage
            if op == sqlite3.SQLITE_TRANSACTION and one == 'COMMIT' and stage is not None and stage[2]:
                seen.append((op, one, len(stage[2]), len(c.p._claim_tx_graph_stage[2])))
                stages.append(stage)
                c.p.session_id = 'withdrawn-at-native-commit'
            return sqlite3.SQLITE_OK
        c.conn.set_authorizer(authorizer)
        failure = None
        result = None
        try:
            if route == 'joined':
                try:
                    with c.p._claim_transaction(c.conn):
                        result = c.embed(source['source_id'])
                        assert result['commit_pending'] and result['created'] == 1
                        assert whole_state(c) == before
                except RuntimeError as error:
                    failure = error
            else:
                result = c.embed(source['source_id'])
        finally:
            c.conn.set_authorizer(None)
        after = whole_state(c)
        # Preserve causal witness before assertions, including baseline durable violation.
        c._emit(dict(event='C1_NATIVE_FENCE_01_actual_native_callback', route=route,
            native_COMMIT_callbacks=seen, result=result, failure_type=type(failure).__name__ if failure else None,
            durable_claim_delta=after['claims']['count'] - before['claims']['count'],
            actor_changed=c.p.session_id != original_session))
        assert seen and all(row[3] == 0 for row in seen), 'genuine document-only native COMMIT not reached'
        claim_effects_unchanged(before, after)
        if route == 'joined':
            assert failure is not None and str(failure) == 'document_native_authorizer_lifetime_unsupported'
            assert after == before
        else:
            assert result['created'] == 0 and result['failed'] == 1, result
        assert all(stage[2] == [] for stage in stages)
        retired(c)
        c.p.session_id = original_session  # Own fixture, only AFTER proven rollback.
        assert c.embed(source['source_id'])['created'] == 1
        retired(c)


@pytest.mark.parametrize('route', ['direct', 'joined'])
def test_default_document_commit_and_postcommit_remain_healthy(derived_case, route):
    with fx.Fixture('native-healthy-' + route) as c:
        if route == 'direct':
            source = c.ingest()
            with fx.observe_callbacks(c) as callbacks:
                result = c.embed(source['source_id'])
                assert result['created'] == 1 and not result['commit_pending']
        else:
            before = whole_state(c)
            with fx.observe_callbacks(c) as callbacks:
                with c.p._claim_transaction(c.conn):
                    source = c.ingest(embed=True)
                    assert source['embedding']['created'] == 1 and source['embedding']['commit_pending']
                    assert not callbacks and whole_state(c) == before
                    stage = c.p._claim_tx_document_stage
                    assert len(stage[2]) == 2 and not c.p._claim_tx_graph_stage[2]
        assert len(callbacks) == 1 and callbacks[0]['idle']
        assert callbacks[0]['durable_links'] == callbacks[0]['durable_claims'] == 1
        assert whole_state(c)['claims']['count'] == 1
        retired(c)


def test_later_native_callback_lifetime_is_explicitly_refused(derived_case):
    with fx.Fixture('native-later') as c:
        for callback_kind in ('trace', 'progress'):
            source = c.ingest('later-' + callback_kind)
            before = whole_state(c)
            calls = []
            if callback_kind == 'trace':
                callback = lambda sql: calls.append('trace')
                c.conn.set_trace_callback(callback)
            else:
                def callback():
                    calls.append('progress')
                    return 0
                c.conn.set_progress_handler(callback, 1)
            try:
                with pytest.raises(RuntimeError, match='^document_native_commit_late_callback_unsupported$'):
                    with c.p._claim_transaction(c.conn):
                        assert c.embed(source['source_id'])['created'] == 1
                        assert c.p._claim_tx_document_stage[2] and not c.p._claim_tx_graph_stage[2]
                assert calls, 'user callback silently disabled'
                assert (c.conn._graph_trace if callback_kind == 'trace' else c.conn._graph_progress) is callback
            finally:
                c.conn.set_trace_callback(None) if callback_kind == 'trace' else c.conn.set_progress_handler(None, 0)
            assert whole_state(c) == before
            retired(c)
            assert c.embed(source['source_id'])['created'] == 1


def test_healthy_user_authorizer_is_refused_only_for_critical_document_stage(derived_case):
    with fx.Fixture('native-supported-limit') as c:
        source = c.ingest()
        before = whole_state(c)
        commits = []
        def callback(op, one, two, db, trigger):
            if op == sqlite3.SQLITE_TRANSACTION and one == 'COMMIT':
                commits.append(bool(c.p._claim_tx_document_stage and c.p._claim_tx_document_stage[2]))
            return sqlite3.SQLITE_OK
        c.conn.set_authorizer(callback)
        try:
            with pytest.raises(RuntimeError, match='^document_native_authorizer_lifetime_unsupported$'):
                with c.p._claim_transaction(c.conn):
                    assert c.embed(source['source_id'])['created'] == 1
            assert commits == [True] and c.conn._graph_user_authorizer is callback
            assert whole_state(c) == before
            retired(c)
            with c.p._claim_transaction(c.conn):
                c.conn.execute('CREATE TABLE authored_ordinary_positive(value TEXT)')
                c.conn.execute("INSERT INTO authored_ordinary_positive VALUES('healthy')")
            assert commits[-1] is False and whole_state(c)['authored_ordinary_positive']['count'] == 1
        finally:
            c.conn.set_authorizer(None)
        assert c.embed(source['source_id'])['created'] == 1


def test_only_actual_owner_can_finish_document_stage(derived_case):
    with fx.Fixture('native-shortcuts') as c:
        for shortcut in ('commit', 'COMMIT', 'END', 'cursor', 'returned_cursor', 'context', 'script'):
            source = c.ingest('shortcut-' + shortcut)
            before = whole_state(c)
            cursor = c.conn.cursor()  # Issued before the stage is created.
            try:
                with pytest.raises((sqlite3.DatabaseError, PermissionError)):
                    with c.p._claim_transaction(c.conn):
                        assert c.embed(source['source_id'])['created'] == 1
                        assert whole_state(c) == before
                        if shortcut == 'commit':
                            c.conn.commit()
                        elif shortcut in ('COMMIT', 'END'):
                            c.conn.execute(shortcut)
                        elif shortcut == 'cursor':
                            cursor.execute('END')
                        elif shortcut == 'returned_cursor':
                            c.conn.execute('SELECT 1').execute('COMMIT')
                        elif shortcut == 'context':
                            with c.conn:
                                pass
                        else:
                            c.conn.executescript('SELECT 1;')
            finally:
                cursor.close()
            assert whole_state(c) == before
            retired(c)
            assert c.embed(source['source_id'])['created'] == 1
            c._emit(dict(event='native_shortcut_refused_before_effect', shortcut=shortcut,
                         known_rollback_and_next_stage_healthy=True))


def test_first_and_repeated_original_admissions_are_not_replaced(derived_case):
    with fx.Fixture('native-multiple') as c:
        before = whole_state(c)
        stages, originals, seen = [], [], []
        def callback(op, one, two, db, trigger):
            if op == sqlite3.SQLITE_TRANSACTION and one == 'COMMIT':
                stage = c.p._claim_tx_document_stage
                if stage is not None and stage[2]:
                    assert stage is stages[0]
                    assert len(stage[2]) == len(originals) == 5
                    assert all(a is b for a, b in zip(stage[2], originals))
                    seen.append('COMMIT')
            return sqlite3.SQLITE_OK
        c.conn.set_authorizer(callback)
        try:
            with pytest.raises(RuntimeError, match='^document_native_authorizer_lifetime_unsupported$'):
                with c.p._claim_transaction(c.conn):
                    first = c.ingest('one', embed=True)
                    second = c.ingest('two', fx.NEW_TEXT, embed=True)
                    repeated = c.ingest('one')
                    assert first['source_id'] == repeated['source_id'] != second['source_id']
                    stage = c.p._claim_tx_document_stage
                    stages.append(stage)
                    originals.extend(stage[2])
                    assert len(originals) == 5 and not c.p._claim_tx_graph_stage[2]
                    assert whole_state(c) == before
        finally:
            c.conn.set_authorizer(None)
        assert seen == ['COMMIT'] and whole_state(c) == before
        assert stages[0][2] == []
        retired(c)
        c.ingest('one', embed=True)
        assert whole_state(c)['claims']['count'] == 1


def test_native_unknown_keeps_original_primary_exact_owner_and_admissions(derived_case):
    class Cancel(BaseException):
        pass
    with fx.Fixture('native-unknown') as c:
        source = c.ingest()
        before = whole_state(c)
        primary = Cancel('authored-native-cancellation')
        stages, obligations, commits, rollbacks = [], [], [], []
        def callback(op, one, two, db, trigger):
            if op == sqlite3.SQLITE_TRANSACTION and one == 'COMMIT':
                stage = c.p._claim_tx_document_stage
                if stage is not None and stage[2]:
                    stages.append(stage)
                    obligations.append(tuple(stage[2]))
                    commits.append(one)
                    raise primary
            if op == sqlite3.SQLITE_TRANSACTION and one == 'ROLLBACK':
                rollbacks.append(one)
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK
        c.conn.set_authorizer(callback)
        try:
            with pytest.raises(Cancel) as caught:
                with c.p._claim_transaction(c.conn):
                    assert c.embed(source['source_id'])['created'] == 1
            assert caught.value is primary and commits == ['COMMIT'] and rollbacks
            stage = stages[0]
            assert c.p._transaction_primary is primary and c.p._transaction_quarantine is c.conn
            assert c.p._claim_tx_connection is c.conn and c.p._claim_tx_document_stage is stage
            assert stage[0] is c.conn and tuple(stage[2]) == obligations[0] and stage[2]
            assert c.conn.in_transaction and c.p._lifecycle_state == 'quarantined'
            assert any('UNKNOWN' in note for note in primary.__notes__)
            assert whole_state(c) == before
            with pytest.raises(RuntimeError):
                c.p._connect()
            assert c.p._transaction_primary is primary and c.p._claim_tx_document_stage is stage
            assert c.conn._document_commit_image[0] is stage
            assert c.conn._document_commit_flight is None
            c._emit(dict(event='native_UNKNOWN_retained', exact_owner_primary_admissions=True,
                         native_COMMIT_callbacks=len(commits), native_ROLLBACK_denials=len(rollbacks)))
        finally:
            c.conn.set_authorizer(None)
            c.safety_close_unknown = True


@pytest.mark.parametrize('route', ['direct', 'joined'])
def test_native_ingest_original_actor_cannot_be_recaptured(derived_case, route):
    with fx.Fixture('native-ingest-' + route) as c:
        before = whole_state(c)
        seen = []
        original_bot = c.p.bot_id
        def callback(op, one, two, db, trigger):
            stage = c.p._claim_tx_document_stage
            if op == sqlite3.SQLITE_TRANSACTION and one == 'COMMIT' and stage is not None and stage[2]:
                seen.append(len(stage[2]))
                c.p.bot_id = 'withdrawn-native-bot'
            return sqlite3.SQLITE_OK
        c.conn.set_authorizer(callback)
        try:
            with pytest.raises(RuntimeError, match='^document_native_authorizer_lifetime_unsupported$'):
                if route == 'direct':
                    c.ingest()
                else:
                    with c.p._claim_transaction(c.conn):
                        c.ingest()
                        assert whole_state(c) == before
        finally:
            c.conn.set_authorizer(None)
        assert seen == [1] and whole_state(c) == before
        retired(c)
        c.p.bot_id = original_bot
        c.ingest()
        retired(c)


def test_native_primary_known_rollback_and_reentrant_completion(derived_case):
    class Cancel(BaseException):
        pass
    with fx.Fixture('native-primary') as c:
        source = c.ingest()
        before = whole_state(c)
        primary = Cancel('authored-exact-primary')
        callbacks, reentry = [], []
        cursor = c.conn.cursor()
        def callback(op, one, two, db, trigger):
            if op == sqlite3.SQLITE_TRANSACTION and one == 'COMMIT':
                stage = c.p._claim_tx_document_stage
                if stage is not None and stage[2]:
                    callbacks.append(stage)
                    for operation in (lambda: cursor.execute('END'),
                                      lambda: sqlite3.Connection.commit(c.conn),
                                      lambda: c.conn.set_authorizer(None), c.conn.close):
                        try:
                            operation()
                        except (sqlite3.DatabaseError, RuntimeError) as error:
                            reentry.append(type(error).__name__)
                    raise primary
            return sqlite3.SQLITE_OK
        c.conn.set_authorizer(callback)
        try:
            with pytest.raises(Cancel) as caught:
                with c.p._claim_transaction(c.conn):
                    assert c.embed(source['source_id'])['created'] == 1
            assert caught.value is primary and c.conn._graph_commit_error is primary
        finally:
            cursor.close()
            c.conn.set_authorizer(None)
        assert len(callbacks) == 1 and len(reentry) == 4
        assert callbacks[0][2] == [] and whole_state(c) == before
        retired(c)
        assert c.embed(source['source_id'])['created'] == 1


def test_noncritical_shared_native_callbacks_still_run(derived_case):
    with fx.Fixture('native-ordinary') as c:
        for callback_kind in ('authorizer', 'trace', 'progress'):
            calls = []
            if callback_kind == 'authorizer':
                def callback(*args):
                    calls.append('authorizer')
                    return sqlite3.SQLITE_OK
                c.conn.set_authorizer(callback)
            elif callback_kind == 'trace':
                c.conn.set_trace_callback(lambda sql: calls.append('trace'))
            else:
                def progress():
                    calls.append('progress')
                    return 0
                c.conn.set_progress_handler(progress, 1)
            try:
                with c.p._claim_transaction(c.conn):
                    c.conn.execute('CREATE TABLE authored_shared_positive_' + callback_kind + '(value TEXT)')
                    c.conn.execute("INSERT INTO authored_shared_positive_" + callback_kind + " VALUES('healthy')")
                assert calls and whole_state(c)['authored_shared_positive_' + callback_kind]['count'] == 1
                assert c.conn.execute('SELECT COUNT(*) FROM claims').fetchone()[0] == 0
                retired(c)
            finally:
                c.conn.set_authorizer(None)
                c.conn.set_trace_callback(None)
                c.conn.set_progress_handler(None, 0)
