"""Provider migration regressions on real owned SPI/SQL/Qdrant resources."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import threading
import contextvars
import pytest

_SPEC = importlib.util.spec_from_file_location(
    '_provider_migration_fixture', Path(__file__).with_name('ci_owned') / 'provider_migration_fixture.py')
_fixture = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _fixture
_SPEC.loader.exec_module(_fixture)
provider_migration_case = _fixture.provider_migration_case


def test_nous_openrouter_mixed_scope_baseline_explains_legacy_refusals(provider_migration_case):
    f = provider_migration_case
    assert f.old_hash != f.new_hash
    assert f.m._embedding_manifest()['provider'] == 'openrouter'
    assert f.m._qdrant_count(f.old_target) == 4
    assert f.alias() == f.old_target
    before = f.a._compare_search('migration receiver calibration', limit=5)
    assert before['fts_only'] and before['vector_only'] == []
    native = json.loads(f.a.handle_tool_call('memory_wiki_recall',
        {'query':'migration receiver calibration','mode':'auto','limit':5}))
    assert any(s['qdrant']['reason'] == 'manifest_target_mismatch'
               for s in native['retrieval_receipt']['searches']), native
    preview = f.public(current_scope_only=True, dry_run=True, limit=2)
    assert preview['status'] == 'refused'
    assert preview['error'] == 'scope_active_target_not_owned_or_compatible'
    assert f.foreign_text not in json.dumps(preview)
    sql = []
    conn = f.a._connect()
    conn.set_trace_callback(sql.append)
    try:
        legacy = f.public(force=True, limit=4)
    finally:
        conn.set_trace_callback(None)
    assert legacy['status'] == 'partial' and legacy['alias_switched'] is False
    assert legacy['failed'] == 2
    assert f.alias() == f.old_target and f.old_unchanged()
    assert set(legacy['failed_ids']) == {f.ids['b_private'], f.ids['b_chat']}
    assert f.embedding_posts and all(item['provider'] == 'openrouter' for item in f.embedding_posts)
    assert all(f.foreign_text not in item['input'] for item in f.embedding_posts)
    # The foreign branch could not find new-manifest registered vectors. No
    # widening of claim visibility or reading foreign SQL text is an acceptable fix.
    reads = [s for s in sql if 'SELECT normalized_claim FROM claims' in s]
    assert reads and all(f.ids['b_private'] not in s and f.ids['b_chat'] not in s for s in reads)


def test_provider_migration_two_owners_exact_coverage_and_vector_hybrid(provider_migration_case):
    f = provider_migration_case
    first = f.public(provider_migration=True)
    assert first['status'] == 'awaiting_authorized_owners' and first['alias_switched'] is False, first
    assert first['attempts'] == 2 and first['own_ready_count'] == 2
    target = first['collection']
    assert set(f.m._qdrant_claim_state(target)) == {f.ids['a_private'], f.ids['a_chat']}
    assert f.alias() == f.old_target and f.old_unchanged()
    assert len(f.embedding_posts) == 2
    assert all(f.foreign_text not in p['input'] for p in f.embedding_posts)
    # Actual native owner objects, not a model-supplied SID/bot/ACL override.
    result = f.a.migrate_embedding_index(owners=(f.a, f.b))
    assert result['status'] == 'completed' and result['alias_switched'] is True, result
    assert result['migration_id'] == first['migration_id'] and result['collection'] == target
    assert len(f.embedding_posts) == 4
    assert f.alias() == target and f.old_unchanged()
    assert set(f.m._qdrant_claim_state(target)) == set(f.ids.values())
    points = f.m._qdrant_req('POST', '/collections/'+target+'/points', {
        'ids':[f.m._qdrant_point_id(cid) for cid in f.ids.values()],
        'with_payload':True, 'with_vector':True})['result']
    assert len(points) == 4
    rows = {r['id']:dict(r) for r in f.a._connect().execute('SELECT * FROM claims')}
    for point in points:
        payload = point['payload']
        assert 'claim' not in payload and payload['manifest_hash'] == f.new_hash
        assert point['vector'] == _fixture.VECTOR_OPENROUTER
        assert point['vector'] != _fixture.VECTOR_NOUS  # Equal dimensions are not compatibility.
        source = rows[payload['claim_id']]
        for field in ('memory_revision','updated_at','visibility_scope','origin_bot_id',
                      'origin_session_id','origin_chat_hash','project_id'):
            assert payload[field] == source[field]
    stored = f.a._connect().execute('SELECT status,completed_revision FROM embedding_migrations').fetchone()
    assert stored['status'] == 'completed' and stored['completed_revision'] == result['validated_revision']
    after = f.a._compare_search('migration receiver calibration', limit=5)
    assert after['vector_only'] and after['hybrid'], after
    allowed = {f.ids['a_private'], f.ids['a_chat']}
    assert {r['id'] for r in after['vector_only']} <= allowed
    assert {r['id'] for r in after['hybrid']} <= allowed
    assert f.foreign_text not in json.dumps((first, result, after))
    assert not any(s['name'] == 'migrate_embedding_index' for s in f.a.get_tool_schemas())
    cached = json.loads((_fixture.SOURCE/'mcp-wrapper/tool_schemas.json').read_bytes())
    assert f.a.get_tool_schemas() == cached
    # The pre-existing exact-manifest foreign-vector copy stays healthy. Only
    # the current owner's two documents may be embedded by this legacy call.
    count = len(f.embedding_posts)
    compatible = f.public(force=True, limit=4)
    assert compatible['status'] == 'completed' and compatible['alias_switched'] is True, compatible
    assert len(f.embedding_posts) - count == 2
    assert all(f.foreign_text not in row['input'] for row in f.embedding_posts[count:])
    assert set(f.m._qdrant_claim_state(compatible['collection'])) == set(f.ids.values())
    assert f.old_unchanged()


def test_provider_migration_partial_restart_resume_same_job_without_reembedding(provider_migration_case):
    f = provider_migration_case
    first = f.public(provider_migration=True, limit=1)
    assert first['status'] == 'awaiting_authorized_owners' and first['attempts'] == 1, first
    assert f.alias() == f.old_target and len(f.embedding_posts) == 1
    # Dispose/reopen only these synthetic native provider connections. This is
    # not a Gateway restart or a change to the installed Hermes runtime.
    f.a.shutdown()
    f.b.shutdown()
    f.a = f.create_owner(f.m, 'a')
    f.b = f.create_owner(f.m, 'b')
    second = f.public(provider_migration=True, limit=1)
    assert second['migration_id'] == first['migration_id']
    assert second['collection'] == first['collection']
    assert second['attempts'] == 1 and second['own_ready_count'] == 2
    assert f.alias() == f.old_target and len(f.embedding_posts) == 2
    final = f.public('b', provider_migration=True)
    assert final['status'] == 'completed' and final['collection'] == first['collection'], final
    assert final['migration_id'] == first['migration_id']
    assert len(f.embedding_posts) == 4  # Successful first-point delivery was reused.
    assert f.a._connect().execute('SELECT COUNT(*) FROM embedding_migrations').fetchone()[0] == 1
    assert f.alias() == final['collection'] and f.old_unchanged()


def test_provider_migration_incomplete_remote_id_set_keeps_old_alias(provider_migration_case):
    f = provider_migration_case
    first = f.public(provider_migration=True)
    target = first['collection']
    seen = []
    def remove_before_validation(event):
        method, path, body = event
        if not seen and method == 'POST' and path == '/collections/'+target+'/points/scroll':
            seen.append(True)
            assert f.m._qdrant_delete_many([f.ids['a_private']], target)
    f.before_request = remove_before_validation
    result = f.public('b', provider_migration=True)
    assert seen == [True]
    assert result['status'] == 'refused' and result['alias_switched'] is False, result
    assert result['error'] == 'migration_target_state_unproven'
    assert f.alias() == f.old_target and f.old_unchanged()
    assert not any(method == 'POST' and path == '/collections/aliases'
                   for method,path,_ in f.qdrant_requests)


@pytest.mark.parametrize('drift', ['revision', 'acl'])
def test_provider_migration_sql_revision_drift_before_switch_keeps_old_alias(provider_migration_case, drift):
    f = provider_migration_case
    first = f.public(provider_migration=True)
    target = first['collection']
    seen = []
    before_revision = f.a._meta_int('memory_revision')
    def commit_source_change(event):
        method, path, body = event
        if not seen and method == 'POST' and path == '/collections/'+target+'/points/scroll':
            seen.append(True)
            assert not f.b._conn.in_transaction
            # Real independent SQLite writer, only in this owned fault fixture.
            writer = sqlite3.connect(str(f.a.db_path))
            try:
                if drift == 'revision':
                    writer.execute('UPDATE claims SET memory_revision=memory_revision+1 WHERE id=?',
                                   (f.ids['a_private'],))
                else:
                    writer.execute('UPDATE claims SET origin_session_id=? WHERE id=?',
                                   ('revoked-synthetic-session', f.ids['b_private']))
                writer.execute("UPDATE meta SET value=CAST(value AS INTEGER)+1 WHERE key='memory_revision'")
                writer.commit()
            finally:
                writer.close()
    f.before_request = commit_source_change
    result = f.public('b', provider_migration=True)
    assert seen == [True] and f.a._meta_int('memory_revision') == before_revision + 1
    assert result['status'] == 'refused' and result['alias_switched'] is False, result
    assert result['error'] == 'migration_source_changed'
    assert f.alias() == f.old_target and f.old_unchanged()


def test_provider_migration_no_forged_owners_or_old_manifest_write(provider_migration_case):
    f = provider_migration_case
    f.b.shutdown()
    host = f.a.migrate_embedding_index(owners=(f.a, f.b))
    assert host['status'] == 'refused' and host['error'] == 'migration_invalid_owner_participants', host
    assert f.embedding_posts == [] and f.qdrant_requests == []
    for args in (
        {'provider_migration':True,'owner_bot_id':'migration-owner-b'},
        {'provider_migration':True,'session_id':'migration-chat-b'},
        {'provider_migration':True,'owners':['migration-owner-b']},
        {'provider_migration':True,'current_scope_only':True},
        {'provider_migration':True,'dry_run':True},
        {'provider_migration':True,'force':True},
        {'provider_migration':'true'},
    ):
        result = f.public(**args)
        assert result['success'] is False and result['error'] == 'invalid_arguments'
    assert f.embedding_posts == [] and f.qdrant_requests == []
    cid = f.ids['a_private']
    row = f.a._connect().execute('SELECT * FROM claims WHERE id=?', (cid,)).fetchone()
    payload = f.m._qdrant_claim_payload(cid, row['normalized_claim'], row)
    assert not f.m._qdrant_upsert(cid, _fixture.VECTOR_OPENROUTER, payload, f.old_target)
    assert f.m._claim_collection_manifest_compatible(f.old_target, f.new_hash) is False
    # The actual old async writer must defer BEFORE reading/embedding any text,
    # not poison the rollback target with new-provider vectors.
    with f.a._claim_transaction(f.a._conn):
        f.m._outbox_enqueue('embed_and_upsert','claim',cid,{},conn=f.a._conn)
    work = f.m._outbox_process(1,db_path=str(f.a.db_path),worker_id='migration-fixture-worker')
    assert work['processed'] == 1 and work['fail'] == 1, work
    assert f.embedding_posts == []
    assert f.alias() == f.old_target and f.old_unchanged()


def test_provider_migration_uncertain_point_delivery_does_not_auto_retry_or_switch(provider_migration_case):
    f = provider_migration_case
    hits = []
    def fail_point_put(event):
        method, path, body = event
        if method == 'PUT' and path.endswith('/points'):
            hits.append(True)
            raise TimeoutError('synthetic pre-wire failure; treated conservatively as unknown')
    f.fail_request = fail_point_put
    first = f.public(provider_migration=True, limit=1)
    assert first['status'] == 'refused' and first['alias_switched'] is False, first
    assert hits == [True]
    assert f.alias() == f.old_target and f.old_unchanged()
    f.fail_request = None
    count = len(f.embedding_posts)
    second = f.public(provider_migration=True)
    assert second['status'] == 'refused' and second['error'] == 'migration_pending_write_outcome_unknown', second
    assert len(f.embedding_posts) == count and hits == [True]
    assert f.alias() == f.old_target and f.old_unchanged()


def test_provider_migration_outstanding_delete_cannot_race_alias_cutover(provider_migration_case):
    f = provider_migration_case
    first = f.public(provider_migration=True)
    assert first['status'] == 'awaiting_authorized_owners', first
    with f.a._claim_transaction(f.a._conn):
        f.m._outbox_enqueue('delete','claim',f.ids['a_private'],
            {'collection':first['collection'],'reason':'claim_content_rewritten'},conn=f.a._conn)
    result = f.public('b',provider_migration=True)
    assert result['status'] == 'refused', result
    assert result['error'] == 'migration_claim_deletes_not_quiescent' and result['alias_switched'] is False
    assert f.alias() == f.old_target and f.old_unchanged()
    assert f.a._conn.execute("SELECT COUNT(*) FROM index_outbox WHERE operation='delete' AND status='pending'").fetchone()[0] > 0


def test_provider_migration_keeps_canonical_episode_upsert_separate(provider_migration_case):
    # Low-level regression for the OTHER caller of the shared HTTP upsert.
    # Real Qdrant, canonical episode payload, no claim/episode authority mock;
    # this is not an end-to-end episode capture/retention qualification.
    f = provider_migration_case
    target = f.m._episodic_collection_name()
    eid = 'e_synthetic_migration_namespace'
    payload = f.m._qdrant_episode_payload(eid, 'Synthetic episode namespace control.', {
        'role':'user','visibility_scope':'chat','owner_bot_id':f.a.bot_id,
        'owner_chat_hash':f.a._chat_hash(f.a.session_id),'collection':target,
        'created_at':f.m.now(),'expires_at':f.m.now()+3600})
    assert payload['object_type'] == 'episode'
    assert f.m._qdrant_upsert(eid, _fixture.VECTOR_OPENROUTER, payload, target)
    response = f.m._qdrant_req('POST','/collections/'+target+'/points',{
        'ids':[f.m._qdrant_point_id(eid)],'with_payload':True,'with_vector':False})
    assert response['result'][0]['payload'] == payload
    assert f.alias() == f.old_target and f.old_unchanged()


@pytest.mark.parametrize('phase', ['after-selection', 'after-intent'])
def test_provider_migration_session_switch_before_hydration_has_no_raw_read(provider_migration_case, phase):
    f = provider_migration_case
    # Import the actual coordinator using its real package, not a stand-in.
    module = importlib.import_module(f.m.__name__ + '.provider_migration')
    switched, raw_after = [], []
    def switch():
        if not switched:
            f.a.on_session_switch('migration-chat-b')
            switched.append(True)
    def trace(sql):
        if switched and 'SELECT * FROM claims' in sql:
            raw_after.append(sql)
        if phase == 'after-intent' and 'INSERT INTO embedding_migration_points' in sql:
            switch()
    original = module._own_rows
    def select(*args):
        rows = original(*args)
        if phase == 'after-selection':
            switch()
        return rows
    f.mp.setattr(module, '_own_rows', select)
    f.a._conn.set_trace_callback(trace)
    try:
        result = f.public(provider_migration=True)
    finally:
        f.a._conn.set_trace_callback(None)
    assert switched == [True] and raw_after == []
    assert result['status'] == 'refused' and result['alias_switched'] is False, result
    assert result['error'] == 'migration_owner_or_route_changed'
    assert f.embedding_posts == []
    assert not any(method == 'PUT' and path.endswith('/points') for method,path,_ in f.qdrant_requests)
    assert f.alias() == f.old_target and f.old_unchanged()


def _migration_queued_delete(f, first):
    cid, target = f.ids['a_private'], first['collection']
    with f.a._claim_transaction(f.a._conn):
        hint = f.m._record_claim_vector_target(f.a._conn, cid, collection=target,
            manifest_hash=f.new_hash, status='active')
        f.m._outbox_enqueue('delete','claim',cid,
            {**hint,'reason':'claim_content_rewritten'}, conn=f.a._conn)
    blocked = f.public('b',provider_migration=True)
    assert blocked['error'] == 'migration_claim_deletes_not_quiescent', blocked
    return cid, target


def _migration_retry_own_point(f, first, cid):
    # Synthetic metadata fault/recovery fixture only; not an authority override.
    # The next real public contribution must re-admit/re-embed under owner A.
    with f.a._claim_transaction(f.a._conn):
        f.a._conn.execute('DELETE FROM embedding_migration_points WHERE migration_id=? AND claim_id=?',
                         (first['migration_id'],cid))


def test_provider_migration_reclaimed_delete_local_row_cannot_send_after_ack(provider_migration_case):
    f = provider_migration_case
    first = f.public(provider_migration=True)
    cid, target = _migration_queued_delete(f, first)
    module = importlib.import_module(f.m.__name__ + '.provider_migration')
    original = module.guarded_claim_delete
    parked, release = threading.Event(), threading.Event()
    old_result, calls, writer_blocked = [], [], []
    def paused(*args, **kwargs):
        if kwargs.get('outbox_lease', ('',''))[1] == 'stale-worker-a':
            parked.set()
            assert release.wait(20), 'test must release its owned stale worker'
            result = original(*args, **kwargs)
            calls.append(result)
            return result
        return original(*args, **kwargs)
    f.mp.setattr(module,'guarded_claim_delete',paused)
    def observe_wire(event):
        method,path,_ = event
        if method == 'POST' and path.endswith('/points/delete'):
            contender = sqlite3.connect(str(f.a.db_path), timeout=0)
            error = None
            try:
                try:
                    contender.execute('BEGIN IMMEDIATE')
                except sqlite3.OperationalError as exc:
                    error = exc
                assert error is not None, 'actual DELETE must hold cutover writer exclusion'
                writer_blocked.append(True)
            finally:
                contender.close()
    f.before_request = observe_wire
    context = contextvars.copy_context()
    def run_old():
        old_result.append(f.m._outbox_process(1,db_path=str(f.a.db_path),worker_id='stale-worker-a'))
    worker = threading.Thread(target=lambda:context.run(run_old),name='migration-owned-stale-delete')
    worker.start()
    try:
        assert parked.wait(20), 'old worker must retain actual claimed row before effect admission'
        with f.a._claim_transaction(f.a._conn):
            f.a._conn.execute("UPDATE index_outbox SET lease_until=0 WHERE worker_id='stale-worker-a'")
        successor = f.m._outbox_process(1,db_path=str(f.a.db_path),worker_id='successor-worker-b')
        assert successor['ok'] == 1 and successor['fail'] == 0, successor
        assert f.a._conn.execute('SELECT COUNT(*) FROM index_outbox WHERE object_id=?',(cid,)).fetchone()[0] == 0
        _migration_retry_own_point(f,first,cid)
        completed = f.public(provider_migration=True)
        assert completed['status'] == 'completed', completed
        sends = sum(method == 'POST' and path.endswith('/points/delete') for method,path,_ in f.qdrant_requests)
    finally:
        release.set()
        worker.join(20)
        assert not worker.is_alive(), 'owned stale worker must finish before fixture disposal'
    assert old_result and calls == ['stale'] and writer_blocked
    assert sum(method == 'POST' and path.endswith('/points/delete') for method,path,_ in f.qdrant_requests) == sends
    assert set(f.m._qdrant_claim_state(target)) == set(f.ids.values())
    assert f.alias() == target and f.old_unchanged()


def test_provider_migration_unknown_delete_survives_successor_queue_ack(provider_migration_case):
    f = provider_migration_case
    first = f.public(provider_migration=True)
    cid, target = _migration_queued_delete(f, first)
    lost = []
    def lose_response(event):
        method,path,_ = event
        if not lost and method == 'POST' and path.endswith('/points/delete'):
            lost.append(True)
            raise TimeoutError('synthetic loss AFTER real Qdrant DELETE response')
    f.after_request = lose_response
    failed = f.m._outbox_process(1,db_path=str(f.a.db_path),worker_id='unknown-delete-a')
    assert lost == [True] and failed['fail'] == 1, failed
    f.after_request = None
    with f.a._claim_transaction(f.a._conn):
        f.a._conn.execute("UPDATE index_outbox SET status='pending',next_retry_at=0 WHERE object_id=?",(cid,))
    successor = f.m._outbox_process(1,db_path=str(f.a.db_path),worker_id='unknown-delete-b')
    assert successor['ok'] == 1, successor
    assert f.a._conn.execute('SELECT COUNT(*) FROM index_outbox WHERE object_id=?',(cid,)).fetchone()[0] == 0
    assert f.a._conn.execute("SELECT COUNT(*) FROM claim_vector_delete_effects WHERE status='unknown'").fetchone()[0] == 1
    _migration_retry_own_point(f,first,cid)
    result = f.public(provider_migration=True)
    assert result['status'] == 'refused' and result['error'] == 'migration_claim_deletes_not_quiescent', result
    assert result['alias_switched'] is False and f.alias() == f.old_target and f.old_unchanged()


def test_provider_migration_alias_response_loss_resume_stays_unknown(provider_migration_case):
    f = provider_migration_case
    first = f.public(provider_migration=True)
    lost = []
    def lose_response(event):
        method,path,_ = event
        if method == 'POST' and path == '/collections/aliases':
            lost.append(True)
            raise TimeoutError('synthetic loss AFTER actual atomic alias operation')
    f.after_request = lose_response
    before = f.public('b',provider_migration=True)
    assert before['error'] == 'migration_alias_outcome_unknown' and before['alias_switched'] is None, before
    assert f.alias() == first['collection'] and lost == [True]
    f.after_request = None
    count = len(f.embedding_posts)
    posts = sum(method == 'POST' and path == '/collections/aliases' for method,path,_ in f.qdrant_requests)
    after = f.public('b',provider_migration=True)
    assert after['error'] == 'migration_alias_outcome_unknown' and after['alias_switched'] is None, after
    assert after['alias_outcome'] == 'unknown'
    assert len(f.embedding_posts) == count
    assert sum(method == 'POST' and path == '/collections/aliases' for method,path,_ in f.qdrant_requests) == posts
    assert f.old_unchanged()
