"""Original admission at actual Qdrant point PUT, genuine SOURCE component.

Authored external HTTP only: no socket/model/native-host/bootstrap assertion.
Received PUT bytes, later cleanup and public return are independent oracles.
"""
from __future__ import annotations
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import threading
import time

import pytest

_SPEC = importlib.util.spec_from_file_location('qdrant_publication_fixture',
    Path(__file__).parent / 'ci_owned/qdrant_publication_fixture.py')
f = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = f
_SPEC.loader.exec_module(f)
publication_case = f.publication_case


def test_claim_collection_erase(publication_case):
    f.baseline_counterfactual()
    with f.Fixture('collection-erase') as case:
        cid = f.produce(case)
        with f.remover(case) as other:
            with f.schedule(case, 'collection', lambda: f.withdraw(case, other, cid=cid)) as seen:
                out = f.call(case)
        assert seen == ['collection'] and len(case.withdrawals) == 1, 'actual_committed_withdrawal_seam_not_completed'
        assert case.calls['post'] == 1  # Received embedding work is not erased.
        assert f.claim.MARKER not in json.dumps(out)
        case._emit({'event': 'collection_erase_outcome', 'received_PUTs': len(case.puts),
            'late_cleanup_deletes': case.calls['delete'], 'public': out,
            'sink_claim_excerpt': bool(case.puts and f.claim.MARKER in json.dumps(case.puts))})
        # Baseline fails ONLY here, after durable removal and public observation.
        assert case.puts == [], 'withdrawn_claim_excerpt_ACL_vector_reached_actual_point_PUT'
        assert out['ok'] == 0 and out['fail'] == 1
        assert not any(case.points.values())


@pytest.mark.parametrize('producer', ['outbox', 'full', 'scoped'])
def test_healthy_claims(publication_case, producer):
    with f.Fixture('healthy-claim') as case:
        cid = f.produce(case)
        m = case.m
        sql = []
        foreign = 'publication-foreign'
        if producer == 'full':
            # Explicit authored registered-vector role, NOT foreign SQL-text admission.
            text = 'CANARY_FOREIGN_SQL_TEXT_MUST_NOT_HYDRATE'
            case.claim(foreign, text=text, visibility='private', origin_bot_id='foreign-owner', origin_session_id='foreign-session')
            case.ready()
            row = case.conn.execute('SELECT * FROM claims WHERE id=?', (foreign,)).fetchone()
            manifest, coll = m._manifest_hash(m._embedding_manifest()), m._physical_collection_name()
            payload = m._qdrant_claim_payload(foreign, text, row, manifest_hash=manifest)
            m._record_claim_vector_target(case.conn, foreign, collection=coll, manifest_hash=manifest, status='active')
            case.conn.commit()
            case.points[coll] = {str(m._qdrant_point_id(foreign)): {
                'id': m._qdrant_point_id(foreign), 'vector': [.5] * 8, 'payload': payload}}
        case.conn.set_trace_callback(sql.append)
        try:
            with f.observe(case) as proof:
                out = f.call(case, producer)
        finally:
            case.conn.set_trace_callback(None)
        assert out['ok' if producer == 'outbox' else 'ok_count'] == (2 if producer == 'full' else 1)
        if producer != 'outbox':
            assert out['status'] == ('completed' if producer == 'full' else 'scoped_completed')
        assert case.calls['post'] == 1
        own = [p for body in case.puts for p in body['points'] if p['payload'].get('claim_id') == cid]
        assert len(own) == 1 and own[0]['payload']['claim'] == f.TEXT
        assert own[0]['vector'] == f.VECTOR and own[0]['payload']['visibility_scope'] == 'bot'
        assert case.conn.execute("SELECT status FROM claim_vector_targets WHERE claim_id=?", (cid,)).fetchone()[0] == 'active'
        if producer == 'scoped':
            assert len(proof['before_write']) == 1 and proof['dispatches'] == []
            assert any(s == 'BEGIN IMMEDIATE' for s in sql)
        else:
            assert proof['pending'] and len(proof['dispatches']) == 1
            assert proof['dispatches'][0] in proof['binds']
        if producer == 'outbox':
            assert not case.conn.execute('SELECT 1 FROM index_outbox').fetchone()
        if producer == 'full':
            copied = next(p for body in case.puts for p in body['points'] if p['payload'].get('claim_id') == foreign)
            assert copied['vector'] == [.5] * 8 and 'claim' not in copied['payload']
            assert text not in json.dumps(case.requests)
            assert not any('SELECT * FROM claims' in s and foreign in s for s in sql)
            assert not any('SELECT normalized_claim FROM claims WHERE id=' in s and foreign in s for s in sql)


@pytest.mark.parametrize('kind', ['generated', 'supplied'])
def test_healthy_episodes(publication_case, kind):
    with f.Fixture('healthy-episode') as case:
        eid = f.episode.capture(case)
        if kind == 'supplied':
            f.supplied(case, eid)
        with f.observe(case) as proof:
            out = f.call(case)
        assert out['ok'] == 1 and out['fail'] == 0
        assert len(case.puts) == 1 and case.calls['post'] == int(kind == 'generated')
        point = case.puts[0]['points'][0]
        payload = point['payload']
        assert point['vector'] == f.VECTOR and payload['episode_id'] == eid
        assert payload['vector_text_hash'] == case.m.sha(f.episode.TEXT)
        assert not {'claim', 'content', 'text'} & payload.keys()
        assert f.episode.MARKER not in json.dumps(case.puts)
        assert len(proof['dispatches']) == 1 and proof['dispatches'][0].episode_indexes
        row = case.conn.execute('SELECT * FROM episodic_turns WHERE id=?', (eid,)).fetchone()
        assert row['vector_manifest_hash'] and row['vector_target_hash']
        assert case.conn.execute('SELECT status FROM episodic_vector_targets WHERE episode_id=?', (eid,)).fetchone()[0] == 'active'
        assert not case.conn.execute('SELECT 1 FROM index_outbox').fetchone()


@pytest.mark.parametrize('producer', ['outbox', 'full', 'episode'])
def test_prepared_erase(publication_case, producer):
    with f.Fixture('prepared-erase') as case:
        eid = f.episode.capture(case) if producer == 'episode' else None
        cid = None if eid else f.produce(case)
        text = f.episode.TEXT if eid else f.TEXT
        with f.remover(case) as other:
            effect = lambda: f.withdraw(case, other, cid=cid, eid=eid, text=text)
            with f.schedule(case, 'prepared', effect) as seen:
                out = f.call(case, 'full' if producer == 'full' else 'outbox')
        assert seen == ['prepared'] and len(case.withdrawals) == 1 and case.puts == []
        assert case.calls['post'] == 1
        assert out['ok_count' if producer == 'full' else 'ok'] == 0
        assert out['failed' if producer == 'full' else 'fail'] == 1
        assert f.claim.MARKER not in json.dumps(out) and f.episode.MARKER not in json.dumps(out)
        # A refused data PUT must not disable metadata/readback/privacy DELETE.
        if producer != 'full':
            cleanup = f.call(case)
            assert cleanup['ok'] >= 1 and case.calls['delete'] >= 1
        assert not any(case.points.values())
        rows = list(case.conn.execute('SELECT payload_json FROM index_outbox'))
        assert all('text' not in json.loads(r[0]) for r in rows)


def test_absolute_TTL(publication_case):
    with f.Fixture('ttl') as case:
        eid = f.episode.capture(case)
        expires = int(time.time()) + 3
        f.episode.edit(case, eid, expires_at=expires)
        f.episode.update_hint(case, eid, expires_at=expires)
        versions = []
        def expire_without_SQL():
            versions.append(case.conn.execute('PRAGMA data_version').fetchone()[0])
            time.sleep(max(0, expires - time.time()) + .02)
            versions.append(case.conn.execute('PRAGMA data_version').fetchone()[0])
        with f.schedule(case, 'collection', expire_without_SQL) as seen:
            out = f.call(case)
        assert seen and len(set(versions)) == 1 and time.time() > expires
        assert out['fail'] == 1 and case.calls['post'] == 1 and case.puts == []
        assert case.conn.execute('SELECT expires_at FROM episodic_turns WHERE id=?', (eid,)).fetchone()[0] == expires
        case._emit({'event': 'publication_TTL_no_SQL', 'versions': versions, 'PUTs': len(case.puts)})


def test_original_ABA(publication_case):
    with f.Fixture('ABA') as case:
        cid = f.produce(case)
        before = tuple(case.conn.execute('SELECT * FROM claims WHERE id=?', (cid,)).fetchone())
        def ABA():
            f.claim.changed(case, 'ABA', cid=cid)
            assert tuple(case.conn.execute('SELECT * FROM claims WHERE id=?', (cid,)).fetchone()) == before
        with f.schedule(case, 'prepared', ABA) as seen:
            out = f.call(case)
        assert seen and case.puts == [] and case.calls['post'] == 1 and out['fail'] == 1
        assert case.conn.execute('SELECT status FROM claim_vector_targets WHERE claim_id=?', (cid,)).fetchone()[0] == 'write_pending'


def test_same_stop_primary_UNKNOWN(publication_case):
    with f.Fixture('stop-primary') as case:
        eid = f.episode.capture(case)
        f.supplied(case, eid)  # No earlier embedding admission can consume the seam.
        m, cls = case.m, case.m._DisclosureFence
        dispatch = f.peer.unwrapped(m._observed_semantic_http).__code__
        for mode in ('cancel', 'deadline'):
            # Keep the same genuine job; an expected previous failure is retryable.
            case.conn.execute("UPDATE index_outbox SET next_retry_at=0 WHERE object_id=?", (eid,))
            case.conn.commit()
            event = threading.Event()
            deadline = time.monotonic() + (4 if mode == 'cancel' else 1)
            def is_final(frame, ev, arg):
                parent = frame.f_back
                outer = parent.f_back if parent else None
                return ev == 'return' and arg is True and parent is not None and parent.f_code is cls.admit_episode_index.__code__ and outer is not None and outer.f_code is dispatch
            def stop():
                assert m._PREFETCH_LOCAL.cancel_event is event and m._PREFETCH_LOCAL.deadline == deadline
                if mode == 'cancel':
                    event.set()
                else:
                    time.sleep(max(0, deadline - time.monotonic()) + .01)
            with m._prefetch_budget(4, event, deadline=deadline):
                with f.claim.at(case, cls.finish.__code__, is_final, stop) as seen:
                    out = f.call(case)
                assert m._PREFETCH_LOCAL.cancel_event is event and m._PREFETCH_LOCAL.deadline == deadline
            assert seen and out['fail'] == 1 and not case.puts
        case.conn.execute("UPDATE index_outbox SET next_retry_at=0 WHERE object_id=?", (eid,))
        case.conn.commit()
        primary = BaseException('authored_publication_primary')
        source, retained = [], []
        def capture_source(frame, event, arg):
            if event == 'return' and frame.f_code is cls.__init__.__code__:
                source.append(frame.f_locals['self'])
            return False
        target = f.peer.unwrapped(cls.episode_worker).__code__
        cleanup = BaseException('authored_reader_close_refusal')
        def refuse_close():
            raise cleanup
        def abort():
            raise primary
        # Primary comes from the authored received-effect transport, NOT the
        # profiler: throwing in sys.setprofile would disable the close witness.
        case.sink_effect = abort
        with f.claim.at(case, cls.__init__.__code__, capture_source, lambda: None):
            with f.claim.at(case, target, lambda fr, ev, a: ev == 'c_call' and getattr(a, '__name__', None) == 'close' and source and getattr(a, '__self__', None) is source[-1].conn, refuse_close) as closing:
                with f.schedule(case, 'prepared', lambda: None) as prepared:
                    with pytest.raises(BaseException) as caught:
                        f.call(case)
        assert prepared and closing and caught.value is primary and len(case.puts) == 1
        df = sys.modules[cls.__module__]
        retained[:] = df._INDEX_READERS_UNKNOWN
        assert retained == [(source[-1].conn, source[-1])]
        assert source[-1].conn.execute('SELECT 1').fetchone()[0] == 1
        assert primary.__notes__ == ['claim_index_reader_cleanup_UNKNOWN']
        with pytest.raises(m._DeliveryWithheld):
            with cls.episode_worker(m, str(case.path)):
                raise AssertionError('retained_UNKNOWN_was_replaced')
        case._emit({'event': 'publication_primary_UNKNOWN', 'same_primary': True,
            'exact_reader_retained': True, 'new_reader_refused': True, 'PUTs': len(case.puts)})
        source[-1].conn.close()  # Reviewer safety only, AFTER production retention receipt.
