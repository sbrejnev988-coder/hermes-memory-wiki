"""C1/C2 regression packet: actual component writers, never host/model boot."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys

import pytest

_SPEC = importlib.util.spec_from_file_location('derived_materialization_fixture',
    Path(__file__).with_name('ci_owned') / 'derived_claim_materialization_fixture.py')
fx = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = fx
_SPEC.loader.exec_module(fx)
derived_case = fx.derived_case


def doc_claims(case):
    return case.conn.execute("SELECT id,status FROM claims WHERE source='artifact:document-index' ORDER BY id").fetchall()


def code_claims(case):
    return case.conn.execute("SELECT c.id,c.status,m.content_hash FROM claims c JOIN code_claim_metadata m ON m.claim_id=c.id WHERE m.claim_type='code_graph_chunk' ORDER BY c.id").fetchall()


def test_document_link_failure_has_no_orphan(derived_case):
    """Baseline C1: known native link rollback must undo the real claim TX."""
    with fx.Fixture('link-failure') as c:
        source = c.ingest()
        c.m.SEMANTIC_ENABLED = True
        before = c.durable()
        with fx.deny_link(c) as denied:
            result = c.embed(source['source_id'])
        assert denied and result['failed'] == 1, result
        after = c.durable()
        c.doc.delete_document(c.p, dict(source_id=source['source_id']))
        retired = c.durable()
        c._emit(dict(event='C1_orphan_oracle', before=before, after=after, after_source_delete=retired,
                     active_document_claims=len([r for r in doc_claims(c) if r['status'] == 'active'])))
        for table in ('claims', 'evidence', 'memory_mutations', 'claim_write_fingerprints', 'index_outbox', 'claims_fts'):
            assert after['images'][table] == before['images'][table], table
        assert not [r for r in doc_claims(c) if r['status'] == 'active']
        assert not c.conn.in_transaction and c.p._transaction_quarantine is None
        # A native ignored UPDATE must fail the CAS rowcount, not publish an
        # orphan or count a rolled-back claim as created.
        second = c.ingest('ignored')
        with c.p._claim_transaction(c.conn):
            c.conn.execute("CREATE TRIGGER authored_ignore_link BEFORE UPDATE OF embedding_claim_id ON document_chunks WHEN NEW.embedding_claim_id<>'' BEGIN SELECT RAISE(IGNORE); END")
        ignored = c.embed(second['source_id'])
        assert ignored['failed'] == 1 and ignored['created'] == 0 and not doc_claims(c)
        with c.p._claim_transaction(c.conn):
            c.conn.execute('DROP TRIGGER authored_ignore_link')
        # Catching a child error does not legalize committing its incomplete
        # owning obligation. The outer stage must still roll back everything.
        with fx.deny_link(c):
            with pytest.raises(RuntimeError, match='document_embedding_link_incomplete'):
                with c.p._claim_transaction(c.conn):
                    with pytest.raises(sqlite3.DatabaseError):
                        c.embed(second['source_id'])
        assert c.durable()['claims'] == 0 and c.p._claim_tx_document_stage is None


def test_pending_snapshot_patch_backfill_is_not_stale(derived_case):
    """Baseline C2: a durable patch must withdraw pending old derivatives."""
    with fx.Fixture('pending-patch') as c:
        old, _ = c.snapshot()
        assert not code_claims(c)
        c.m.SEMANTIC_ENABLED = True
        patch, applied = c.patch()
        assert applied['outcome'].get('id') and not applied['deduplicated'], applied
        assert c.conn.execute('SELECT COUNT(*) FROM patch_outcomes').fetchone()[0] == 1
        result = c.backfill()
        rows = code_claims(c)
        c._emit(dict(event='C2_stale_oracle', materialized=[dict(r) for r in rows], result=result))
        assert not rows, 'old snapshot materialized after durable patch'
        assert c.conn.execute('SELECT COUNT(*) FROM code_graph_chunks').fetchone()[0] == 0
        assert c.conn.execute('SELECT COUNT(*) FROM code_graph_chunks_fts').fetchone()[0] == 0
        assert c.conn.execute('SELECT commit_sha FROM code_graph_repositories').fetchone()[0] == old['commit_sha']
        # An old verified recovery artifact is still a duplicate; replay must
        # not restore derivatives withdrawn by the later patch.
        old_artifact = c.p._store_code_graph_inbox_artifact(old, json.dumps(old).encode(),
            source_payload_hash=c.m._normalized_code_graph_event_payload_hash(old))
        replay = c.p._replay_code_recovery_reference(dict(schema='code_recovery_reference/v1',
            kind='code_graph_inbox', artifacts=[old_artifact]))
        assert replay['processed'] == 1 and replay['results'][0]['deduplicated']
        assert c.conn.execute('SELECT COUNT(*) FROM code_graph_chunks').fetchone()[0] == 0
        # A new authoritative snapshot, also through genuine recovery, restores
        # eligibility without rebasing old chunks onto the patch commit.
        digest = hashlib.sha256(fx.NEW_TEXT.encode()).hexdigest()
        fresh = {**old, 'event_id': 'snapshot-new', 'commit_sha': hashlib.sha1(b'fresh').hexdigest(),
                 'files': [{**old['files'][0], 'file_hash': digest}],
                 'chunks': [{**old['chunks'][0], 'chunk_text': fx.NEW_TEXT,
                             'embedding_text': fx.NEW_TEXT, 'content_hash': digest}]}
        artifact = c.p._store_code_graph_inbox_artifact(fresh, json.dumps(fresh).encode(),
            source_payload_hash=c.m._normalized_code_graph_event_payload_hash(fresh))
        replay = c.p._replay_code_recovery_reference(dict(schema='code_recovery_reference/v1',
            kind='code_graph_inbox', artifacts=[artifact]))
        assert replay['processed'] == 1 and replay['results'][0]['status'] == 'completed'
        recovered = c.backfill()
        assert recovered['embedding']['created'] == 1, recovered
        rows = code_claims(c)
        assert len(rows) == 1 and rows[0]['content_hash'] == hashlib.sha256(fx.NEW_TEXT.encode()).hexdigest()


def test_document_healthy_create_reuse_and_postcommit(derived_case):
    with fx.Fixture('healthy') as c:
        source = c.ingest()
        c.m.SEMANTIC_ENABLED = True
        with fx.observe_callbacks(c) as callbacks:
            created = c.embed(source['source_id'])
        assert created['created'] == 1 and created['failed'] == 0, created
        assert len(callbacks) == 1 and callbacks[0]['idle'] and callbacks[0]['durable_links'] == 1
        assert callbacks[0]['durable_claims'] == 1
        cid = doc_claims(c)[0]['id']
        assert c.conn.execute('SELECT COUNT(*) FROM evidence WHERE claim_id=?', (cid,)).fetchone()[0] == 1
        assert c.conn.execute("SELECT COUNT(*) FROM index_outbox WHERE object_id=? AND operation='embed_and_upsert'", (cid,)).fetchone()[0] == 1
        assert c.conn.execute('SELECT COUNT(*) FROM claims_fts WHERE id=?', (cid,)).fetchone()[0] == 1
        # Authored loss of only the derivative link models supported recovery;
        # real active/visible evidence reuse must not recreate the claim.
        with c.p._claim_transaction(c.conn):
            c.conn.execute("UPDATE document_chunks SET embedding_claim_id='' WHERE source_id=?", (source['source_id'],))
        with fx.observe_callbacks(c) as callbacks:
            reused = c.embed(source['source_id'])
        assert reused['reused'] == 1 and reused['created'] == 0, reused
        assert len(doc_claims(c)) == 1 and len(callbacks) == 1  # no additional callback on reuse
        owned = c.ingest('owned', fx.NEW_TEXT)
        with c.p._claim_transaction(c.conn):
            c.connectors([(owned['source_id'], c.bot_id, 'active')])
        assert c.embed(owned['source_id'])['created'] == 1
        linked = c.conn.execute('SELECT embedding_claim_id FROM document_chunks WHERE source_id=?', (owned['source_id'],)).fetchone()[0]
        assert c.conn.execute('SELECT visibility_scope FROM claims WHERE id=?', (linked,)).fetchone()[0] == 'bot'
        with c.p._claim_transaction(c.conn):
            c.conn.execute("UPDATE document_chunks SET embedding_claim_id='' WHERE source_id=?", (owned['source_id'],))
        before = c.durable()
        def withdraw_connector():
            c.conn.execute("UPDATE external_sources SET status='inactive' WHERE document_source_id=?", (owned['source_id'],))
        with fx.callback_seam(c, '_claim_journal_pending_commit', withdraw_connector) as seen:
            denied = c.embed(owned['source_id'])
        assert seen and denied['failed'] == 1 and denied['reused'] == 0
        assert c.durable()['images']['claims'] == before['images']['claims']


def test_document_commit_deny_is_known_rollback(derived_case):
    with fx.Fixture('commit-deny') as c:
        source = c.ingest()
        c.m.SEMANTIC_ENABLED = True
        before = c.durable()
        with fx.deny_link(c, commit=True) as denied:
            result = c.embed(source['source_id'])
        assert any(row[1] == 'COMMIT' for row in denied), denied
        assert result['failed'] == 1 and result['created'] == 0, result
        after = c.durable()
        for table in ('claims', 'evidence', 'memory_mutations', 'claim_write_fingerprints', 'index_outbox', 'claims_fts'):
            assert after['images'][table] == before['images'][table], table
        assert not c.conn.in_transaction and c.p._claim_tx_document_stage is None
        assert c.p._transaction_quarantine is None


def test_document_shared_delete_and_changed_reingest(derived_case):
    with fx.Fixture('shared') as c:
        one, two = c.ingest('first/shared'), c.ingest('second/shared')
        assert c.embed(one['source_id'])['created'] == 1
        assert c.embed(two['source_id'])['created'] == 1  # real dedup/add evidence, one claim
        rows = doc_claims(c)
        assert len(rows) == 1
        cid = rows[0]['id']
        assert c.conn.execute('SELECT COUNT(*) FROM document_chunks WHERE active=1 AND embedding_claim_id=?', (cid,)).fetchone()[0] == 2
        c.doc.delete_document(c.p, dict(source_id=one['source_id']))
        assert doc_claims(c)[0]['status'] == 'active'
        new = c.ingest('second/shared', fx.NEW_TEXT)
        assert new['revision_id'] != two['revision_id']
        assert doc_claims(c)[0]['status'] == 'archived'
        assert c.embed(new['source_id'])['created'] == 1
        assert len([r for r in doc_claims(c) if r['status'] == 'active']) == 1


@pytest.mark.parametrize('retirement', ['archived', 'missing'])
def test_document_retained_links_do_not_resurrect(derived_case, retirement):
    with fx.Fixture('retained') as c:
        source = c.ingest()
        assert c.embed(source['source_id'])['created'] == 1
        cid = doc_claims(c)[0]['id']
        with c.p._claim_transaction(c.conn):
            if retirement == 'archived':
                c.conn.execute("UPDATE claims SET status='archived' WHERE id=?", (cid,))
            else:
                c.conn.execute('DELETE FROM claims WHERE id=?', (cid,))
        before = c.durable()
        result = c.embed(source['source_id'])
        assert result['created'] == result['reused'] == 0, result
        after = c.durable()
        assert after['images']['claims'] == before['images']['claims']
        assert c.conn.execute('SELECT embedding_claim_id FROM document_chunks WHERE source_id=? AND active=1', (source['source_id'],)).fetchone()[0] == cid


def test_document_original_binding_after_prepare(derived_case):
    with fx.Fixture('prepare-drift') as c:
        for change in ('source', 'chunk', 'actor'):
            source = c.ingest('prepare-' + change)
            original_session = c.p.session_id
            def withdraw():
                if change == 'actor':
                    c.p.session_id = 'late-session'
                else:
                    with c.p._claim_transaction(c.conn):
                        if change == 'source':
                            c.conn.execute("UPDATE document_sources SET revision_id='late-revision' WHERE source_id=?", (source['source_id'],))
                        else:
                            c.conn.execute("UPDATE document_chunks SET embedding_text=? WHERE source_id=?", (fx.NEW_TEXT, source['source_id']))
            with fx.callback_seam(c, '_prepare_claim', withdraw) as seen:
                result = c.embed(source['source_id'])
            assert seen and result['created'] == 0, result
            assert not doc_claims(c)
            assert c.p._transaction_quarantine is None
            # Fixture-only actor restoration after proved clean completion;
            # never reset a quarantined owner or an original obligation.
            c.p.session_id = original_session


def test_document_late_owning_commit_callback(derived_case):
    with fx.Fixture('late-owner') as c:
        for change in ('source', 'actor'):
            source = c.ingest('late-' + change)
            original_session = c.p.session_id
            def withdraw():
                if change == 'actor':
                    c.p.session_id = 'late-session'
                else:
                    c.conn.execute('UPDATE document_sources SET active=0 WHERE source_id=?', (source['source_id'],))
            with fx.callback_seam(c, '_claim_journal_pending_commit', withdraw) as seen:
                result = c.embed(source['source_id'])
            assert seen and result['failed'] == 1 and result['created'] == 0, result
            assert not doc_claims(c) and not c.conn.in_transaction
            assert c.p._claim_tx_document_stage is None
            c.p.session_id = original_session


def test_document_join_defers_to_actual_outer_commit(derived_case):
    with fx.Fixture('joined') as c:
        two = c.ingest('two', fx.NEW_TEXT)
        with fx.observe_callbacks(c) as callbacks:
            with c.p._claim_transaction(c.conn):
                # Compose actual joined ingest and its inline materializer,
                # retaining both original obligations through the outer commit.
                one = c.ingest('one', embed=True)
                assert one['embedding']['created'] == 1
                assert one['embedding']['status'] == 'pending_commit'
                assert one['embedding']['commit_pending'] is True
                assert c.embed(two['source_id'])['created'] == 1
                assert c.conn.in_transaction and not callbacks
                assert c.durable()['claims'] == 0
            assert len(callbacks) == 2
        assert all(r['idle'] and r['durable_links'] == 1 and r['durable_claims'] == 1 for r in callbacks)
        assert c.p._claim_tx_document_stage is None


def test_document_join_retains_first_and_repeated_admission(derived_case):
    with fx.Fixture('joined-drift') as c:
        one, two = c.ingest('one'), c.ingest('two', fx.NEW_TEXT)
        with pytest.raises(PermissionError, match='document_.*actor_changed'):
            with c.p._claim_transaction(c.conn):
                assert c.embed(one['source_id'])['created'] == 1
                # First admission must not be replaced by the latest actor.
                c.p.session_id = 'second-actor'
                assert c.embed(two['source_id'])['created'] == 1
                assert c.embed(two['source_id'])['processed'] == 0
        assert c.durable()['claims'] == 0
        assert c.p._claim_tx_document_stage is None
        assert c.p._transaction_quarantine is None
        c.p.session_id = 'session-own'  # Fixture restoration after known rollback.
        # A new, healthy owning stage must retain the earlier source through
        # the late outer callback as well as through its child returns.
        def withdraw():
            c.conn.execute('UPDATE document_sources SET active=0 WHERE source_id=?', (one['source_id'],))
        with fx.callback_seam(c, '_claim_journal_pending_commit', withdraw) as seen:
            with pytest.raises((PermissionError, RuntimeError), match='document_'):
                with c.p._claim_transaction(c.conn):
                    assert c.embed(one['source_id'])['created'] == 1
                    assert c.embed(two['source_id'])['created'] == 1
        assert seen and c.durable()['claims'] == 0
        assert c.p._transaction_quarantine is None


def test_document_unknown_retains_exact_owner_primary_and_stage(derived_case):
    with fx.Fixture('unknown') as c:
        source = c.ingest()
        c.m.SEMANTIC_ENABLED = True
        with fx.deny_link(c, rollback=True) as denied:
            with pytest.raises(sqlite3.DatabaseError) as error:
                c.embed(source['source_id'])
        assert any(row[1] == 'ROLLBACK' for row in denied), denied
        assert c.p._transaction_primary is error.value
        assert c.p._transaction_quarantine is c.conn and c.p._claim_tx_connection is c.conn
        stage = c.p._claim_tx_document_stage
        assert stage[0] is c.conn and stage[2] and c.conn.in_transaction
        assert c.p._lifecycle_state == 'quarantined'
        assert any('UNKNOWN' in note for note in error.value.__notes__)
        assert c.durable()['claims'] == 0  # uncommitted effects are not visible
        with pytest.raises(RuntimeError):
            c.p._connect()
        assert c.p._transaction_quarantine is c.conn and c.p._claim_tx_document_stage is stage
        c.safety_close_unknown = True


def test_document_unregistered_join_fails_closed(derived_case):
    with fx.Fixture('unowned') as c:
        c.ingest()
        c.conn.execute('BEGIN IMMEDIATE')
        with pytest.raises(RuntimeError, match='provider_transaction_owner_pending'):
            c.embed()
        assert c.p._transaction_quarantine is c.conn and c.conn.in_transaction
        assert c.durable()['claims'] == 0
        c.safety_close_unknown = True


def test_patch_native_failure_rolls_back_outcome_and_pending(derived_case):
    with fx.Fixture('patch-rollback') as c:
        c.snapshot()
        before = c.durable()
        denied = []
        def authorizer(op, table, col, db, trigger):
            if op == sqlite3.SQLITE_DELETE and table == 'code_graph_chunks':
                denied.append(table)
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK
        c.conn.set_authorizer(authorizer)
        try:
            with pytest.raises(sqlite3.DatabaseError):
                c.patch()
        finally:
            c.conn.set_authorizer(None)
        after = c.durable()
        assert denied and after['images'] == before['images']
        assert not c.conn.in_transaction and c.p._transaction_quarantine is None


def test_revision_pending_retirement_exact_boundaries(derived_case):
    with fx.Fixture('exact-boundaries') as c:
        for boundary in ('symbol', 'file', 'repository'):
            event, _ = c.snapshot('snapshot-origin-' + boundary)
            event = {**event, 'event_id': 'snapshot-multiple-' + boundary, 'chunks': [
                *event['chunks'],
                {**event['chunks'][0], 'chunk_id': 'chunk-peer', 'symbol_id': 'peer'},
                {**event['chunks'][0], 'chunk_id': 'chunk-other', 'file_path': 'src/other.py'},
            ], 'files': [*event['files'], {**event['files'][0], 'file_path': 'src/other.py'}]}
            c.code.ingest_code_graph_event(c.p, event)
            c.snapshot('snapshot-foreign-' + boundary, repo='repo-foreign')
            args = dict(repository_id='repo-own', new_content_hash=hashlib.sha256(fx.NEW_TEXT.encode()).hexdigest())
            if boundary == 'symbol':
                args.update(symbol_id='main', file_path='src/main.py')
            elif boundary == 'file':
                args.update(file_path='src/main.py')
            else:
                args.update(repository_id='repo-foreign', file_path='src/main.py')
            c.p._invalidate_revision(args)
            actual = {(r[0], r[1]) for r in c.conn.execute('SELECT repository_id,chunk_id FROM code_graph_chunks')}
            expected = {('repo-own', 'chunk-main'), ('repo-own', 'chunk-peer'), ('repo-own', 'chunk-other'), ('repo-foreign', 'chunk-main')}
            retired = {('repo-own', 'chunk-main')} if boundary == 'symbol' else {('repo-own', 'chunk-main'), ('repo-own', 'chunk-peer')} if boundary == 'file' else {('repo-foreign', 'chunk-main')}
            assert actual == expected - retired
            assert c.conn.execute('SELECT COUNT(*) FROM code_graph_chunks_fts').fetchone()[0] == len(actual)


def test_patch_preserves_actual_new_file_and_exact_chunk_content(derived_case):
    with fx.Fixture('new-content') as c:
        complete = hashlib.sha256(b'complete source file with multiple semantic chunks').hexdigest()
        event, _ = c.snapshot(files=[dict(file_path='src/main.py', file_hash=complete, language='python', line_count=3)])
        c.patch(new_hash=complete)
        assert c.conn.execute('SELECT COUNT(*) FROM code_graph_chunks').fetchone()[0] == 1
        assert c.backfill()['embedding']['created'] == 1
        _, repeated = c.patch('verified-new-file-still-current', new_hash=complete)
        assert all(r['invalidated'] == 0 for r in repeated['invalidations'])
        assert code_claims(c)[0]['status'] == 'active'
        # A symbol/content-specific no-change revision preserves its claim too.
        digest = event['chunks'][0]['content_hash']
        out = c.p._invalidate_revision(dict(repository_id='repo-own', file_path='src/main.py', symbol_id='main', new_content_hash=digest))
        assert out['invalidated'] == 0
        assert len(code_claims(c)) == 1 and code_claims(c)[0]['status'] == 'active'


def test_duplicate_and_review_patch_have_no_pending_effects(derived_case):
    with fx.Fixture('duplicate-review') as c:
        c.snapshot()
        original, result = c.patch()
        assert result['outcome'].get('id')
        c.snapshot('snapshot-authoritative', text=fx.NEW_TEXT)
        before = c.durable()
        duplicate = c.p._apply_code_shrinker_patch_event({**original,
            'per_file': [dict(file_path='src/main.py', new_content_hash=hashlib.sha256(b'different').hexdigest()),
                         dict(file_path='src/auxiliary.py', new_content_hash=hashlib.sha256(b'different').hexdigest())]})
        assert duplicate['deduplicated'] and duplicate['invalidations'] == []
        assert c.durable()['images']['code_graph_chunks'] == before['images']['code_graph_chunks']
        # The generic redactor also maps long slash-only words. Dots split
        # those runs without changing policy; repeated main tokens keep the
        # real >420-character outcome below the unconditional quality0.34 gate.
        review_files = ['src/main.py', *[
            'src/' + 'main.' * 20 + leaf + '.py'
            for leaf in ('main', 'Main', 'MAIN', 'mAiN')
        ]]
        review_event = {**original, 'event_id': 'event-plain', 'patch_id': 'main', 'outcome': 'applied',
                        'changed_files': review_files,
                        'per_file': [dict(file_path=path, new_content_hash=hashlib.sha256(b'different').hexdigest())
                                     for path in review_files]}
        assert c.conn.execute("SELECT COUNT(*) FROM code_graph_chunks WHERE embedding_claim_id=''").fetchone()[0] > 0
        queued = c.p._apply_code_shrinker_patch_event(review_event)
        assert not queued['outcome'].get('id') and queued['invalidations'] == [], queued
        assert queued['outcome']['status'] == 'need_review'
        review_id = queued['outcome']['review_id']
        assert review_id.startswith('rq_')
        row = c.conn.execute('SELECT candidate,status,reason FROM review_queue WHERE id=?', (review_id,)).fetchone()
        assert row is not None and row['status'] == 'pending'
        assert 420 < len(row['candidate']) <= 1400
        assert '<opaque_code_graph_id>' not in row['candidate']
        lint = c.m.lint_claim_text(row['candidate'], 'patch-outcomes')
        gate = c.m.memory_gate_decision(row['candidate'], 'patch-outcomes', 'tool:patch_outcome_add')
        assert lint['quality'] < 0.34 and gate['action'] == 'queue'
        assert c.durable()['images']['code_graph_chunks'] == before['images']['code_graph_chunks']
        after_review = c.durable()
        for table in ('claims', 'patch_outcomes', 'integration_events', 'code_graph_chunks', 'code_graph_chunks_fts'):
            assert after_review['images'][table] == before['images'][table], table
        c._emit(dict(event='actual_queued_patch_no_effects', review_id=review_id,
                     candidate_chars=len(row['candidate']), quality=lint['quality'],
                     reason=row['reason'], unchanged_tables=['claims', 'patch_outcomes',
                         'integration_events', 'code_graph_chunks', 'code_graph_chunks_fts']))


def test_model_revision_does_not_withdraw_global_pending_graph(derived_case):
    with fx.Fixture('model-boundary') as c:
        c.snapshot()
        before = c.durable()
        out = c.p._invalidate_revision(dict(repository_id='repo-own', file_path='src/main.py',
            new_content_hash=hashlib.sha256(fx.NEW_TEXT.encode()).hexdigest()), model_scope=True)
        assert out['invalidated'] == 0
        assert c.durable()['images']['code_graph_chunks'] == before['images']['code_graph_chunks']
        assert c.backfill()['embedding']['created'] == 1
        cid = code_claims(c)[0]['id']
        out = c.p._invalidate_revision(dict(repository_id='repo-own', file_path='src/main.py'), model_scope=True)
        assert out['invalidated'] == 0 and code_claims(c)[0]['status'] == 'active'
        with c.p._claim_transaction(c.conn):
            c.conn.execute("UPDATE claims SET visibility_scope='private',origin_bot_id=?,origin_session_id=? WHERE id=?", (c.bot_id, c.p.session_id, cid))
        out = c.p._invalidate_revision(dict(repository_id='repo-own', file_path='src/main.py'), model_scope=True)
        assert out['invalidated'] == 1 and code_claims(c)[0]['status'] == 'archived'


def test_unchanged_snapshot_reuses_claim_and_new_generation_recovers(derived_case):
    with fx.Fixture('unchanged') as c:
        c.snapshot()
        assert c.backfill()['embedding']['created'] == 1
        cid = code_claims(c)[0]['id']
        c.snapshot('snapshot-unchanged')
        result = c.backfill()
        assert result['embedding']['reused'] == 1, result
        assert code_claims(c)[0]['id'] == cid and code_claims(c)[0]['status'] == 'active'
        c.patch()
        c.snapshot('snapshot-recovered', text=fx.NEW_TEXT)
        assert c.backfill()['embedding']['created'] == 1
        assert len([r for r in code_claims(c) if r['status'] == 'active']) == 1


def test_existing_snapshot_late_writer_fence_is_preserved(derived_case):
    with fx.Fixture('snapshot-fence') as c:
        c.snapshot()
        with fx.callback_seam(c, '_prepare_code_claim', lambda: c.snapshot('snapshot-replacement', text=fx.NEW_TEXT)) as seen:
            result = c.backfill()
        assert seen and result['embedding']['skipped_stale'] == 1, result
        assert not code_claims(c)
        assert c.backfill()['embedding']['created'] == 1
        assert code_claims(c)[0]['content_hash'] == hashlib.sha256(fx.NEW_TEXT.encode()).hexdigest()
