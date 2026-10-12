"""Native SQLite authorizer seam; real provider, synthetic owned data only."""
from contextlib import closing
import hashlib
import os
from pathlib import Path
import sqlite3
import sys
import threading

import pytest
import memory_wiki as wiki
from memory_wiki import code_knowledge_graph as graph
from memory_wiki import background_jobs as jobs


class NativeGraphProvider(wiki.MemoryWikiProvider):
    def _auto_graph_enrich_extracted_claims(self, claim_ids):
        factory = getattr(self, 'fixture_authorizer', None)
        if factory is not None:
            self._connect().set_authorizer(factory(self))
        self._add_relation(edge(claim_ids[0]))
        return {'errors': 0, 'deadline_exhausted': 0}


@pytest.fixture
def store(request, monkeypatch):
    root = Path(os.environ['RECOVERY_DIAGNOSTIC_OUT']) / 'controls' / hashlib.sha256(request.node.nodeid.encode()).hexdigest()[:16]
    home = root / 'home'
    home.mkdir(parents=True)
    monkeypatch.setenv('HERMES_HOME', str(home))
    for key in ('MEMORY_WIKI_SEMANTIC', 'MEMORY_WIKI_BACKGROUND_JOBS_ENABLED', 'MEMORY_WIKI_EXTRACTION_ENABLED', 'MW_EXTRACTION_ENABLED', 'MEMORY_WIKI_GRAPH_AUTO_EXTRACT_ENABLED', 'MEMORY_WIKI_GRAPH_EXTRACT_ENABLED', 'MEMORY_WIKI_QDRANT_ENABLED', 'MEMORY_WIKI_EPISODIC_ENABLED', 'MEMORY_WIKI_EVENTS_ENABLED', 'MEMORY_WIKI_OBSERVATIONS_ENABLED'):
        monkeypatch.setenv(key, '0')
    provider = NativeGraphProvider()
    provider.initialize('synthetic-native-commit-session', hermes_home=str(home), agent_context='test', bot_id='synthetic-native-commit-bot', project_id='diagnostic')
    assert provider._background_worker is None
    assert provider.db_path.resolve().is_relative_to(root.resolve())
    with wiki._native_profile_scope(home):
        yield provider
    # Exact test-owned emergency release AFTER UNKNOWN assertions, not recovery.
    handles = set(getattr(provider, '_graph_writer_connections', {}))
    if provider._transaction_quarantine is not None:
        handles.update({provider._conn, provider._owned_conn, provider._transaction_quarantine} - {None})
    for conn in handles:
        sqlite3.Connection.set_authorizer(conn, None)
        sqlite3.Connection.close(conn)
    if provider._transaction_quarantine is None:
        provider._shutdown_lifecycle(render=False)
        assert provider._conn is None and provider._owned_conn is None


def seed(provider):
    cid = 'c_synthetic_native_commit'
    stamp = wiki.now()
    with provider._claim_transaction() as conn:
        conn.execute("""INSERT INTO claims(id,hash,claim,normalized_claim,topic,type,scope,visibility_scope,origin_bot_id,origin_session_id,origin_chat_hash,project_id,status,risk,quality,trust_class,confidence,salience,freshness_at,updated_at,created_at,source)
            VALUES(?,?,?,?,?,'fact','chat','chat',?,?,?,'','active','low',1,'fact',.9,.9,?,?,?,'extractor:heuristic')""",
            (cid, wiki.sha(cid), 'Synthetic Atlas runs on synthetic Borealis.', 'Synthetic Atlas runs on synthetic Borealis.', 'synthetic-graph', provider.bot_id, provider.session_id, provider._chat_hash(provider.session_id), stamp, stamp, stamp))
    return cid


def edge(cid):
    return {'subject': 'Synthetic Atlas', 'predicate': 'runs_on', 'object': 'Synthetic Borealis', 'source_claim_id': cid, 'confidence': .9}


def counts(provider):
    with closing(sqlite3.connect(str(provider.db_path))) as conn:
        return tuple(conn.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0] for table in ('relations', 'entities'))


@pytest.mark.parametrize('path', ['private', 'shared'])
@pytest.mark.parametrize('mutation', ['healthy', 'actor', 'source', 'registry'])
def test_native_commit_authorizer_original_admission(store, path, mutation):
    cid = seed(store)
    conn, owned = graph._open_graph_writer_connection(store) if path == 'private' else (store._connect(), False)
    original = store.session_id
    seen = []
    audit_events, auditing = [], [False]
    def audit(event, args):
        if auditing[0]:
            audit_events.append(event)
    sys.addaudithook(audit)
    def authorize(action, a, b, db, trigger):
        if action == sqlite3.SQLITE_TRANSACTION and a == 'COMMIT':
            seen.append('native_COMMIT')
            if mutation == 'actor':
                store.session_id = 'synthetic-withdrawn-actor'
            elif mutation == 'registry':
                if owned:
                    del store._graph_writer_connections[conn]
                else:
                    store._owned_conn = None
            elif mutation == 'source':
                # Shared supports reentrant SQL; private must refuse it safely.
                conn.execute("UPDATE claims SET status='retired' WHERE id=?", (cid,))
            elif mutation == 'healthy':
                auditing[0] = True
                try:
                    graph._graph_commit_fence(conn, conn._graph_commit_flight)
                finally:
                    auditing[0] = False
        return sqlite3.SQLITE_OK
    conn.set_authorizer(authorize)
    try:
        if mutation == 'healthy':
            with store._claim_transaction(conn):
                store._add_relation(edge(cid), conn=conn)
            assert counts(store) == (1, 2)
            assert store._claim_tx_graph_stage is None and store._transaction_quarantine is None
        else:
            with pytest.raises((PermissionError, RuntimeError, sqlite3.DatabaseError)) as caught:
                with store._claim_transaction(conn):
                    store._add_relation(edge(cid), conn=conn)
            assert counts(store) == (0, 0)
            if mutation == 'registry' and owned:
                assert store._transaction_quarantine is conn and conn.in_transaction
                assert store._claim_tx_graph_stage[0] is conn
                assert store._transaction_primary is caught.value
            else:
                assert not conn.in_transaction
        assert seen == ['native_COMMIT']
        assert audit_events == []
    finally:
        store.session_id = original
        if mutation == 'registry' and not owned:
            store._owned_conn = conn  # Fixture restoration, not production recovery.
        if owned and store._transaction_quarantine is None:
            graph._close_graph_writer_connection(conn, True)


@pytest.mark.parametrize('path', ['private', 'shared'])
def test_native_commit_denied_rollback_retains_exact_unknown(store, path):
    cid = seed(store)
    conn, owned = graph._open_graph_writer_connection(store) if path == 'private' else (store._connect(), False)
    original = store.session_id
    def authorize(action, a, b, db, trigger):
        if action == sqlite3.SQLITE_TRANSACTION:
            if a == 'COMMIT':
                store.session_id = 'synthetic-withdrawn-actor'
            elif a == 'ROLLBACK':
                return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK
    conn.set_authorizer(authorize)
    try:
        with pytest.raises((PermissionError, sqlite3.DatabaseError)) as caught:
            with store._claim_transaction(conn):
                store._add_relation(edge(cid), conn=conn)
        assert counts(store) == (0, 0) and conn.in_transaction
        assert store._transaction_quarantine is store._claim_tx_connection is conn
        assert store._claim_tx_graph_stage[0] is conn and len(store._claim_tx_graph_stage[2]) == 1
        assert store._claim_tx_graph_stage[1] == threading.get_ident()
        assert store._transaction_primary is caught.value
        assert any('outcome=UNKNOWN' in note for note in caught.value.__notes__)
        with pytest.raises(RuntimeError, match='not_ready'):
            store._connect()
        assert not store._release_connection_for_retry(caught.value)
    finally:
        store.session_id = original


@pytest.mark.parametrize('withdrawal', ['actor', 'source'])
def test_last_native_lease_read_cannot_withdraw_original_image(store, withdrawal):
    cid = seed(store)
    assert jobs.enqueue_claim(store, cid)
    jobstore = jobs.JobStore(store.db_path, jobs.profile_key(store), jobs.owner_key(store))
    worker = 'a' * 32
    job = jobstore.lease(worker)
    assert job is not None and jobstore.owns(job, worker)
    seen = []
    def observe(frame, event, arg):
        if event != 'return' or frame.f_code is not jobs.JobStore.owns.__code__ or seen:
            return
        parent = frame.f_back
        if parent is None or parent.f_code.co_name != '_assert_graph_effects' or parent.f_locals.get('terminal_stage') is None:
            return
        actor, conn = parent.f_locals['self'], parent.f_locals['conn']
        seen.append('last_real_lease_read')
        if withdrawal == 'actor':
            actor.session_id = 'synthetic-late-withdrawn-actor'
        else:
            conn.execute("UPDATE claims SET status='retired' WHERE id=?", (cid,))
    previous = sys.getprofile()
    try:
        sys.setprofile(observe)
        with pytest.raises(PermissionError, match='graph_'):
            jobs._run_job(store, wiki, job, lease_valid=lambda: jobstore.owns(job, worker),
                          lease_valid_in_transaction=lambda conn: jobstore.owns(job, worker, connection=conn))
    finally:
        sys.setprofile(previous)
    assert seen == ['last_real_lease_read'] and counts(store) == (0, 0)
    assert jobstore.owns(job, worker) and store._transaction_quarantine is None


def test_native_commit_original_job_lease_withdrawal(store):
    cid = seed(store)
    assert jobs.enqueue_claim(store, cid)
    jobstore = jobs.JobStore(store.db_path, jobs.profile_key(store), jobs.owner_key(store))
    worker = 'a' * 32
    job = jobstore.lease(worker)
    seen = []
    def factory(actor):
        def authorize(action, a, b, db, trigger):
            if action == sqlite3.SQLITE_TRANSACTION and a == 'COMMIT':
                seen.append('native_COMMIT')
                actor._conn.execute('UPDATE memory_jobs SET lease_expires_at=0 WHERE job_id=?', (job['job_id'],))
            return sqlite3.SQLITE_OK
        return authorize
    store.fixture_authorizer = factory
    with pytest.raises(PermissionError, match='graph_native_commit_image_changed'):
        jobs._run_job(store, wiki, job, lease_valid=lambda: jobstore.owns(job, worker),
                      lease_valid_in_transaction=lambda conn: jobstore.owns(job, worker, connection=conn))
    assert seen == ['native_COMMIT'] and counts(store) == (0, 0)
    assert jobstore.owns(job, worker) and store._transaction_quarantine is None


def test_shared_native_authorizer_cannot_commit_reentrantly_before_fence(store):
    cid = seed(store)
    conn = store._connect()
    seen = []
    def authorize(action, a, b, db, trigger):
        if action == sqlite3.SQLITE_TRANSACTION and a == 'COMMIT' and not seen:
            seen.append('outer_native_COMMIT')
            with pytest.raises(sqlite3.DatabaseError):
                conn.execute('COMMIT')
            with pytest.raises(RuntimeError, match='in_flight'):
                conn.commit()
            with pytest.raises(RuntimeError, match='in_flight'):
                conn.close()
            assert conn._graph_commit_flight is not None and conn.in_transaction
            store.session_id = 'synthetic-withdrawn-after-nested-refusal'
        return sqlite3.SQLITE_OK
    original = store.session_id
    conn.set_authorizer(authorize)
    try:
        with pytest.raises(PermissionError, match='owner_changed'):
            store._add_relation(edge(cid))
    finally:
        store.session_id = original
    assert seen == ['outer_native_COMMIT'] and counts(store) == (0, 0)
    assert not conn.in_transaction and store._transaction_quarantine is None


@pytest.mark.parametrize('path', ['private', 'shared'])
def test_native_authorizer_cancellation_primary_is_not_sqlite_error(store, path):
    cid = seed(store)
    conn, owned = graph._open_graph_writer_connection(store) if path == 'private' else (store._connect(), False)
    primary = KeyboardInterrupt('synthetic cancellation')
    def authorize(action, a, b, db, trigger):
        if action == sqlite3.SQLITE_TRANSACTION and a == 'COMMIT':
            raise primary
        return sqlite3.SQLITE_OK
    conn.set_authorizer(authorize)
    try:
        with pytest.raises(KeyboardInterrupt) as caught:
            with store._claim_transaction(conn):
                store._add_relation(edge(cid), conn=conn)
        assert caught.value is primary and counts(store) == (0, 0)
        assert not conn.in_transaction and store._claim_tx_graph_stage is None
        assert store._transaction_quarantine is None
    finally:
        if owned:
            graph._close_graph_writer_connection(conn, True)


def test_actual_cpython_callback_order_and_graph_late_callback_refusal(store):
    order = []
    with closing(sqlite3.connect(':memory:')) as probe:
        probe.execute('CREATE TABLE example(value)')
        probe.execute('INSERT INTO example VALUES(1)')
        def authorizer(action, a, b, db, trigger):
            if action == sqlite3.SQLITE_TRANSACTION and a == 'COMMIT':
                order.append('authorizer')
            return sqlite3.SQLITE_OK
        probe.set_authorizer(authorizer)
        probe.set_trace_callback(lambda sql: order.append('trace') if sql == 'COMMIT' else None)
        probe.commit()
    assert order == ['authorizer', 'trace']
    cid = seed(store)
    conn = store._connect()
    for configure, clear in ((lambda: conn.set_trace_callback(lambda sql: None), lambda: conn.set_trace_callback(None)),
                             (lambda: conn.set_progress_handler(lambda: 0, 1), lambda: conn.set_progress_handler(None, 0))):
        configure()
        try:
            with pytest.raises(RuntimeError, match='late_callback_unsupported'):
                store._add_relation(edge(cid))
        finally:
            clear()
        assert counts(store) == (0, 0) and not conn.in_transaction
        assert store._transaction_quarantine is None
    store._add_relation(edge(cid))
    assert counts(store) == (1, 2)
