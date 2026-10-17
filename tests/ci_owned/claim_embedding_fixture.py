"""Stored-claim peer: real direct SPI/SQLite, authored external HTTP only.

Reuse the accepted no-file, key-free LLM/document fixture initialization and
ownership. No MemoryManager/bootstrap/SDK client, model, socket or curl child.
"""
from __future__ import annotations
from contextlib import contextmanager
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import urllib.parse

import pytest

_SPEC = importlib.util.spec_from_file_location(
    'claim_embedding_llm_peer', Path(__file__).with_name('llm_pack_egress_fixture.py'))
llm = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = llm
_SPEC.loader.exec_module(llm)
peer = llm.peer
SOURCE = Path(__file__).resolve().parents[2]
CLAIM = 'claim-embedding-own'
MARKER = 'CANARY_CLAIM_EMBEDDING_OWN'
TEXT = MARKER + ' ' + peer.QUERY + ' ' + peer.SAFE
VECTOR = [0.1, 0.2] + [0.0] * 6


@pytest.fixture
def claim_embedding_case(request, tmp_path_factory):
    assert peer._ACTIVE is None
    ordinary = sys.modules['memory_wiki']
    assert Path(ordinary.__file__).resolve() == SOURCE / '__init__.py'
    token = hashlib.sha256(request.node.nodeid.encode()).hexdigest()[:16]
    root = tmp_path_factory.mktemp('document-egress-' + token, numbered=False)
    peer.no_links(root)
    control = root / 'diagnostics/controls' / token
    control.mkdir(parents=True, exist_ok=False)
    peer._ACTIVE = {'root': control, 'ordinary': ordinary}
    try:
        yield
    finally:
        peer._ACTIVE = None


class Fixture(llm.Fixture):
    def __init__(self, label='case'):
        super().__init__(label)
        self.points = {}
        self.requests = []
        self.on_post = None
        self._auxiliary = []
        self.calls.update(put=0, delete=0, scroll=0)

    def __enter__(self):
        # Legacy outbox snapshot/context-manager helpers end transactions but
        # do not close every SQLite handle. Own those genuine fixture resources
        # explicitly (as the shipped provider lifecycle helper does); never
        # change results/guards or rely on GC before Windows fixture archival.
        connect = sqlite3.connect
        def owned_connect(*args, **kwargs):
            conn = connect(*args, **kwargs)
            self._auxiliary.append(conn)
            return conn
        self._mp.setattr(sqlite3, 'connect', owned_connect)
        # Before import and all route ContextVar captures; not a dummy key or a
        # profile_ready override. Super initializes with semantic work disabled.
        for key, value in {
            'MEMORY_WIKI_EMBED_URL': 'http://127.0.0.1:18647/v1',
            'MEMORY_WIKI_QDRANT_URL': 'http://127.0.0.1:18648',
            'MEMORY_WIKI_QDRANT_COLLECTION': 'source_claims',
            'MEMORY_WIKI_EPISODIC_QDRANT_COLLECTION': 'source_episodes',
            'MEMORY_WIKI_QDRANT_ALIAS': 'source_alias',
            'MEMORY_WIKI_QDRANT_ALIAS_MODE': 'physical',
        }.items():
            self._mp.setenv(key, value)
        super().__enter__()
        m = self.m
        native = sys.modules['hermes_constants']
        assert m._set_native_home is native.set_hermes_home_override
        assert m._IMPORT_HERMES_HOME == self.home
        assert self.p._privacy_erasure.dir == self.p.root / 'privacy-erasure'
        assert self.p._privacy_erasure._load_unlocked() == []
        assert self.p._runtime_identity()['profile_ready'] is True
        self.semantic_enabled = True  # Supported feature opt-in after initialize.
        self._emit({'event': 'claim_fixture_ready', 'native_home_setter_identity': True,
                    'native_MRO': [c.__module__ + '.' + c.__qualname__ for c in type(self.p).__mro__],
                    'existing_ledger': True, 'key_free_stub': True})
        return self

    def _finish(self, primary):
        for conn in self._auxiliary:
            if conn is self.conn:
                continue  # The real provider shutdown owns this handle.
            try:
                pending = conn.in_transaction
            except sqlite3.ProgrammingError:
                continue  # Already proved closed, including our readonly source.
            if pending:
                raise RuntimeError('fixture_auxiliary_transaction_ownership_UNKNOWN')
            df = sys.modules.get(self.m._DisclosureFence.__module__) if self.m is not None else None
            if df is not None and any(c is conn for c, _ in df._INDEX_READERS_UNKNOWN):
                raise RuntimeError('fixture_does_not_close_retained_UNKNOWN_reader')
            conn.close()
        super()._finish(primary)

    def transport(self, request, timeout):
        assert timeout > 0
        assert not request.has_header('Authorization')
        url, method = request.full_url, request.get_method()
        body = json.loads(request.data) if request.data is not None else None
        self.requests.append((method, url, body))
        m = self.m
        if url == m.EMBED_URL + '/health' and method == 'GET':
            self.calls['health'] += 1
            payload = {'status': 'ok', 'algorithm': 'character-ngram-hashing',
                       'model': m.EMBED_MODEL, 'vector_size': 8}
        elif url == m.EMBED_URL + '/embeddings' and method == 'POST':
            assert body['dimensions'] == 8 and body['model'] == 'hash-ngram-8'
            self.posts.append(body)
            self.calls['post'] += 1
            self.calls['embed'] += 1
            self._emit({'event': 'authored_embedding_POST', 'post': self.calls['post'],
                        'canary': MARKER in body['input'], 'task': body.get('task_type')})
            if self.on_post is not None:
                self.on_post()
            if self.failure is not None:
                raise self.failure
            payload = {'data': [{'embedding': VECTOR}]}
        elif url.startswith(m._qdrant_url() + '/'):
            path = urllib.parse.urlsplit(url).path
            self.calls['qdrant_metadata'] += 1
            if path == '/collections' and method == 'GET':
                payload = {'status': 'ok', 'result': {'collections': [
                    {'name': m._physical_collection_name()}]}}
            elif path == '/aliases' and method == 'GET':
                payload = {'status': 'ok', 'result': {'aliases': []}}
            else:
                parts = path.split('/')
                assert parts[1] == 'collections' and m._profile_target_allowed(parts[2])
                coll = parts[2]
                points = self.points.setdefault(coll, {})
                if len(parts) == 3 and method == 'GET':
                    payload = {'status': 'ok', 'result': {'points_count': len(points),
                        'payload_schema': {}, 'config': {'params': {
                            'vectors': {'size': 8, 'distance': 'Cosine'}}}}}
                elif len(parts) == 4 and parts[3] == 'index' and method == 'PUT':
                    payload = {'status': 'ok', 'result': {'status': 'completed'}}
                elif path.endswith('/points') and method == 'PUT':
                    self.calls['put'] += 1
                    for point in body['points']:
                        points[str(point['id'])] = point
                    payload = {'status': 'ok', 'result': {'status': 'completed'}}
                elif path.endswith('/points') and method == 'POST':
                    selected = body['with_payload']
                    result = []
                    for pid in body['ids']:
                        item = points.get(str(pid))
                        if item is not None:
                            result.append({'id': item['id'], 'payload': dict(item['payload']) if selected is True
                                else {k: v for k, v in item['payload'].items() if k in selected},
                                **({'vector': item['vector']} if body.get('with_vector') else {})})
                    payload = {'status': 'ok', 'result': result}
                elif path.endswith('/points/scroll') and method == 'POST':
                    self.calls['scroll'] += 1
                    assert 'claim' not in body['with_payload']
                    payload = {'status': 'ok', 'result': {'points': [
                        {'id': item['id'], 'payload': {k: v for k, v in item['payload'].items()
                            if k in body['with_payload']}} for item in points.values()],
                        'next_page_offset': None}}
                elif path.endswith('/points/delete') and method == 'POST':
                    self.calls['delete'] += 1
                    for pid in body['points']:
                        points.pop(str(pid), None)
                    payload = {'status': 'ok', 'result': {'status': 'completed'}}
                else:
                    self.calls['unexpected'] += 1
                    raise AssertionError('unregistered_authored_Qdrant_request')
        else:
            self.calls['unexpected'] += 1
            raise AssertionError('unregistered_authored_transport')
        stream = peer.Stream(payload)
        self.streams.append(stream)
        return stream


def seed(f, *, cid=CLAIM, text=TEXT, **changes):
    f.claim(cid, text=text, visibility='bot', topic='general', **changes)
    f.ready()


def changed(f, action, cid=CLAIM):
    if action == 'lifecycle':
        f.p.on_session_switch('another-session', reset=False)
        return
    writer = sqlite3.connect(str(f.path))
    try:
        if action == 'status':
            cur = writer.execute("UPDATE claims SET status='retired' WHERE id=?", (cid,))
        elif action == 'owner':
            cur = writer.execute("UPDATE claims SET origin_bot_id='foreign-owner' WHERE id=?", (cid,))
        elif action == 'ABA':
            before = writer.execute('SELECT * FROM claims WHERE id=?', (cid,)).fetchone()
            cur = writer.execute("UPDATE claims SET origin_bot_id='foreign-owner' WHERE id=?", (cid,))
            writer.execute('UPDATE claims SET origin_bot_id=? WHERE id=?', (f.bot_id, cid))
            assert writer.execute('SELECT * FROM claims WHERE id=?', (cid,)).fetchone() == before
        else:
            raise AssertionError('unregistered_change')
        assert cur.rowcount == 1
        writer.commit()
    finally:
        writer.close()
    f._emit({'event': 'source_changed', 'action': action, 'post_before_change': f.calls['post']})


@contextmanager
def schedule(f, seam='prepared', action='status', *, effect=None):
    encoder = f.m._semantic_request_bytes.__code__
    embed_req = f.m._embed_req.__code__
    response = f.m._semantic_response_json.__code__
    seen = []
    prior = sys.getprofile()

    def inject(frame, event, arg):
        parent = frame.f_back
        if (not seen and event == 'return' and parent is not None
                and parent.f_code is embed_req
                and ((seam == 'prepared' and frame.f_code is encoder
                      and isinstance(frame.f_locals.get('body'), dict)
                      and frame.f_locals['body'].get('task_type') == 'search_document')
                     or (seam == 'response' and frame.f_code is response
                         and parent.f_locals.get('method') == 'POST'
                         and parent.f_locals.get('path') == '/embeddings'))):
            seen.append(seam)
            f._emit({'event': 'scheduled_claim_change', 'seam': seam, 'action': action,
                     'post_before_change': f.calls['post']})
            effect() if effect is not None else changed(f, action)
        if prior is not None:
            prior(frame, event, arg)
    sys.setprofile(inject)
    try:
        yield seen
    finally:
        sys.setprofile(prior)


def public(f, *, scoped=True, **options):
    out = json.loads(f.p.handle_tool_call('memory_wiki_reindex',
        {'current_scope_only': scoped, **options}))
    f._emit({'event': 'public_reindex_return', 'output': out, 'calls': dict(f.calls),
             'queue': f.conn.execute('SELECT COUNT(*) FROM index_outbox').fetchone()[0],
             'targets': f.conn.execute('SELECT COUNT(*) FROM claim_vector_targets').fetchone()[0]})
    return out


def enqueue(f, *, cid=CLAIM, payload=None, operation='embed_and_upsert'):
    payload = {'text': 'UNTRUSTED_QUEUED_TEXT_NOT_THE_CLAIM', **(payload or {})}
    oid = f.m._outbox_enqueue(operation, 'claim', cid, payload, conn=f.conn)
    f.conn.commit()
    assert oid and f.conn.execute('SELECT COUNT(*) FROM index_outbox WHERE id=?', (oid,)).fetchone()[0] == 1
    return oid


def call(f, producer):
    if producer != 'outbox':
        return public(f, scoped=producer == 'scoped')
    out = f.m._outbox_process(1, db_path=str(f.path), worker_id='source-worker')
    f._emit({'event': 'outbox_return', 'output': out, 'calls': dict(f.calls),
             'queue': [dict(r) for r in f.conn.execute('SELECT status,attempts,last_error,worker_id,lease_until FROM index_outbox')],
             'targets': f.conn.execute('SELECT COUNT(*) FROM claim_vector_targets').fetchone()[0]})
    return out


def admission(f, cid=CLAIM, purpose='full_reindex'):
    original = f.m._DisclosureFence(f.p, f.conn)
    row = f.conn.execute('SELECT id FROM claims WHERE id=?', (cid,)).fetchone()
    original.index_claim(row, purpose)
    assert original.ok and original.finish()
    return original


@contextmanager
def at(f, target, predicate, effect):
    prior, seen = sys.getprofile(), []
    def inject(frame, event, arg):
        if frame.f_code is target and not seen and predicate(frame, event, arg):
            seen.append(True)
            effect()
        if prior is not None:
            prior(frame, event, arg)
    sys.setprofile(inject)
    try:
        yield seen
    finally:
        sys.setprofile(prior)


@contextmanager
def observe_original(f):
    cls = f.m._DisclosureFence
    dispatch = peer.unwrapped(f.m._observed_semantic_http).__code__
    prior = sys.getprofile()
    originals, reads, sent, checks = [], [], [], []
    def observe(frame, event, arg):
        if event == 'return' and frame.f_code is cls.__init__.__code__:
            originals.append(frame.f_locals['self'])
        if event == 'call' and frame.f_code is f.m._embed_document.__code__:
            bound = frame.f_locals.get('_admit')
            original = getattr(bound, '__self__', None)
            reads.append(original)
            assert original in originals and original.purposes
            assert any(key[0] == 'claims' for key in original.selectors)
        if event == 'call' and frame.f_code is cls.admit_index.__code__:
            original = frame.f_locals['self']
            assert not f.m._EMBED_CACHE_LOCK._is_owned(), 'source_SQL_inside_cache_lock'
            checks.append(id(original))
        if event == 'call' and frame.f_code is dispatch:
            bound = frame.f_locals.get('_before_dispatch')
            if bound is not None:
                original = getattr(bound, '__self__', None)
                assert original in reads
                sent.append(id(original))
        if prior is not None:
            prior(frame, event, arg)
    sys.setprofile(observe)
    try:
        yield
    finally:
        sys.setprofile(prior)
        f.originals = originals
        f._emit({'event': 'original_source_handoff', 'captures': len(originals),
                 'embed_originals': [originals.index(x) for x in reads],
                 'dispatch_originals': len(sent), 'original_checks': len(checks),
                 'worker_readonly': [x.worker is not None for x in reads]})


def erasure(f, kind):
    ledger = f.p._privacy_erasure
    # append calls the genuine principal mapper -> _meta_text -> _connect.
    # Register the real owning transaction, never raw BEGIN on the provider.
    with f.p._claim_transaction(f.conn):
        seq = ledger.append(f.p, f.m.normalize_claim(TEXT) if kind == 'text' else '',
            claim_ids=[CLAIM] if kind == 'id' else [], event_ids=[], episode_ids=[], episode_surface='')
    # No replay/create in final admission; leave the durable intent pending.
    entries = ledger._load_unlocked()
    assert seq == len(entries) == 1
    row = f.conn.execute('SELECT * FROM claims WHERE id=?', (CLAIM,)).fetchone()
    assert ledger._owner_allows(entries[0]['owner'], row, 'claim')
    if kind == 'id':
        assert ledger.digest('claim-id', CLAIM) in entries[0]['claims']
    if kind == 'text':
        assert ledger._contains_digest(f.m.normalize_claim(TEXT).casefold(), entries[0]['claim_text'], 'claim-text')
    applied = f.conn.execute("SELECT value FROM meta WHERE key='privacy_erasure_applied_seq'").fetchone()
    f._emit({'event': 'authenticated_erasure_intent', 'kind': kind, 'seq': seq,
             'applied': int(applied[0]) if applied else 0})
