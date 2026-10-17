"""DL1: genuine shared document support must retire independently of order.

Direct SOURCE/SPI + file SQLite, not host erasure or remote vector delivery.
The shipped fixture owns all ENV/profile scopes and the real plain extractor.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys

import pytest

_SPEC = importlib.util.spec_from_file_location('document_shared_retirement_fixture',
    Path(__file__).with_name('ci_owned') / 'derived_claim_materialization_fixture.py')
fx = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = fx
_SPEC.loader.exec_module(fx)
derived_case = fx.derived_case


def whole_state(c):
    """Typed independent entire durable write-set; also covers BLOB tables."""
    reader = sqlite3.connect(str(c.path))
    try:
        tables = [r[0] for r in reader.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        images = {}
        for table in tables:
            rows = reader.execute('SELECT * FROM "' + table.replace('"', '""') + '"').fetchall()
            typed = [[(type(value).__name__, value.hex() if type(value) is bytes else value)
                      for value in row] for row in rows]
            images[table] = dict(count=len(rows), sha256=hashlib.sha256(
                json.dumps(sorted(typed, key=repr), separators=(',', ':')).encode()).hexdigest())
    finally:
        reader.close()
    ordinal = getattr(c, '_shared_whole_reads', 0) + 1
    c._shared_whole_reads = ordinal
    raw = (json.dumps(images, sort_keys=True, indent=2) + '\n').encode()
    path = c.dir / ('durable-write-set-' + str(ordinal) + '.json')
    path.write_bytes(raw)
    c._emit(dict(event='shared_independent_whole_write_set', path=path.name,
                 tables=len(images), sha256=hashlib.sha256(raw).hexdigest()))
    return images


def observe(c, label):
    """Capture cause BEFORE assertions, including all original support rows."""
    images = whole_state(c)
    reader = sqlite3.connect(str(c.path))
    reader.row_factory = sqlite3.Row
    try:
        queries = {
            'sources': 'SELECT source_id,revision_id,scope_id,repository_id,active,status FROM document_sources ORDER BY source_id',
            'revisions': 'SELECT revision_id,source_id,status FROM document_revisions ORDER BY revision_id',
            'chunks': 'SELECT chunk_id,source_id,revision_id,content_hash,scope_id,repository_id,active,embedding_claim_id FROM document_chunks ORDER BY chunk_id',
            'claims': 'SELECT id,topic,status,source,evidence,visibility_scope,project_id,memory_revision FROM claims ORDER BY id',
            'evidence': 'SELECT id,claim_id,kind,text,source FROM evidence ORDER BY id',
            'outbox': 'SELECT id,operation,object_type,object_id,status,payload_json FROM index_outbox ORDER BY id',
            'targets': 'SELECT * FROM claim_vector_targets ORDER BY claim_id,collection',
            'mutations': 'SELECT id,operation,target_table,target_id,reversible FROM memory_mutations ORDER BY id',
            'claim_fts': 'SELECT id FROM claims_fts ORDER BY id',
            'chunk_fts': 'SELECT source_id,chunk_id FROM document_chunks_fts ORDER BY source_id,chunk_id',
            'unit_fts': 'SELECT source_id,unit_id FROM document_units_fts ORDER BY source_id,unit_id',
            'revision_meta': "SELECT key,value FROM meta WHERE key IN ('memory_revision','cache_state_revision','semantic_enabled') ORDER BY key",
        }
        state = {name: [dict(row) for row in reader.execute(sql)] for name, sql in queries.items()}
    finally:
        reader.close()
    path = c.dir / ('coupled-' + str(c._shared_whole_reads) + '.json')
    raw = (json.dumps(state, sort_keys=True, indent=2) + '\n').encode()
    path.write_bytes(raw)
    c._emit(dict(event='DL1_coupled_state', label=label, path=path.name,
                 sha256=hashlib.sha256(raw).hexdigest(),
                 claim_ids=[r['id'] for r in state['claims']],
                 active_links=sum(bool(r['active'] and r['embedding_claim_id']) for r in state['chunks'])))
    return state, images


def evidence_for(c, chunk, *, revision=None, content=None):
    return ('document_chunk_ref:' + c.doc._evidence_ref(
        chunk['source_id'] + '\0' + (content or chunk['content_hash']))
        + '; source_ref:' + c.doc._evidence_ref(chunk['source_id'])
        + '; revision_ref:' + c.doc._evidence_ref(revision or chunk['revision_id']))


def setup_shared(c):
    # Real opt-in/outbox SQL, no worker starts: the fixture's recovery flag owns
    # that exclusion. A write_pending target is only possible intent, not a
    # fabricated remote vector or successful transport acknowledgement.
    c.m.SEMANTIC_ENABLED = True
    with c.p._claim_transaction(c.conn):
        c.conn.execute("UPDATE meta SET value='1' WHERE key='semantic_enabled'")
    a, b = c.ingest('first/shared'), c.ingest('second/shared')
    results = [c.embed(a['source_id']), c.embed(b['source_id'])]
    state, _ = observe(c, 'genuine-two-materializations-before-setup-oracle')
    assert a['source_id'] != b['source_id']
    assert all(r['created'] == 1 and r['failed'] == 0 for r in results), results
    assert len(state['claims']) == 1 and len(state['chunks']) == 2
    cid = state['claims'][0]['id']
    assert all(r['active'] == 1 and r['embedding_claim_id'] == cid for r in state['chunks'])
    chunks = {r['source_id']: r for r in state['chunks']}
    support = [r for r in state['evidence'] if r['claim_id'] == cid]
    assert len(support) == 2
    assert {(r['kind'], r['source']) for r in support} == {('support', 'artifact:document-index')}
    assert {r['text'] for r in support} == {evidence_for(c, chunks[a['source_id']]), evidence_for(c, chunks[b['source_id']])}
    assert state['claims'][0]['evidence'] == evidence_for(c, chunks[b['source_id']])
    with c.p._claim_transaction(c.conn):
        c.m._record_claim_vector_target(c.conn, cid, collection='shared-retirement',
            endpoint='https://synthetic.invalid/vector', status='write_pending')
    return a, b, cid


def eligibility(c, cid):
    # Exact canonical worker admission, with the original retained read-only
    # source and its real close. Never invokes embed/HTTP/Qdrant transport.
    with c.m._DisclosureFence.claim_worker(c.m, str(c.path)) as fence:
        snapshot = fence.index_snapshot(cid)
        eligible = snapshot is not None
    lexical = c.p._search('Boreal archive', retrieval_mode='fts', record_retrieval=False,
                         apply_rerank=False, conn=c.conn)
    result = dict(index_eligible=eligible, lexical_ids=[r['id'] for r in lexical])
    c._emit(dict(event='DL1_actual_canonical_index_and_lexical_boundary', claim_id=cid, **result))
    return result


def retired_owner(c):
    assert not c.conn.in_transaction and c.p._transaction_quarantine is None
    assert c.p._claim_tx_connection is None and c.p._claim_tx_document_stage is None


def assert_withdrawn(c, before, after, cid):
    claim = next(r for r in after['claims'] if r['id'] == cid)
    old = next(r for r in before['claims'] if r['id'] == cid)
    assert claim['status'] == 'archived', 'DL1 active orphan after final lawful support retired'
    assert claim['memory_revision'] > old['memory_revision']
    assert not [r for r in after['chunks'] if r['active'] and r['embedding_claim_id'] == cid]
    assert not [r for r in after['claim_fts'] if r['id'] == cid]
    assert not [r for r in after['outbox'] if r['object_id'] == cid and r['operation'] in ('upsert', 'embed_and_upsert')]
    targets = [r for r in after['targets'] if r['claim_id'] == cid]
    assert targets and all(r['status'] == 'delete_pending' for r in targets)
    deletes = [r for r in after['outbox'] if r['object_id'] == cid and r['operation'] == 'delete']
    assert deletes
    assert {(json.loads(r['payload_json']).get('endpoint'), json.loads(r['payload_json']).get('collection'))
            for r in deletes} >= {(r['endpoint'], r['collection']) for r in targets}
    # Ordinary retirement uses actual status/revision/history triggers, not a
    # fictitious new memory_mutations operation. Observe the unchanged ledger.
    assert after['mutations'] == before['mutations']
    assert after['evidence'] == before['evidence']
    retired_owner(c)


@pytest.mark.parametrize('order', ['reverse', 'forward'])
def test_shared_last_support_retires(derived_case, order):
    """Same shipped safety oracle on pristine ca0 and the correction."""
    with fx.Fixture('shared-' + order) as c:
        a, b, cid = setup_shared(c)
        before, _ = observe(c, 'before-first-delete')
        healthy = eligibility(c, cid)
        first, last = (b, a) if order == 'reverse' else (a, b)
        first_result = c.doc.delete_document(c.p, dict(source_id=first['source_id']))
        middle, _ = observe(c, 'after-first-delete-surviving-support')
        surviving = eligibility(c, cid)
        last_result = c.doc.delete_document(c.p, dict(source_id=last['source_id']))
        after, _ = observe(c, 'after-final-delete-before-safety-oracle')
        final = eligibility(c, cid)
        c._emit(dict(event='DL1_order_oracle', order=order, claim_id=cid,
                     source_A=a['source_id'], source_B=b['source_id'],
                     first=first_result, last=last_result, healthy=healthy, surviving=surviving, final=final,
                     active_original_supports=sum(bool(r['active']) for r in after['chunks'])))
        assert healthy['index_eligible'] and cid in healthy['lexical_ids']
        assert first_result['archived_claims'] == 0 and middle['claims'][0]['status'] == 'active'
        assert sum(bool(r['active']) for r in middle['chunks']) == 1
        assert surviving['index_eligible'] and cid in surviving['lexical_ids']
        assert all(r['active'] == 0 and r['status'] == 'deleted' for r in after['sources'])
        assert not after['chunk_fts'] and not after['unit_fts']
        assert_withdrawn(c, before, after, cid)
        assert last_result['archived_claims'] == 1
        assert not final['index_eligible'] and cid not in final['lexical_ids']


def test_shared_changed_reingest_retires_earlier_support(derived_case):
    with fx.Fixture('shared-reingest') as c:
        a, b, cid = setup_shared(c)
        c.doc.delete_document(c.p, dict(source_id=b['source_id']))
        before, _ = observe(c, 'last-support-before-content-change')
        changed = c.ingest('first/shared', fx.NEW_TEXT)
        after, _ = observe(c, 'changed-reingest-before-oracle')
        assert changed['source_id'] == a['source_id'] and changed['revision_id'] != a['revision_id']
        assert_withdrawn(c, before, after, cid)
        assert not eligibility(c, cid)['index_eligible']
        created = c.embed(changed['source_id'])
        fresh, _ = observe(c, 'new-content-materialized')
        assert created['created'] == 1 and created['failed'] == 0
        assert len([r for r in fresh['claims'] if r['status'] == 'active' and r['id'] != cid]) == 1


def test_shared_reused_earlier_revision_still_proves_support(derived_case):
    with fx.Fixture('shared-earlier-revision') as c:
        a, b, cid = setup_shared(c)
        # Restore A's scalar through its genuine dedup writer, not an evidence
        # SQL rewrite. B's lawful link preserves C while A changes revision.
        with c.p._claim_transaction(c.conn):
            c.conn.execute("UPDATE document_chunks SET embedding_claim_id='' WHERE source_id=?", (a['source_id'],))
        assert c.embed(a['source_id'])['created'] == 1
        c._mp.setenv('MEMORY_WIKI_DOCUMENT_CHUNK_CHARS', '6100')
        newer = c.ingest('first/shared')
        reused = c.embed(a['source_id'])
        before, _ = observe(c, 'reused-earlier-revision-before-retire')
        c.doc.delete_document(c.p, dict(source_id=b['source_id']))
        result = c.doc.delete_document(c.p, dict(source_id=a['source_id']))
        after, _ = observe(c, 'reused-earlier-revision-retired')
        assert newer['revision_id'] != a['revision_id']
        assert reused['reused'] == 1 and reused['created'] == 0
        assert any(r['revision_id'] == a['revision_id'] for r in before['revisions'])
        latest = next(r for r in before['chunks'] if r['source_id'] == a['source_id'] and r['active'])
        assert before['claims'][0]['evidence'] == evidence_for(c, latest, revision=a['revision_id'])
        assert result['archived_claims'] == 1
        assert_withdrawn(c, before, after, cid)


@pytest.mark.parametrize('mismatch', ['forged-link', 'kind', 'source', 'revision', 'content', 'project'])
def test_retirement_requires_exact_original_support(derived_case, mismatch):
    with fx.Fixture('support-deny-' + mismatch) as c:
        if mismatch == 'forged-link':
            a, b = c.ingest('first/shared'), c.ingest('second/shared')
            assert c.embed(b['source_id'])['created'] == 1
            cid = c.conn.execute("SELECT id FROM claims WHERE source='artifact:document-index'").fetchone()[0]
            # Only B genuinely supports C. Removing B's derivative link then
            # forging A's link must not transfer B's provenance to A.
            with c.p._claim_transaction(c.conn):
                c.conn.execute("UPDATE document_chunks SET embedding_claim_id='' WHERE source_id=?", (b['source_id'],))
                c.conn.execute('UPDATE document_chunks SET embedding_claim_id=? WHERE source_id=?', (cid, a['source_id']))
            c.doc.delete_document(c.p, dict(source_id=b['source_id']))
        else:
            a, b, cid = setup_shared(c)
            c.doc.delete_document(c.p, dict(source_id=b['source_id']))
            chunk = dict(c.conn.execute('SELECT * FROM document_chunks WHERE source_id=? AND active=1', (a['source_id'],)).fetchone())
            original = evidence_for(c, chunk)
            with c.p._claim_transaction(c.conn):
                if mismatch in ('kind', 'source'):
                    column, value = ('kind', 'refute') if mismatch == 'kind' else ('source', 'tool:unrelated')
                    c.conn.execute('UPDATE evidence SET ' + column + '=? WHERE claim_id=? AND text=?', (value, cid, original))
                elif mismatch in ('revision', 'content'):
                    replacement = evidence_for(c, chunk, **({'revision': 'nonexistent-revision'} if mismatch == 'revision' else {'content': 'different-content'}))
                    c.conn.execute('UPDATE evidence SET text=? WHERE claim_id=? AND text=?', (replacement, cid, original))
                else:
                    c.conn.execute("UPDATE claims SET project_id='repo-foreign' WHERE id=?", (cid,))
        before, images = observe(c, 'invalid-support-before-delete-' + mismatch)
        result = c.doc.delete_document(c.p, dict(source_id=a['source_id']))
        after, final_images = observe(c, 'invalid-support-after-delete-' + mismatch)
        c._emit(dict(event='DL1_provenance_refusal', mismatch=mismatch, claim_id=cid, result=result))
        assert result['archived_claims'] == 0
        assert next(r for r in after['claims'] if r['id'] == cid)['status'] == 'active'
        assert not any(r['active'] and r['embedding_claim_id'] == cid for r in after['chunks'])
        for table in ('claims', 'evidence', 'memory_mutations', 'claim_write_fingerprints', 'claims_fts', 'index_outbox', 'claim_vector_targets'):
            assert images[table] == final_images[table], table
        assert before['claims'] == after['claims']
        retired_owner(c)


@pytest.mark.parametrize('fault', ['commit', 'claim-update'])
def test_shared_retirement_native_refusal_is_atomic(derived_case, fault):
    with fx.Fixture('retirement-rollback-' + fault) as c:
        a, b, cid = setup_shared(c)
        c.doc.delete_document(c.p, dict(source_id=b['source_id']))
        before, images = observe(c, 'before-native-retirement-refusal')
        denied = []
        def authorizer(op, one, two, db, trigger):
            refusing = ((fault == 'commit' and op == sqlite3.SQLITE_TRANSACTION and one == 'COMMIT')
                        or (fault == 'claim-update' and op == sqlite3.SQLITE_UPDATE and one == 'claims' and two == 'status'))
            if refusing:
                denied.append((op, one, two))
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK
        c.conn.set_authorizer(authorizer)
        failure = None
        try:
            try:
                c.doc.delete_document(c.p, dict(source_id=a['source_id']))
            except sqlite3.DatabaseError as error:
                failure = type(error).__name__
        finally:
            c.conn.set_authorizer(None)
        after, final_images = observe(c, 'after-native-retirement-refusal')
        c._emit(dict(event='DL1_native_rollback', fault=fault, denied=denied, failure=failure,
                     whole_write_set_equal=images == final_images))
        assert denied and failure is not None
        assert final_images == images
        retired_owner(c)
        assert eligibility(c, cid)['index_eligible']
        result = c.doc.delete_document(c.p, dict(source_id=a['source_id']))
        healthy, _ = observe(c, 'next-healthy-retirement')
        assert result['archived_claims'] == 1
        assert_withdrawn(c, before, healthy, cid)
