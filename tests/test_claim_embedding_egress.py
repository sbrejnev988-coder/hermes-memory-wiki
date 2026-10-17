"""SOURCE direct-component regressions: original stored-claim embedding admission."""
from __future__ import annotations
import importlib.util
from pathlib import Path
import sys
import sqlite3
import ast
import io
import json
import threading
import time
import urllib.error
import urllib.request
from contextlib import contextmanager

import pytest

_SPEC = importlib.util.spec_from_file_location('claim_embedding_fixture',
    Path(__file__).parent / 'ci_owned/claim_embedding_fixture.py')
f = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = f
_SPEC.loader.exec_module(f)
claim_embedding_case = f.claim_embedding_case


def test_scoped_prepared_retirement(claim_embedding_case):
    with f.Fixture() as case:
        f.seed(case)
        with f.schedule(case) as seen:
            out = f.public(case)
        assert seen == ['prepared'], 'prepared_claim_dispatch_not_reached'
        assert out['status'] == 'scoped_partial' and out['attempts'] == out['failed'] == 1
        assert out['ok_count'] == 0 and out['remaining'] == 1 and out['alias_switched'] is False
        assert case.calls['put'] == 0
        assert case.conn.execute('SELECT COUNT(*) FROM claim_vector_targets').fetchone()[0] == 0
        assert case.conn.execute('SELECT status FROM claims WHERE id=?', (f.CLAIM,)).fetchone()[0] == 'retired'
        # Late public refusal and zero Qdrant PUT do not undo a prior canary POST.
        assert case.calls['post'] == 0, 'revoked_claim_canary_reached_authored_embedding_POST'


@pytest.mark.parametrize('producer', ['scoped', 'full', 'outbox'])
def test_producer_healthy(claim_embedding_case, producer):
    with f.Fixture() as case:
        f.seed(case)
        if producer == 'outbox':
            f.enqueue(case)
        with f.observe_original(case):
            out = f.call(case, producer)
        assert case.calls['post'] == case.calls['put'] == 1
        assert case.posts[0]['input'] == f.TEXT
        assert out['ok_count' if producer != 'outbox' else 'ok'] == 1
        if producer != 'outbox':
            assert out['status'] == ('scoped_completed' if producer == 'scoped' else 'completed')
        assert case.conn.execute("SELECT COUNT(*) FROM claim_vector_targets WHERE status='active'").fetchone()[0] == 1
        if producer == 'outbox':
            assert case.conn.execute('SELECT COUNT(*) FROM index_outbox').fetchone()[0] == 0
            workers = [x for x in case.originals if x.worker is not None]
            assert len(workers) == 1 and workers[0].provider is None
            with pytest.raises(sqlite3.ProgrammingError):
                workers[0].conn.execute('SELECT 1')


@pytest.mark.parametrize('scenario', ['scoped-owner', 'full-ABA', 'outbox-status', 'scoped-lifecycle'])
def test_late_source(claim_embedding_case, scenario):
    producer, action = scenario.split('-')
    with f.Fixture() as case:
        f.seed(case)
        if producer == 'outbox':
            f.enqueue(case)
        with f.schedule(case, action=action) as seen:
            out = f.call(case, producer)
        assert seen and case.calls['post'] == case.calls['put'] == 0
        assert case.conn.execute('SELECT COUNT(*) FROM claim_vector_targets').fetchone()[0] == 0
        if producer == 'outbox':
            assert out['ok'] == 0 and out['fail'] == 1
            assert case.conn.execute('SELECT COUNT(*) FROM index_outbox').fetchone()[0] == 1
        else:
            assert out['ok_count'] == 0 and out['failed'] == 1
        assert f.MARKER not in json.dumps(out)


@pytest.mark.parametrize('scenario', ['scoped-id', 'full-text', 'outbox-pending'])
def test_erasure(claim_embedding_case, scenario):
    producer, kind = scenario.split('-')
    with f.Fixture() as case:
        f.seed(case)
        if producer == 'outbox':
            f.enqueue(case)
        with f.schedule(case, effect=lambda: f.erasure(case, kind)) as seen:
            out = f.call(case, producer)
        assert seen and case.calls['post'] == case.calls['put'] == 0
        assert case.conn.execute('SELECT COUNT(*) FROM claim_vector_targets').fetchone()[0] == 0
        assert len(case.p._privacy_erasure._load_unlocked()) == 1
        assert f.MARKER not in json.dumps(out)


@pytest.mark.parametrize('producer', ['scoped', 'full', 'outbox'])
def test_response_publication(claim_embedding_case, producer):
    with f.Fixture() as case:
        f.seed(case)
        enable_cache(case)
        if producer == 'outbox':
            f.enqueue(case)
        with f.schedule(case, 'response') as seen:
            out = f.call(case, producer)
        assert seen and case.calls['post'] == 1  # Already-issued POST is not undone.
        assert case.calls['put'] == 0
        assert not case.m._embedding_cache_state()['cache']
        assert not case.m._embedding_cache_state()['flights']
        assert case.conn.execute('SELECT COUNT(*) FROM claim_vector_targets').fetchone()[0] == 0
        assert out['ok_count' if producer != 'outbox' else 'ok'] == 0


def test_compatibility(claim_embedding_case):
    with f.Fixture() as case:
        f.seed(case)
        m = case.m
        foreign, text = 'claim-foreign', 'CANARY_FOREIGN_NO_SQL_HYDRATION'
        case.claim(foreign, text=text, visibility='private', origin_bot_id='foreign-owner', origin_session_id='foreign-session')
        case.ready()
        row = case.conn.execute('SELECT * FROM claims WHERE id=?', (foreign,)).fetchone()
        manifest, source = m._manifest_hash(m._embedding_manifest()), m._physical_collection_name()
        payload = m._qdrant_claim_payload(foreign, text, row, manifest_hash=manifest)
        m._record_claim_vector_target(case.conn, foreign, collection=source, manifest_hash=manifest, status='active')
        case.conn.commit()
        case.points[source] = {str(m._qdrant_point_id(foreign)): {
            'id': m._qdrant_point_id(foreign), 'vector': [0.5] * 8, 'payload': payload}}
        out = f.public(case, dry_run=True)
        assert out['status'] == 'scoped_preflight' and out['eligible_count'] == 1
        assert case.calls['post'] == case.calls['put'] == 0
        sql = []
        case.conn.set_trace_callback(sql.append)
        try:
            out = f.public(case, scoped=False)
        finally:
            case.conn.set_trace_callback(None)
        assert out['status'] == 'completed' and case.calls['post'] == 1
        assert text not in json.dumps(case.requests)
        assert not any('SELECT * FROM claims' in s and foreign in s for s in sql)
        copied = case.points[source][str(m._qdrant_point_id(foreign))]
        assert copied['vector'] == [0.5] * 8 and 'claim' not in copied['payload']
        # Healthy matching supplied vector still takes no embedding path.
        f.enqueue(case, operation='upsert', payload={'vector': f.VECTOR,
            'qdrant_payload': {'manifest_hash': manifest, 'vector_text_hash': m.sha(f.TEXT)}})
        before = case.calls['post']
        assert f.call(case, 'outbox')['ok'] == 1 and case.calls['post'] == before
        # Fixed probe, query and episode-shared helper have no stored-claim carrier.
        assert m._embed_query('  needle   query  ') == f.VECTOR
        assert m._embed_for_qdrant('memory-wiki embedding health probe', task_type='search_query') == f.VECTOR
        assert m._embed_document('Authored episode source, not a stored claim.') == f.VECTOR
        assert case.calls['post'] == before + 3
        assert not any(callable(value) for state in m._EMBED_PROFILE_STATES.values()
                       for entry in state['cache'].values() for value in entry)


def enable_cache(case):
    # Explicit non-secret cache feature controls, never an authority override.
    case.m.EMBED_CACHE_MAX_ENTRIES = 8
    case.m.EMBED_DOCUMENT_CACHE_TTL_SECONDS = 60
    case.m._embedding_cache_key(f.TEXT, 'search_document')


def test_cache_originals(claim_embedding_case):
    with f.Fixture() as case:
        f.seed(case)
        f.seed(case, cid='claim-twin')  # Same text is not the same original source.
        enable_cache(case)
        original = f.admission(case)
        assert case.m._embed_document(f.TEXT, _admit=original.admit_index) == f.VECTOR
        assert case.m._embed_document(f.TEXT, _admit=original.admit_index) == f.VECTOR
        assert case.calls['post'] == 1
        key = case.m._embedding_cache_key(f.TEXT, 'search_document')
        stored = case.m._embedding_cache_state()['cache'][key]
        with f.at(case, case.m._stage_receipt.__code__,
                  lambda fr, ev, a: ev == 'return' and fr.f_locals.get('status') == 'cache_hit',
                  lambda: f.changed(case, 'status')) as seen:
            with pytest.raises(case.m._DeliveryWithheld):
                case.m._embed_document(f.TEXT, _admit=original.admit_index)
        assert seen and case.calls['post'] == 1
        assert case.m._embedding_cache_state()['cache'][key] is stored
        twin = f.admission(case, 'claim-twin')
        assert case.m._embed_document(f.TEXT, _admit=twin.admit_index) == f.VECTOR
        assert case.calls['post'] == 1


def test_singleflight_original_waiter(claim_embedding_case):
    with f.Fixture() as case:
        f.seed(case)
        f.seed(case, cid='claim-twin')
        enable_cache(case)
        m = case.m
        started, release = threading.Event(), threading.Event()
        result, errors, worker_fence = [], [], []
        def hold():
            started.set()
            assert release.wait(3), 'authored_POST_barrier_timeout'
        case.on_post = hold
        def produce():
            try:
                with m._DisclosureFence.claim_worker(m, str(case.path)) as source:
                    assert source.index_snapshot(f.CLAIM)['index_text'] == f.TEXT
                    worker_fence.append(source)
                    result.append(m._embed_document(f.TEXT, _admit=source.admit_index))
            except BaseException as exc:
                errors.append(type(exc).__name__)
        from agent.memory_provider import spawn_context_thread
        worker = spawn_context_thread(produce, name='source-embedding-coalescer')
        worker.start()
        try:
            assert started.wait(3)
            waiter = f.admission(case, 'claim-twin')
            def retire_waiter():
                worker.join(3)
                assert not worker.is_alive()
                f.changed(case, 'status', cid='claim-twin')
            with f.at(case, m._hybrid_note.__code__,
                      lambda fr, ev, a: ev == 'return' and fr.f_locals.get('outcome') == 'waiter',
                      release.set) as seen:
                with f.at(case, m._stage_receipt.__code__,
                          lambda fr, ev, a: ev == 'return' and fr.f_locals.get('status') == 'coalesced',
                          retire_waiter) as retired:
                    with pytest.raises(m._DeliveryWithheld):
                        m._embed_document(f.TEXT, _admit=waiter.admit_index)
            assert seen and retired
        finally:
            release.set()
            worker.join(5)
        assert not worker.is_alive() and errors == []
        assert result == [f.VECTOR] and case.calls['post'] == 1
        with pytest.raises(sqlite3.ProgrammingError):
            worker_fence[0].conn.execute('SELECT 1')
        assert not m._embedding_cache_state()['flights']
        assert m._embed_document(f.TEXT, _admit=f.admission(case).admit_index) == f.VECTOR
        assert case.calls['post'] == 1


@pytest.mark.parametrize('mode', ['primary', 'replacement', 'store'])
def test_cache_unwind(claim_embedding_case, mode):
    with f.Fixture() as case:
        f.seed(case)
        enable_cache(case)
        m = case.m
        original = f.admission(case)
        primary = BaseException('authored_primary')
        key = m._embedding_cache_key(f.TEXT, 'search_document')
        replacement, flight = (time.monotonic() + 60, [0.7] * 8), {'event': threading.Event(), 'result': None, 'invalidated': False}
        def abort():
            if mode == 'replacement':
                state = m._embedding_cache_state()
                state['cache'][key] = replacement
                state['flights'][key] = flight
            raise primary
        seam = m._embedding_store_locked.__code__ if mode == 'store' else m._stage_receipt.__code__
        with f.at(case, seam,
                  lambda fr, ev, a: ev == 'return' and (mode == 'store' or fr.f_locals.get('status') == 'executed'), abort) as seen:
            with pytest.raises(BaseException) as caught:
                m._embed_document(f.TEXT, _admit=original.admit_index)
        assert seen and caught.value is primary and case.calls['post'] == 1
        state = m._embedding_cache_state()
        if mode in {'primary', 'store'}:
            assert not state['cache'] and not state['flights']
            assert m._embed_document(f.TEXT, _admit=f.admission(case).admit_index) == f.VECTOR
        else:
            assert state['cache'][key] is replacement and state['flights'][key] is flight
            assert not flight['event'].is_set()  # Never finish somebody else's flight.


class AuthoredStdin(io.BytesIO):
    def close(self):
        if not self.closed:
            self.received = self.getvalue()
        super().close()


class AuthoredProcess:
    """Only three BytesIO pipes. No native child or OS containment claim."""
    def __init__(self):
        self.stdin = AuthoredStdin()
        self.stdout = io.BytesIO(json.dumps({'data': [{'embedding': f.VECTOR}]}).encode())
        self.stderr = io.BytesIO()
        self.returncode = 0
    def poll(self):
        return self.returncode
    def wait(self, timeout):
        return self.returncode
    def kill(self):
        self.returncode = -1


def command(case):
    return ['curl', '--disable', '--silent', '--show-error', '--max-time', '1.0',
            '--request', 'POST', '--url', case.m.EMBED_URL + '/embeddings', '--config', '-']


@pytest.mark.parametrize('transport', ['http', 'curl'])
def test_deadline_during_admission(claim_embedding_case, transport):
    with f.Fixture() as case:
        f.seed(case)
        original = f.admission(case)
        m = case.m
        event = threading.Event()
        deadline = time.monotonic() + 0.6
        req = urllib.request.Request(m.EMBED_URL + '/embeddings',
            data=m._semantic_request_bytes({'model': m.EMBED_MODEL, 'dimensions': 8,
                'input': f.TEXT, 'task_type': 'search_document'}), method='POST')
        factories = []
        def factory(*a, **kw):
            factories.append(a)
            return AuthoredProcess()
        def expire():
            assert m._PREFETCH_LOCAL.cancel_event is event and m._PREFETCH_LOCAL.deadline == deadline
            if transport == 'http':
                event.set()
            else:
                time.sleep(max(0, deadline - time.monotonic()) + .01)
        with m._prefetch_budget(1, event, deadline=deadline):
            with f.at(case, m._DisclosureFence.finish.__code__,
                      lambda fr, ev, a: ev == 'return' and a is True,
                      expire) as seen:
                with pytest.raises(TimeoutError):
                    if transport == 'http':
                        with m._observed_semantic_http(req, timeout=1, stage='embedding', _before_dispatch=original.admit_index):
                            raise AssertionError('adapter_admitted_after_cancel')
                    else:
                        m._semantic_curl_capture(command(case), b'data = "prepared"\n', 1,
                            check=lambda: m._semantic_io_check('embedding'),
                            _before_factory=original.admit_index, _popen=factory)
        assert seen and not factories and case.calls['post'] == 0


def test_shared_remote_composition(claim_embedding_case):
    with f.Fixture() as case:
        f.seed(case)
        m = case.m
        original = f.admission(case)
        # Key-free actual shared HTTP seam; NOT a remote-key provider integration.
        req = urllib.request.Request(m.EMBED_URL + '/embeddings', data=m._semantic_request_bytes(
            {'model': m.EMBED_MODEL, 'dimensions': 8, 'input': f.TEXT, 'task_type': 'search_document'}), method='POST')
        case.failure = urllib.error.URLError('authored_retryable_failure')
        with pytest.raises(urllib.error.URLError):
            with m._observed_semantic_http(req, timeout=1, stage='embedding', _before_dispatch=original.admit_index):
                pass
        case.failure = None
        f.changed(case, 'status')
        with pytest.raises(m._DeliveryWithheld):
            with m._observed_semantic_http(req, timeout=1, stage='embedding', _before_dispatch=original.admit_index):
                pass
        assert case.calls['post'] == 1
        # Actual curl_capture (_popen only), with a different, eligible claim.
        f.seed(case, cid='claim-curl')
        source = f.admission(case, 'claim-curl')
        procs, commands = [], []
        def factory(cmd, **kw):
            commands.append(cmd)
            proc = AuthoredProcess()
            procs.append(proc)
            return proc
        config = ('data = "' + json.dumps({'input': f.TEXT}).replace('"', '\\"') + '"\n').encode()
        raw = m._semantic_curl_capture(command(case), config, 1,
            check=lambda: m._semantic_io_check('embedding'), _before_factory=source.admit_index, _popen=factory)
        assert m._semantic_json_body(raw)['data'][0]['embedding'] == f.VECTOR
        assert len(procs) == 1 and float(commands[0][5]) <= 1
        assert f.MARKER.encode() in procs[0].stdin.received
        assert all(getattr(procs[0], name).closed for name in ('stdin', 'stdout', 'stderr'))
        # A genuine missing owner-local keyed health route still refuses. This
        # is not a healthy keyed-route proof (no key may be authored here).
        assert m._health_owner_route_snapshot() is None
        with m._prefetch_health_scope(time.monotonic() + 1, threading.Event(),
                lambda: m._health_owner_route_current(None)):
            with pytest.raises(m._SemanticIOError) as health:
                with m._observed_semantic_http(req, timeout=1, stage='embedding', _before_dispatch=source.admit_index):
                    pass
            assert health.value.code == 'health_owner_changed'
        f.changed(case, 'owner', cid='claim-curl')
        with pytest.raises(m._DeliveryWithheld):
            m._semantic_curl_capture(command(case), config, 1,
                check=lambda: m._semantic_io_check('embedding'), _before_factory=source.admit_index, _popen=factory)
        assert len(procs) == 1
        # Static forwarding of ORIGINAL callback at every key-required branch;
        # no key, missing-key guard override, fake provider or curl execution.
        tree = ast.parse((f.SOURCE / '__init__.py').read_bytes())
        funcs = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
        for owner, callee, keyword in (
            ('_embed_document', '_openrouter_embed', '_admit'),
            ('_embed_document', '_embed_for_qdrant', '_admit'),
            ('_embed_document', '_embedding_cached_call', '_admit'),
            ('_embed_for_qdrant', '_embed_req', '_admit'),
            ('_embed_req', '_observed_semantic_http', '_before_dispatch'),
            ('_openrouter_embed', '_observed_semantic_http', '_before_dispatch'),
            ('_openrouter_embed', '_http_json_via_curl', '_admit'),
            ('_http_json_via_curl', '_semantic_curl_capture', '_before_factory')):
            calls = [n for n in ast.walk(funcs[owner]) if isinstance(n, ast.Call)
                     and isinstance(n.func, ast.Name) and n.func.id == callee]
            assert calls and all(any(k.arg == keyword and isinstance(k.value, ast.Name)
                and k.value.id == '_admit' for k in n.keywords) for n in calls)
        assert not m._embed_api_key()
        assert m._openrouter_embed(f.TEXT, input_type='search_document', _admit=source.admit_index) is None
        case._emit({'event': 'remote_scope', 'remote_full_provider_chains': 'NOT_RUN_KEY_REQUIRED',
                    'actual_keyfree_HTTP_and_curl_capture': True, 'forwarding': 'STATIC_SOURCE'})


def test_worker_reader_unknown(claim_embedding_case):
    with f.Fixture() as case:
        f.seed(case)
        m = case.m
        df = sys.modules[m._DisclosureFence.__module__]
        primary, cleanup = BaseException('authored_primary'), BaseException('authored_close_refusal')
        target = f.peer.unwrapped(m._DisclosureFence.claim_worker).__code__
        owned = []
        def refuse_close():
            raise cleanup
        with f.at(case, target, lambda fr, ev, a: ev == 'c_call'
                  and getattr(a, '__name__', None) == 'close'
                  and getattr(a, '__self__', None) is (owned[0].conn if owned else None), refuse_close) as seen:
            with pytest.raises(BaseException) as caught:
                with m._DisclosureFence.claim_worker(m, str(case.path)) as source:
                    owned.append(source)
                    assert source.index_snapshot(f.CLAIM)['index_text'] == f.TEXT
                    assert source.conn.execute('PRAGMA query_only').fetchone()[0] == 1
                    raise primary
        assert seen and caught.value is primary
        assert df._INDEX_READERS_UNKNOWN == [(owned[0].conn, owned[0])]
        assert owned[0].conn.execute('SELECT 1').fetchone()[0] == 1
        assert 'claim_index_reader_cleanup_UNKNOWN' in primary.__notes__
        with pytest.raises(m._DeliveryWithheld):
            with m._DisclosureFence.claim_worker(m, str(case.path)):
                raise AssertionError('UNKNOWN_reader_was_replaced')
        case._emit({'event': 'retained_reader_unknown', 'primary_preserved': True,
                    'exact_owner_retained': True, 'still_queryable': True})
        # Explicit fixture safety close AFTER the retained production snapshot;
        # do not clear the registry or claim that production recovered.
        owned[0].conn.close()
        assert len(df._INDEX_READERS_UNKNOWN) == 1


def test_full_indexing_policy(claim_embedding_case):
    with f.Fixture() as case:
        f.seed(case, quality=0.0, expires_at=1, trust_class='tool_log', type='source_artifact')
        out = f.public(case, scoped=False)
        assert out['status'] == 'completed' and case.calls['post'] == 1
        # Do not reanchor across the visibility callback BEFORE hydration.
        visible = type(case.p)._claim_visible.__code__
        with f.at(case, visible,
                  lambda fr, ev, a: ev == 'return' and a is True and fr.f_back is not None
                  and fr.f_locals.get('__name') == '_claim_visible'
                  and fr.f_back.f_code.co_name == 'index_row', lambda: f.changed(case, 'ABA')) as seen:
            out = f.public(case, scoped=False, force=True)
        assert seen and case.calls['post'] == 1 and out['failed'] == 1
