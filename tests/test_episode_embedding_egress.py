"""Narrow SOURCE episode admission packet; no native host/model/network claim."""
from __future__ import annotations
from contextlib import contextmanager
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import threading
import time
import urllib.request

import pytest

_SPEC = importlib.util.spec_from_file_location('episode_embedding_fixture',
    Path(__file__).parent / 'ci_owned/episode_embedding_fixture.py')
f = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = f
_SPEC.loader.exec_module(f)
episode_embedding_case = f.episode_embedding_case


def test_prepared_owned_delete(episode_embedding_case):
    with f.Fixture('delete') as case:
        eid = f.capture(case)
        with f.schedule(case, lambda: f.erase(case, eid)) as seen:
            out = f.call(case)
        assert seen == ['prepared'], 'exact_prepared_episode_dispatch_not_reached'
        assert case.calls['put'] == 0 and not any(case.points.values())
        assert case.conn.execute('SELECT COUNT(*) FROM episodic_vector_targets').fetchone()[0] == 0
        assert f.MARKER not in json.dumps(out)
        jobs = list(case.conn.execute('SELECT operation,payload_json FROM index_outbox WHERE object_id=?', (eid,)))
        assert jobs and all('text' not in json.loads(r['payload_json']) for r in jobs), 'scrubbed_payload_resurrected_by_failure_writer'
        case._emit({'event': 'prepared_delete_outcome', 'authored_POSTs': case.calls['post'],
            'late_projection_cleanup': case.calls['delete'], 'public': out,
            'scrubbed_SQL_still_scrubbed': True})
        # Baseline can fail ONLY this privacy assertion after downstream cleanup.
        assert case.calls['post'] == 0, 'revoked_episode_canary_reached_authored_embedding_POST'
        assert out['ok'] == 0 and out['fail'] == 1


def test_capture_backfill_healthy(episode_embedding_case):
    with f.Fixture('producer') as case:
        first = f.capture(case, role='user')
        second = f.capture(case, role='assistant', session='another-host-chat',
            text=f.TEXT + ' Another host turn.', semantic=False)
        count = case.m._episodic_memory.enqueue_semantic_backfill(case.p, case.receiver)
        assert count == 2  # Coalesces first; genuinely produces the missing second.
        with f.observe_original(case) as originals:
            out = f.call(case, 2)
        assert out['ok'] == 2 and out['fail'] == 0
        assert case.calls['post'] == case.calls['put'] == 2
        assert {p['input'] for p in case.posts} == {f.TEXT, f.TEXT + ' Another host turn.'}
        assert case.conn.execute('SELECT COUNT(*) FROM index_outbox').fetchone()[0] == 0
        rows = list(case.conn.execute('SELECT * FROM episodic_turns'))
        assert {r['id'] for r in rows} == {first, second}
        assert len({r['owner_chat_hash'] for r in rows}) == 2  # Namespace worker, not recall's last user.
        assert all(r['vector_manifest_hash'] and r['vector_target_hash'] for r in rows)
        targets = list(case.conn.execute("SELECT collection,status FROM episodic_vector_targets"))
        assert len(targets) == 2 and all(r['status'] == 'active' for r in targets)
        assert all(r['collection'] == case.m._episodic_collection_name() != case.m._physical_collection_name() for r in targets)
        for original in originals:
            with pytest.raises(sqlite3.ProgrammingError):
                original.conn.execute('SELECT 1')


def test_initial_supplied_cleanup(episode_embedding_case):
    with f.Fixture('supplied') as case:
        expired = f.capture(case)
        f.edit(case, expired, expires_at=int(time.time()) - 1)
        assert f.call(case)['ok'] == 1  # Existing stale-target cleanup is successful work.
        assert case.calls['post'] == case.calls['put'] == 0
        for valid in (True, False):
            eid = f.capture(case, text=f.TEXT + (' Valid supplied.' if valid else ' Invalid supplied.'))
            raw = case.conn.execute('SELECT content FROM episodic_turns WHERE id=?', (eid,)).fetchone()[0]
            snapshot = case.m._load_active_episode_index_snapshot(str(case.path), eid)
            hint = f.update_hint(case, eid, vector=f.VECTOR if valid else [0.1], qdrant_payload={
                'vector_text_hash': case.m.sha(raw), 'manifest_hash': snapshot['manifest_hash'],
                'vector_target_hash': snapshot['current_vector_target_hash']})
            case.conn.execute("UPDATE index_outbox SET operation='upsert' WHERE object_id=?", (eid,))
            case.conn.commit()
            # The first real capture also prunes the still-canonical expired
            # row and enqueues its durable DELETE. Drain that known cleanup as
            # well; created_at/id ordering is not insertion ordering.
            out = f.call(case, 10)
            assert out['processed'] == out['ok'] == (2 if valid else 1) and out['fail'] == 0
            assert case.calls['post'] == 0, 'supplied_vector_fell_back_to_embedding'
            assert case.calls['put'] == 1  # Valid PUT, invalid supplied cleans up only.
        assert case.calls['put'] == 1 and case.calls['delete'] >= 2
        assert case.conn.execute('SELECT COUNT(*) FROM episodic_vector_targets').fetchone()[0] == 1


def test_absolute_TTL_crossing(episode_embedding_case):
    with f.Fixture('ttl') as case:
        eid = f.capture(case)
        expires = int(time.time()) + 3
        f.edit(case, eid, expires_at=expires)
        f.update_hint(case, eid, expires_at=expires)
        versions = []
        def wait_for_real_expiry():
            versions.append(case.conn.execute('PRAGMA data_version').fetchone()[0])
            time.sleep(max(0, expires - time.time()) + .02)
            versions.append(case.conn.execute('PRAGMA data_version').fetchone()[0])
            assert time.time() > expires
        with f.schedule(case, wait_for_real_expiry) as seen:
            out = f.call(case)
        assert seen and len(set(versions)) == 1, 'TTL_schedule_performed_SQL_write'
        assert out['fail'] == 1 and case.calls['post'] == case.calls['put'] == 0
        assert case.conn.execute('SELECT expires_at FROM episodic_turns WHERE id=?', (eid,)).fetchone()[0] == expires
        case._emit({'event': 'absolute_TTL_crossed_without_SQL', 'before_after_data_version': versions,
            'actual_wall_clock_crossing': True, 'embedding_POSTs': case.calls['post']})


def test_original_ABA_namespace(episode_embedding_case):
    with f.Fixture('ownership') as case:
        eid = f.capture(case)
        def ABA():
            before = tuple(case.conn.execute('SELECT * FROM episodic_turns WHERE id=?', (eid,)).fetchone())
            writer = sqlite3.connect(str(case.path))
            try:
                writer.execute("UPDATE episodic_turns SET owner_bot_id='foreign-owner' WHERE id=?", (eid,))
                writer.execute('UPDATE episodic_turns SET owner_bot_id=? WHERE id=?', (case.bot_id, eid))
                writer.commit()
            finally:
                writer.close()
            assert tuple(case.conn.execute('SELECT * FROM episodic_turns WHERE id=?', (eid,)).fetchone()) == before
        with f.schedule(case, ABA) as seen:
            assert f.call(case)['fail'] == 1
        assert seen and case.calls['post'] == case.calls['put'] == 0
        # Original request home is independently retained; matching row text is
        # not permission to adopt a different native request namespace.
        with f.admission(case, eid) as source:
            assert source.finish()
            foreign = case.home.parent / 'foreign-home'
            foreign.mkdir()
            token = case._native.set_hermes_home_override(foreign)
            request_token = case.m._REQUEST_HOME.set(str(foreign))
            try:
                with pytest.raises(case.m._DeliveryWithheld):
                    source.admit_episode_index()
            finally:
                case.m._REQUEST_HOME.reset(request_token)
                case._native.reset_hermes_home_override(token)
        assert case.calls['post'] == 0


def test_pending_erasure(episode_embedding_case):
    with f.Fixture('pending') as case:
        eid = f.capture(case)
        with f.schedule(case, lambda: f.erasure_intent(case, eid)) as seen:
            out = f.call(case)
        assert seen and out['fail'] == 1 and case.calls['post'] == case.calls['put'] == 0
        assert len(case.p._privacy_erasure._load_unlocked()) == 1
        applied = case.conn.execute("SELECT value FROM meta WHERE key='privacy_erasure_applied_seq'").fetchone()
        assert (int(applied[0]) if applied else 0) == 0, 'dispatch_replayed_or_reanchored_erasure'
        assert case.conn.execute('SELECT 1 FROM episodic_turns WHERE id=?', (eid,)).fetchone()


@pytest.mark.parametrize('kind', ['id', 'text'])
def test_applied_erasure_policy(episode_embedding_case, kind):
    with f.Fixture('applied') as case:
        eid = f.capture(case)
        twin = f.capture(case, session='another-host-chat')
        # Authored old-restore inconsistency against genuine MAC/owner/text
        # policy. The genuine producer already created both rows and hints.
        entry = f.erasure_intent(case, eid, kind, applied=True)
        own = case.conn.execute('SELECT * FROM episodic_turns WHERE id=?', (eid,)).fetchone()
        other = case.conn.execute('SELECT * FROM episodic_turns WHERE id=?', (twin,)).fetchone()
        assert case.p._privacy_erasure._owner_allows(entry['owner'], own, 'episode')
        assert not case.p._privacy_erasure._owner_allows(entry['owner'], other, 'episode')
        if kind == 'text':
            # Real replay's word boundary and older-only cutoff, not claim normalization.
            ledger = case.p._privacy_erasure
            surface = case.m._episodic_memory._removal_surface(f.TEXT)
            assert ledger._contains_digest(surface, entry['episode_text'], 'episode-text', boundary=True)
            assert not ledger._contains_digest('prefix' + surface + 'suffix', entry['episode_text'], 'episode-text', boundary=True)
        out = f.call(case, 2)
        assert out['ok'] == out['fail'] == 1
        assert case.calls['post'] == case.calls['put'] == 1  # Other chat remains legal.
        assert case.conn.execute('SELECT COUNT(*) FROM episodic_turns').fetchone()[0] == 2
        if kind == 'text':
            # A newer genuine capture survives a phrase tombstone. Change only
            # its timestamp/hint to represent a post-intent host turn without a
            # clock replacement or waiting a whole second.
            newer = f.capture(case, text=f.TEXT + ' Later legitimate host turn.')
            created = int(entry['created_at']) + 1
            f.edit(case, newer, created_at=created)
            f.update_hint(case, newer, created_at=created)
            assert f.call(case, 10)['ok'] == 1 and case.calls['post'] == 2


def test_response_cache_separate_callers(episode_embedding_case):
    with f.Fixture('response-cache') as case:
        eid = f.capture(case)
        f.enable_cache(case)
        with f.schedule(case, lambda: f.erase(case, eid), seam='response') as seen:
            out = f.call(case)
        assert seen and out['fail'] == 1 and case.calls['post'] == 1  # Already received response counts.
        assert case.calls['put'] == 0
        state = case.m._embedding_cache_state()
        assert not state['cache'] and not state['flights']
        first = f.capture(case, turn='cache_first')
        twin = f.capture(case, turn='cache_twin', session='another-host-chat')
        with f.admission(case, first) as original:
            assert case.m._embed_document(f.TEXT, _admit=original.admit_episode_index) == f.VECTOR
        with f.admission(case, first) as original:
            assert case.m._embed_document(f.TEXT, _admit=original.admit_episode_index) == f.VECTOR
            stored = next(iter(state['cache'].values()))
            with f.at(case, case.m._stage_receipt.__code__, lambda fr, ev, a:
                    ev == 'return' and fr.f_locals.get('status') == 'cache_hit',
                    lambda: f.edit(case, first, owner_bot_id='foreign-owner')) as hit:
                with pytest.raises(case.m._DeliveryWithheld):
                    case.m._embed_document(f.TEXT, _admit=original.admit_episode_index)
        assert hit and next(iter(state['cache'].values())) is stored
        with f.admission(case, twin) as other:
            assert case.m._embed_document(f.TEXT, _admit=other.admit_episode_index) == f.VECTOR
        assert case.calls['post'] == 2  # Same-text new caller uses data, not old authority.
        assert all(not callable(value) for entry in state['cache'].values() for value in entry)


def test_singleflight_original_waiter(episode_embedding_case):
    with f.Fixture('waiter') as case:
        first = f.capture(case)
        twin = f.capture(case, session='another-host-chat')
        f.enable_cache(case)
        started, release = threading.Event(), threading.Event()
        results, errors = [], []
        def hold():
            started.set()
            assert release.wait(4)
        case.on_post = hold
        # Admission's lease writer must not use the main-thread provider handle.
        # Reserve both leases before starting the genuine context-propagating thread.
        for eid in (first, twin):
            case.conn.execute("UPDATE index_outbox SET status='processing',worker_id='episode-source-worker',lease_until=? WHERE object_id=?", (int(time.time()) + 120, eid))
        case.conn.commit()
        payload = json.loads(f.queue(case, first)['payload_json'])
        rowid = f.queue(case, first)['id']
        def producer():
            try:
                with case.m._DisclosureFence.episode_worker(case.m, str(case.path)) as source:
                    snapshot = case.m._load_active_episode_index_snapshot(str(case.path), first, _disclosure=source)
                    source.index_episode(snapshot, payload, outbox_id=rowid, worker_id='episode-source-worker')
                    results.append(case.m._embed_document(f.TEXT, _admit=source.admit_episode_index))
            except BaseException as exc:
                errors.append(type(exc).__name__)
        from agent.memory_provider import spawn_context_thread
        worker = spawn_context_thread(producer, name='episode-source-singleflight')
        # Prepare waiter before producer: admission's lease write changes epoch.
        with f.admission(case, twin) as waiter:
            worker.start()
            try:
                assert started.wait(4)
                def retire_waiter():
                    worker.join(4)
                    assert not worker.is_alive() and errors == []
                    f.edit(case, twin, owner_bot_id='foreign-owner')
                with f.at(case, case.m._hybrid_note.__code__, lambda fr, ev, a:
                        ev == 'return' and fr.f_locals.get('outcome') == 'waiter', release.set) as waiting:
                    with f.at(case, case.m._stage_receipt.__code__, lambda fr, ev, a:
                            ev == 'return' and fr.f_locals.get('status') == 'coalesced', retire_waiter) as retired:
                        with pytest.raises(case.m._DeliveryWithheld):
                            case.m._embed_document(f.TEXT, _admit=waiter.admit_episode_index)
                assert waiting and retired
            finally:
                release.set()
                worker.join(5)
        assert not worker.is_alive() and errors == [] and results == [f.VECTOR]
        assert case.calls['post'] == 1 and not case.m._embedding_cache_state()['flights']


def test_primary_and_reader_UNKNOWN(episode_embedding_case):
    with f.Fixture('primary') as case:
        eid = f.capture(case)
        f.enable_cache(case)
        primary = BaseException('authored_episode_primary')
        m = case.m
        key = m._embedding_cache_key(f.TEXT, 'search_document')
        replacement = (time.monotonic() + 60, [0.7] * 8)
        foreign_flight = {'event': threading.Event(), 'result': None, 'invalidated': False}
        def abort():
            state = m._embedding_cache_state()
            state['cache'][key] = replacement
            state['flights'][key] = foreign_flight
            raise primary
        with f.admission(case, eid) as source:
            with f.at(case, m._stage_receipt.__code__, lambda fr, ev, a:
                    ev == 'return' and fr.f_locals.get('status') == 'executed', abort) as seen:
                with pytest.raises(BaseException) as caught:
                    m._embed_document(f.TEXT, _admit=source.admit_episode_index)
        assert seen and caught.value is primary
        state = m._embedding_cache_state()
        assert state['cache'][key] is replacement and state['flights'][key] is foreign_flight
        assert not foreign_flight['event'].is_set()
        df = sys.modules[m._DisclosureFence.__module__]
        owned = []
        close_primary = BaseException('authored_episode_close_primary')
        def refuse_close():
            raise BaseException('authored_close_refusal')
        target = f.peer.unwrapped(m._DisclosureFence.episode_worker).__code__
        with f.at(case, target, lambda fr, ev, a: ev == 'c_call'
                and getattr(a, '__name__', None) == 'close'
                and getattr(a, '__self__', None) is (owned[0].conn if owned else None), refuse_close) as closing:
            with pytest.raises(BaseException) as caught:
                with f.admission(case, eid) as source:
                    owned.append(source)
                    raise close_primary
        assert closing and caught.value is close_primary
        assert df._INDEX_READERS_UNKNOWN == [(owned[0].conn, owned[0])]
        assert owned[0].conn.execute('SELECT 1').fetchone()[0] == 1
        assert close_primary.__notes__
        with pytest.raises(m._DeliveryWithheld):
            with m._DisclosureFence.episode_worker(m, str(case.path)):
                raise AssertionError('UNKNOWN_reader_was_replaced')
        case._emit({'event': 'episode_retained_UNKNOWN', 'primary_identity': True,
            'exact_reader_retained': True, 'new_admission_refused': True})
        # Safety close only AFTER observing retained production ownership. No registry clear.
        owned[0].conn.close()


def test_same_Event_deadline(episode_embedding_case):
    with f.Fixture('deadline') as case:
        eid = f.capture(case)
        m = case.m
        for mode in ('cancel', 'deadline'):
            event = threading.Event()
            deadline = time.monotonic() + (4 if mode == 'cancel' else .5)
            req = urllib.request.Request(m.EMBED_URL + '/embeddings', method='POST',
                data=m._semantic_request_bytes({'model': m.EMBED_MODEL, 'dimensions': 8,
                    'input': f.TEXT, 'task_type': 'search_document'}))
            with f.admission(case, eid) as source:
                def is_prepared_admission(frame, ev, arg):
                    parent = frame.f_back
                    outer = parent.f_back if parent else None
                    return (ev == 'return' and arg is True and frame.f_locals.get('self') is source
                        and parent is not None and parent.f_code is m._DisclosureFence.admit_episode_index.__code__
                        and outer is not None and outer.f_code is f.peer.unwrapped(m._observed_semantic_http).__code__)
                def wait_or_cancel():
                    assert m._PREFETCH_LOCAL.cancel_event is event and m._PREFETCH_LOCAL.deadline == deadline
                    if mode == 'cancel':
                        event.set()
                    else:
                        time.sleep(max(0, deadline - time.monotonic()) + .01)
                with m._prefetch_budget(4, event, deadline=deadline):
                    with f.at(case, m._DisclosureFence.finish.__code__, is_prepared_admission, wait_or_cancel) as seen:
                        with pytest.raises(TimeoutError):
                            with m._observed_semantic_http(req, timeout=4, stage='embedding',
                                    _before_dispatch=source.admit_episode_index):
                                raise AssertionError('prepared_dispatch_admitted_after_stop')
                    assert m._PREFETCH_LOCAL.cancel_event is event and m._PREFETCH_LOCAL.deadline == deadline
            assert seen and case.calls['post'] == 0
            case._emit({'event': 'episode_prepared_same_stop', 'mode': mode,
                'same_Event_and_absolute_deadline': True, 'POSTs': case.calls['post']})
