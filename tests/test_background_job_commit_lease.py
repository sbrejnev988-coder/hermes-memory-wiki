"""R2 event-job native COMMIT admission on genuine file-backed SQLite.

SOURCE standalone fallback is intentional; SDK/host/network are not qualified.
Only the extraction reply and deterministic scheduler/clock are synthetic. The
queue producer/lease/renew/finish, quality/ACL gates, owner and native SQL are real.
"""
from __future__ import annotations

from contextlib import closing
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import time

import pytest


_SPEC = importlib.util.spec_from_file_location(
    'event_job_atomicity_peer', Path(__file__).with_name('test_code_graph_idempotency_atomicity.py'))
peer = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = peer
_SPEC.loader.exec_module(peer)
KINDS = ['consolidate_observations', 'extract_session_events']
TEXT = ('User prefers the violet telescope at Aurora Observatory for detailed nightly '
        'observations, with a durable local archive and verified daily integrity checks.')


def durable(path):
    """Independent connection: the entire DB write-set, including FTS shadows."""
    with closing(sqlite3.connect(str(path))) as reader:
        tables = [r[0] for r in reader.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        return {name: sorted(reader.execute('SELECT * FROM "' + name.replace('"', '""') + '"').fetchall(), key=repr)
                for name in tables}


@pytest.fixture
def case(request, tmp_path_factory, monkeypatch):
    token = hashlib.sha256(request.node.nodeid.encode()).hexdigest()[:16]
    root = tmp_path_factory.mktemp('code-identity-' + token, numbered=False)
    home = root / 'home'
    home.mkdir()
    settings = {
        'HERMES_HOME': str(home), 'MEMORY_WIKI_BACKGROUND_JOBS_ENABLED': '0',
        'MEMORY_WIKI_EVENT_LEDGER_ENABLED': '1', 'MEMORY_WIKI_OBSERVATIONS_ENABLED': '1',
        'MEMORY_WIKI_BACKGROUND_LEASE_SECONDS': '30', 'MEMORY_WIKI_EXTRACT_ENABLED': '0',
        'MEMORY_WIKI_GRAPH_EXTRACT_ENABLED': '0', 'MEMORY_WIKI_GRAPH_AUTO_EXTRACT': '0',
        'MEMORY_WIKI_EPISODIC_ENABLED': '0', 'MEMORY_WIKI_ENV_META_SYNC': '0',
        'MEMORY_WIKI_DOCUMENT_AUTO_SCAN_CACHE': '0', 'MEMORY_WIKI_SEMANTIC': '0',
        'MEMORY_WIKI_EMBED_PROVIDER': 'stub', 'MEMORY_WIKI_EMBED_MODEL': 'hash-ngram-8',
        'MEMORY_WIKI_EMBED_DIMENSIONS': '8', 'MEMORY_WIKI_VECTOR_SIZE': '8',
        'MEMORY_WIKI_RERANK_ENABLED': '0', 'MEMORY_WIKI_LLM_PACK': '0',
    }
    for key, value in settings.items():
        monkeypatch.setenv(key, value)
    m, p = peer.load_provider('event_job_' + token, home, monkeypatch)
    p.project_scope = ''
    j = m._background_jobs
    assert p._background_worker is None and p._transaction_quarantine is None
    assert p._runtime_identity()['profile_ready'] is True
    assert m.memory_gate_decision(TEXT, 'preferences', 'extractor:heuristic')['action'] == 'accept'
    stamp = [float(int(time.time()))]
    monkeypatch.setattr(j.time, 'time', lambda: stamp[0])
    event = m._memory_events.capture_event(p, m, TEXT, event_type='dialogue_turn', role='user',
                                         scope='chat', session_id=p.session_id)
    assert event
    store = j.JobStore(p.db_path, j.profile_key(p), j.owner_key(p))
    workers, returns, schedule = [], [], []
    state = dict(m=m, p=p, j=j, root=root, store=store, event=event, clock=stamp,
                 workers=workers, returns=returns, schedule=schedule, configure=None)
    actual_factory = j._worker_provider
    old_profile = sys.getprofile()
    assert old_profile is None

    def observe(frame, phase, value):
        if phase == 'return' and frame.f_code is actual_factory.__code__:
            workers.append(value)
            if state['configure'] is not None:
                state['configure'](value)

    # Same authored callback shape as test_background_jobs.py. No gate override.
    def extraction(exchanges, session_id, *, add_claim_callback, **kwargs):
        assert exchanges and exchanges[0]['content'] == TEXT
        try:
            cid = add_claim_callback(TEXT, topic='preferences', evidence=json.dumps({
                'schema': 'memory-wiki-extraction-evidence-v1', 'session_id': session_id,
                'speaker': 'user', 'message_index': 0, 'evidence_quote': TEXT,
                'extractor': 'extractor:heuristic'}), source='extractor:heuristic',
                confidence=.85, salience=.8, visibility_scope='chat', event_at=0, event_timezone='UTC')
        except Exception as exc:
            # The real extractor also catches Exception. _run_job must deliver
            # the exact retained primary, not flatten it to provider/empty ID.
            returns.append(('error', type(exc).__name__))
            return {'persisted_ids': [], 'errors': [type(exc).__name__], 'error': ''}
        returns.append(('id', cid))
        return {'persisted_ids': [cid] if cid else [], 'errors': [], 'error': ''}

    monkeypatch.setattr(m, 'extract_session_claims', extraction)
    sys.setprofile(observe)
    try:
        yield state
    finally:
        sys.setprofile(old_profile)
        # These are fixture-owned emergency closes AFTER UNKNOWN assertions;
        # they never clear a production owner or constitute recovery proof.
        handles = {w._conn for w in workers if w._conn is not None}
        handles.update(w._owned_conn for w in workers if w._owned_conn is not None)
        handles.update({p._conn, p._owned_conn} - {None})
        for conn in handles:
            try:
                sqlite3.Connection.set_authorizer(conn, None)
                sqlite3.Connection.set_trace_callback(conn, None)
                sqlite3.Connection.set_progress_handler(conn, None, 0)
                sqlite3.Connection.close(conn)
            except sqlite3.ProgrammingError:
                pass
        (root / 'witness.json').write_text(json.dumps({
            'scheduler': schedule, 'callback_results': returns,
            'boundary': 'SOURCE genuine standalone/file-backed SQLite; synthetic extraction and scheduler',
            'emergency_fixture_close_is_not_production_recovery': True,
        }, sort_keys=True, indent=2) + '\n', encoding='utf-8')


def lease(c, kind, worker='a' * 32):
    assert c['j'].enqueue_event(c['p'], kind, c['event'])
    job = c['store'].lease(worker)
    assert job and job['job_type'] == kind and c['store'].owns(job, worker)
    return job


def run(c, job):
    worker_id = job['lease_owner'].split(':')[0]
    return c['j']._run_job(c['p'], c['m'], job,
        lease_valid=lambda: c['store'].owns(job, worker_id),
        lease_valid_in_transaction=lambda conn: c['store'].owns(job, worker_id, connection=conn))


def effect(c, kind):
    rows = durable(c['p'].db_path)
    if kind == 'consolidate_observations':
        assert len(rows['memory_observations']) == 1
        assert len(rows['memory_observation_versions']) == 1
        assert len(rows['memory_observation_events']) == 1
        assert len(rows['memory_observation_event_decisions']) == 1
    else:
        assert len(rows['claims']) == 1 and rows['evidence']
        assert c['returns'][-1][0] == 'id' and c['returns'][-1][1]
    return rows


@pytest.mark.parametrize('kind', KINDS)
def test_expiry_after_last_python_check_before_native_commit(case, kind):
    c = case
    job = lease(c, kind)
    before = durable(c['p'].db_path)

    def configure(actor):
        conn = actor._connect()
        initial = conn.total_changes
        def authorize(action, a, b, database, source):
            if action == sqlite3.SQLITE_TRANSACTION and a == 'COMMIT' and not c['schedule']:
                assert conn.total_changes > initial, 'safety seam needs actual pending writes'
                c['schedule'].append('after_last_python_check_before_native_COMMIT')
                c['clock'][0] = float(job['lease_expires_at'])
            return sqlite3.SQLITE_OK
        conn.set_authorizer(authorize)
    c['configure'] = configure
    caught = None
    try:
        run(c, job)
    except TimeoutError as exc:
        caught = exc
    after = durable(c['p'].db_path)
    assert c['schedule'] == ['after_last_python_check_before_native_COMMIT']
    assert after == before, 'R2-TTL-1 expired event job committed its canonical write-set'
    assert isinstance(caught, TimeoutError)
    assert not c['store'].owns(job, job['lease_owner'].split(':')[0])
    assert c['p']._transaction_quarantine is None
    assert not any(row[0] == 'id' and row[1] for row in c['returns'])


@pytest.mark.parametrize('kind', KINDS)
def test_current_lease_healthy_native_and_postadmission_fts(case, kind):
    c = case
    job = lease(c, kind)
    def configure(actor):
        conn = actor._connect()
        admitted = [False]
        def authorize(action, a, b, database, source):
            if action == sqlite3.SQLITE_TRANSACTION and a == 'COMMIT':
                admitted[0] = True
                c['schedule'].append('native_COMMIT_current')
            elif admitted[0]:
                # A later FTS synchronization is not a second expiry admission.
                c['clock'][0] = float(job['lease_expires_at'])
                c['schedule'].append('post_COMMIT_callback')
                admitted[0] = False
            return sqlite3.SQLITE_OK
        conn.set_authorizer(authorize)
    c['configure'] = configure
    assert run(c, job) == ''
    effect(c, kind)
    assert 'native_COMMIT_current' in c['schedule']
    assert c['p']._transaction_quarantine is None
    assert c['workers'][-1]._claim_tx_event_job_stage is None


@pytest.mark.parametrize('kind', KINDS)
def test_renewed_current_token_and_coalesced_generation_are_lawful(case, kind):
    c = case
    job = lease(c, kind)
    frozen = dict(job)
    worker_id = job['lease_owner'].split(':')[0]
    c['clock'][0] += 20
    assert c['store'].renew(job, worker_id)
    assert c['j'].enqueue_event(c['p'], kind, c['event']) == job['job_id']
    c['clock'][0] = float(job['lease_expires_at'] + 1)
    assert c['store'].owns(job, worker_id) and job == frozen
    assert run(c, job) == ''
    effect(c, kind)
    assert c['store'].finish(job, worker_id)
    with closing(sqlite3.connect(c['p'].db_path)) as reader:
        status, generation, leased_generation = reader.execute(
            'SELECT status,generation,lease_generation FROM memory_jobs WHERE job_id=?', (job['job_id'],)).fetchone()
    assert status == 'pending' and generation > leased_generation == job['lease_generation']
    assert c['p']._transaction_quarantine is None


@pytest.mark.parametrize('kind', KINDS)
@pytest.mark.parametrize('same_worker', [False, True])
def test_committed_reassignment_before_begin_refuses_exact_old_suffix(case, kind, same_worker):
    c = case
    job = lease(c, kind)
    replacement, after_reassignment = [], []
    def configure(actor):
        c['configure'] = None
        c['clock'][0] = float(job['lease_expires_at'])
        new = c['store'].lease('a' * 32 if same_worker else 'b' * 32)
        assert new and new['job_id'] == job['job_id'] and new['lease_owner'] != job['lease_owner']
        replacement.append(new)
        after_reassignment.append(durable(c['p'].db_path))
        c['schedule'].append('committed_new_token_before_writer_BEGIN')
    c['configure'] = configure
    try:
        run(c, job)
    except TimeoutError:
        pass
    assert replacement and durable(c['p'].db_path) == after_reassignment[0]
    assert not c['store'].owns(job, 'a' * 32)
    assert run(c, replacement[0]) == ''
    effect(c, kind)
    assert c['p']._transaction_quarantine is None


@pytest.mark.parametrize('mode', ['healthy', 'owner_first', 'owner_last', 'later_callback'])
def test_join_retains_all_original_obligations_through_later_owner(case, monkeypatch, mode):
    c = case
    first = lease(c, KINDS[0])
    c['clock'][0] += 10
    second = lease(c, KINDS[1], 'b' * 32)
    if mode == 'owner_last':
        c['clock'][0] += 10
        assert c['store'].renew(first, 'a' * 32)
    before = durable(c['p'].db_path)
    p, conn = c['p'], c['p']._connect()
    tail = [False]
    def second_check(connection):
        valid = c['store'].owns(second, 'b' * 32, connection=connection)
        if tail[0] and mode == 'later_callback':
            c['clock'][0] = float(first['lease_expires_at'])
            c['schedule'].append('later_join_callback_expires_first_original')
        return valid
    a = c['j']._event_job_obligation(p, first, lambda: c['store'].owns(first, 'a' * 32),
                                    lambda connection: c['store'].owns(first, 'a' * 32, connection=connection))
    b = c['j']._event_job_obligation(p, second, None, second_check)
    original_tail = p._claim_journal_pending_commit
    def owner_tail(connection):
        image = original_tail(connection)
        tail[0] = True
        if mode in {'owner_first', 'owner_last'}:
            c['clock'][0] = float((first if mode == 'owner_first' else second)['lease_expires_at'])
            c['schedule'].append('late_outer_owner_expires_original')
        return image
    monkeypatch.setattr(p, '_claim_journal_pending_commit', owner_tail)
    stages = []
    caught = None
    try:
        with p._claim_transaction(conn):
            c['m']._memory_observations.consolidate_events(p, c['m'], scope='chat',
                session_id=p.session_id, _event_job=a)
            with p._claim_transaction(conn, join=True, _event_job=b):
                p._audit('event_join', conn=conn)
            with p._claim_transaction(conn, join=True, _event_job=a):
                stages.append(p._claim_tx_event_job_stage)
                assert stages[0][2] == [a, b, a]
                assert all(x is y for x, y in zip(stages[0][2], [a, b, a]))
    except TimeoutError as exc:
        caught = exc
    assert tail[0]
    if mode == 'healthy':
        assert caught is None
        effect(c, KINDS[0])
    else:
        assert isinstance(caught, TimeoutError) and durable(p.db_path) == before
    assert stages and stages[0][2] == [] and p._claim_tx_event_job_stage is None
    assert p._transaction_quarantine is None
    monkeypatch.setattr(p, '_claim_journal_pending_commit', original_tail)
    with p._claim_transaction(conn):
        assert p._claim_tx_event_job_stage is not stages[0]
        assert p._claim_tx_event_job_stage[2] == []
        p._audit('clean_new_owner_stage', conn=conn)


@pytest.mark.parametrize('kind', KINDS)
@pytest.mark.parametrize('mode', ['cancel', 'deny', 'unknown'])
def test_primary_known_rollback_and_genuine_unknown_worker_retention(case, kind, mode):
    c = case
    job = lease(c, kind)
    before = durable(c['p'].db_path)
    primary = KeyboardInterrupt('synthetic cancellation') if mode == 'cancel' else ValueError('synthetic primary')
    stage = []
    def configure(actor):
        conn = actor._connect()
        def authorize(action, a, b, database, source):
            if action == sqlite3.SQLITE_TRANSACTION:
                if a == 'COMMIT':
                    stage.append(actor._claim_tx_event_job_stage)
                    if mode == 'deny':
                        return sqlite3.SQLITE_DENY
                    raise primary
                if a == 'ROLLBACK' and mode == 'unknown':
                    return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK
        conn.set_authorizer(authorize)
    c['configure'] = configure
    expected = sqlite3.DatabaseError if mode == 'deny' else type(primary)
    with pytest.raises(expected) as caught:
        run(c, job)
    assert stage and durable(c['p'].db_path) == before
    if mode != 'deny':
        assert caught.value is primary
    actor = c['workers'][-1]
    if mode == 'unknown':
        assert c['p']._graph_effect_quarantined_worker is actor
        assert actor._transaction_quarantine is actor._claim_tx_connection is actor._conn is actor._owned_conn
        assert actor._transaction_primary is caught.value is c['p']._transaction_primary
        assert actor._claim_tx_event_job_stage is stage[0] and len(stage[0][2]) == 1
        assert actor._conn.in_transaction and c['p']._transaction_quarantine is actor._conn
        assert any('outcome=UNKNOWN' in note for note in caught.value.__notes__)
        with pytest.raises(RuntimeError, match='not_ready'):
            actor._connect()
        with pytest.raises(RuntimeError, match='not_ready'):
            c['p']._connect()
        assert not actor._release_connection_for_retry(caught.value)
        assert not c['p']._release_connection_for_retry(caught.value)
        with pytest.raises(type(primary)) as retried:
            c['j'].run_once(c['p'], c['m'])
        assert retried.value is caught.value
        assert not any(row[0] == 'id' and row[1] for row in c['returns'])
    else:
        assert stage[0][2] == [] and actor._claim_tx_event_job_stage is None
        assert c['p']._transaction_quarantine is None
        c['configure'] = None
        assert run(c, job) == ''
        effect(c, kind)


@pytest.mark.parametrize('kind', KINDS)
def test_shortcuts_reentry_and_late_callbacks_do_not_bypass_owner(case, kind):
    c = case
    job = lease(c, kind)
    p, conn = c['p'], c['p']._connect()
    admission = c['j']._event_job_obligation(p, job, None, None)
    cursor = conn.cursor()
    with p._claim_transaction(conn, _event_job=admission):
        p._audit('protected_event_owner', conn=conn)
        for shortcut in (lambda: conn.execute('COMMIT'), lambda: cursor.execute('END'),
                         lambda: sqlite3.Connection.commit(conn)):
            with pytest.raises(sqlite3.DatabaseError):
                shortcut()
            assert conn.in_transaction
    # Native context exit tries ROLLBACK after its denied implicit COMMIT.
    # That confirmed rollback is safe, but cannot leave a pending TX to join.
    before_context = durable(p.db_path)
    with pytest.raises(sqlite3.DatabaseError):
        with p._claim_transaction(conn, _event_job=admission):
            p._audit('context_exit_denied_commit', conn=conn)
            sqlite3.Connection.__exit__(conn, None, None, None)
    assert durable(p.db_path) == before_context and not conn.in_transaction
    assert p._claim_tx_event_job_stage is None and p._transaction_quarantine is None
    callbacks = []
    def authorize(action, a, b, database, source):
        if action == sqlite3.SQLITE_TRANSACTION and a == 'COMMIT':
            callbacks.append('native')
            with pytest.raises(sqlite3.DatabaseError):
                conn.execute('COMMIT')
            for operation in (conn.commit, conn.close, lambda: conn.set_authorizer(None),
                              lambda: conn.set_trace_callback(None), lambda: conn.set_progress_handler(None, 0)):
                with pytest.raises(RuntimeError, match='in_flight'):
                    operation()
        return sqlite3.SQLITE_OK
    conn.set_authorizer(authorize)
    with p._claim_transaction(conn, _event_job=admission):
        p._audit('event_authorizer_reentry', conn=conn)
    assert callbacks == ['native']
    conn.set_authorizer(None)
    for configure, clear in (
        (lambda: conn.set_trace_callback(lambda sql: callbacks.append('trace')), lambda: conn.set_trace_callback(None)),
        (lambda: conn.set_progress_handler(lambda: callbacks.append('progress') or 0, 1), lambda: conn.set_progress_handler(None, 0)),
    ):
        configure()
        try:
            with pytest.raises(RuntimeError, match='late_callback_unsupported'):
                with p._claim_transaction(conn, _event_job=admission):
                    p._audit('late_critical_callback', conn=conn)
            # The same configured callbacks remain supported for ordinary work.
            with p._claim_transaction(conn):
                p._audit('ordinary_callback_positive', conn=conn)
        finally:
            clear()
    assert 'trace' in callbacks and 'progress' in callbacks and p._transaction_quarantine is None


def test_current_graph_apply_and_ordinary_noncritical_control(case, monkeypatch):
    c = case
    p, m = c['p'], c['m']
    cid = p._add_claim(TEXT, 'preferences', json.dumps({
        'schema': 'memory-wiki-extraction-evidence-v1', 'session_id': p.session_id,
        'speaker': 'user', 'message_index': 0, 'evidence_quote': TEXT,
        'extractor': 'extractor:heuristic'}), 'extractor:heuristic', .85, .8, visibility_scope='chat')
    assert cid and not str(cid).startswith('rq_')
    assert c['j'].enqueue_claim(p, cid)
    job = c['store'].lease('a' * 32)
    assert job and job['job_type'] == 'enrich_claim_graph'
    def proposal(actor, ids):
        # Synthetic remote proposal only; actual graph owner/APPLY and lease are real.
        actor._add_relation({'subject': 'Aurora Observatory', 'predicate': 'owns',
                             'object': 'violet telescope', 'source_claim_id': ids[0], 'confidence': .9})
        return {'errors': 0, 'deadline_exhausted': 0}
    monkeypatch.setattr(type(p), '_auto_graph_enrich_extracted_claims', proposal)
    assert run(c, job) == ''
    rows = durable(p.db_path)
    assert len(rows['relations']) == 1 and len(rows['entities']) == 2
    conn = p._connect()
    seen = []
    conn.set_authorizer(lambda action, a, b, db, source: seen.append(a) or sqlite3.SQLITE_OK)
    conn.set_trace_callback(lambda sql: None)
    try:
        with p._claim_transaction(conn):
            p._audit('ordinary_after_graph_and_event_fixture', conn=conn)
    finally:
        conn.set_trace_callback(None)
        conn.set_authorizer(None)
    assert 'COMMIT' in seen and p._transaction_quarantine is None
