"""Episode SOURCE peer: genuine capture/backfill, SPI, SQL and erasure authority.

The host text/session and wake receiver are authored SOURCE roles. The receiver
only records the producer's supported scheduling calls, forwarding all other
operations to the real module; no product scheduler/guard/SDK is monkeypatched.
HTTP is the existing bounded, key-free claim peer, not a socket/model service.
"""
from __future__ import annotations
from contextlib import contextmanager
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import time

import pytest

_SPEC = importlib.util.spec_from_file_location('episode_claim_peer',
    Path(__file__).with_name('claim_embedding_fixture.py'))
claim = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = claim
_SPEC.loader.exec_module(claim)
peer = claim.peer
SOURCE = Path(__file__).resolve().parents[2]
MARKER = 'CANARY_EPISODE_EMBEDDING_OWN'
TEXT = MARKER + ' ' + peer.QUERY + ' ' + peer.SAFE
VECTOR = claim.VECTOR
at = claim.at


@pytest.fixture
def episode_embedding_case(request, tmp_path_factory):
    """Shipped default scratch layout; no external test-root environment needed."""
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


class ProducerReceiver:
    """Authored scheduling receiver, NOT a provider or permission validator."""
    def __init__(self, case):
        self.case = case
        self.wakes = []
    def __getattr__(self, name):
        return getattr(self.case.m, name)
    def _start_outbox_worker(self, path):
        assert Path(path) == self.case.path
        self.wakes.append(('start', str(path)))
    def _wake_outbox_worker(self, path):
        assert Path(path) == self.case.path
        self.wakes.append(('wake', str(path)))


class Fixture(claim.Fixture):
    def __enter__(self):
        super().__enter__()
        # These readers are live feature opt-ins, not import-time route settings.
        # Initialize stayed offline; the key-free route preceded import/scopes.
        self._mp.setenv('MEMORY_WIKI_EPISODIC_ENABLED', '1')
        self._mp.setenv('MEMORY_WIKI_EPISODIC_SEMANTIC', '1')
        self._mp.setenv('MEMORY_WIKI_EPISODIC_SCOPE', 'chat')
        assert self.m._episodic_semantic_enabled()
        self.receiver = ProducerReceiver(self)
        self._emit({'event': 'episode_fixture_ready', 'roles': {
            'host_payload_and_wake_receiver': 'AUTHORED_SOURCE',
            'producer_worker_SPI_home_SQL_ledger_validator': 'GENUINE_DIRECT_COMPONENT',
            'transport': 'AUTHORED_BOUNDED_STREAM_NO_SOCKET_MODEL'}})
        return self

    def transport(self, request, timeout):
        response = super().transport(request, timeout)
        if request.get_method() == 'POST' and request.full_url == self.m.EMBED_URL + '/embeddings':
            self._emit({'event': 'episode_authored_POST_received',
                'post': self.calls['post'], 'canary': MARKER in self.posts[-1]['input']})
        return response


def capture(f, *, text=TEXT, role='user', session='session-own', turn='episode_turn', semantic=True):
    f._mp.setenv('MEMORY_WIKI_EPISODIC_SEMANTIC', '1' if semantic else '0')
    eid = f.m._episodic_memory.capture_turn(f.p, f.receiver, role, text,
        session_id=session, turn_id=turn)
    f._mp.setenv('MEMORY_WIKI_EPISODIC_SEMANTIC', '1')
    assert eid and f.conn.execute('SELECT content FROM episodic_turns WHERE id=?', (eid,)).fetchone()[0] == text
    jobs = list(f.conn.execute("SELECT * FROM index_outbox WHERE object_type='episode' AND object_id=? AND operation='embed_and_upsert'", (eid,)))
    assert len(jobs) == int(semantic)
    if semantic:
        payload = json.loads(jobs[0]['payload_json'])
        assert f.m._episode_outbox_payload_matches(payload,
            f.m._load_active_episode_index_snapshot(str(f.path), eid), eid)
        assert f.receiver.wakes[-2:] == [('start', str(f.path)), ('wake', str(f.path))]
    f._emit({'event': 'genuine_capture', 'episode_id': eid, 'role': role,
        'host_session': session, 'queued': bool(jobs), 'semantic': semantic})
    return eid


def call(f, batch=1):
    out = f.m._outbox_process(batch, db_path=str(f.path), worker_id='episode-source-worker')
    f._emit({'event': 'episode_worker_return', 'output': out, 'calls': dict(f.calls),
        'queue': [dict(r) for r in f.conn.execute('SELECT operation,status,attempts,last_error,worker_id,lease_until FROM index_outbox')],
        'targets': f.conn.execute('SELECT COUNT(*) FROM episodic_vector_targets').fetchone()[0]})
    return out


def erase(f, eid, text=TEXT):
    with f.p._claim_transaction(f.conn):
        out = f.m._episodic_memory.erase_matching_episodes(f.p, f.receiver, text, conn=f.conn)
    assert out['episode_ids'] == [eid] and out['deleted'] == 1
    assert f.conn.execute('SELECT 1 FROM episodic_turns WHERE id=?', (eid,)).fetchone() is None
    # Actual delete producer scrubs the already processing SQL copy. The
    # failure writer MUST NOT restore the claimed local payload after refusal.
    running = list(f.conn.execute("SELECT payload_json FROM index_outbox WHERE object_id=? AND operation='embed_and_upsert' AND status='processing'", (eid,)))
    assert running and all('text' not in json.loads(r[0]) for r in running)
    f._emit({'event': 'owned_episode_erased', 'post_before_change': f.calls['post'],
        'SQL_processing_payload_scrubbed': True, 'durable_delete_queued': out['vector_deletes_queued']})


@contextmanager
def schedule(f, effect, seam='prepared'):
    with claim.schedule(f, seam, action='episode_owned_change', effect=effect) as seen:
        yield seen


def edit(f, eid, **changes):
    """Authored SQL writer for race/retention metadata, never authority stand-in."""
    assert set(changes) <= {'owner_bot_id', 'owner_chat_hash', 'created_at', 'expires_at', 'content'}
    writer = sqlite3.connect(str(f.path))
    try:
        assert writer.execute('UPDATE episodic_turns SET ' + ','.join(k + '=?' for k in changes)
            + ' WHERE id=?', (*changes.values(), eid)).rowcount == 1
        writer.commit()
    finally:
        writer.close()


def queue(f, eid):
    rows = list(f.conn.execute("SELECT * FROM index_outbox WHERE object_id=? AND operation IN ('upsert','embed_and_upsert')", (eid,)))
    assert len(rows) == 1
    return rows[0]


def update_hint(f, eid, **changes):
    row = queue(f, eid)
    payload = json.loads(row['payload_json'])
    payload.update(changes)
    f.conn.execute('UPDATE index_outbox SET payload_json=? WHERE id=?', (json.dumps(payload), row['id']))
    f.conn.commit()
    return payload


def enable_cache(f):
    f.m.EMBED_CACHE_MAX_ENTRIES = 8
    f.m.EMBED_DOCUMENT_CACHE_TTL_SECONDS = 60
    f.m._embedding_cache_key(TEXT, 'search_document')


@contextmanager
def admission(f, eid):
    """Use the real factory and queue lease shape; do not fabricate a fence."""
    row = queue(f, eid)
    f.conn.execute("UPDATE index_outbox SET status='processing',worker_id='episode-source-worker',lease_until=? WHERE id=?",
        (int(time.time()) + 120, row['id']))
    f.conn.commit()
    payload = json.loads(row['payload_json'])
    with f.m._DisclosureFence.episode_worker(f.m, str(f.path)) as original:
        snapshot = f.m._load_active_episode_index_snapshot(str(f.path), eid, _disclosure=original)
        original.index_episode(snapshot, payload, outbox_id=row['id'], worker_id='episode-source-worker')
        yield original


@contextmanager
def observe_original(f):
    cls = f.m._DisclosureFence
    prior = sys.getprofile()
    originals, callbacks, dispatches, checks = [], [], [], []
    dispatch = peer.unwrapped(f.m._observed_semantic_http).__code__
    def observe(frame, event, arg):
        if event == 'return' and frame.f_code is cls.__init__.__code__:
            originals.append(frame.f_locals['self'])
        if event == 'call' and frame.f_code is f.m._embed_document.__code__:
            original = getattr(frame.f_locals.get('_admit'), '__self__', None)
            assert original in originals and original.episode_indexes
            assert {'episodic_turns', 'index_outbox'} <= {k[0] for k in original.selectors}
            assert original.provider is None and original.worker is f.m
            assert original.conn.execute('PRAGMA query_only').fetchone()[0] == 1
            callbacks.append(original)
        if event == 'call' and frame.f_code is cls.admit_episode_index.__code__:
            assert not f.m._EMBED_CACHE_LOCK._is_owned(), 'source_SQL_inside_cache_lock'
            checks.append(id(frame.f_locals['self']))
        if event == 'call' and frame.f_code is dispatch and frame.f_locals.get('_before_dispatch') is not None:
            original = getattr(frame.f_locals['_before_dispatch'], '__self__', None)
            assert original in callbacks
            dispatches.append(original)
        if prior is not None:
            prior(frame, event, arg)
    sys.setprofile(observe)
    try:
        yield originals
    finally:
        sys.setprofile(prior)
        f._emit({'event': 'episode_original_handoff', 'originals': len(originals),
            'embedding_callbacks': len(callbacks), 'prepared_same_callback': len(dispatches),
            'SQL_checks_outside_cache_lock': len(checks)})


def erasure_intent(f, eid, kind='id', *, applied=False, text=TEXT):
    ledger = f.p._privacy_erasure
    with f.p._claim_transaction(f.conn):
        seq = ledger.append(f.p, '', claim_ids=[], event_ids=[],
            episode_ids=[eid] if kind == 'id' else [],
            episode_surface=f.m._episodic_memory._removal_surface(text) if kind == 'text' else '')
        if applied:
            # Authored old-restore inconsistency: original captured raw row
            # survives an already-applied authenticated intent. No replay at
            # dispatch may create permission for this surviving copy.
            f.conn.execute("INSERT INTO meta(key,value) VALUES('privacy_erasure_applied_seq',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(seq),))
    entries = ledger._load_unlocked()
    assert seq == len(entries)
    f._emit({'event': 'genuine_authenticated_episode_intent', 'kind': kind,
        'seq': seq, 'applied_marker': applied, 'surviving_raw_row': True})
    return entries[-1]
