"""Qdrant publication SOURCE peer, not wire/native/MemoryManager proof.

Reuse shipped genuine SPI/registry/home/SQL/ledger setup and bounded transport.
Host/session text and wake receiver are explicit authored SOURCE roles. The
same-home remover is a second real ready provider; only its ordinary semantic
feature is OFF during host removal so no asynchronous test worker is launched.
No profile_ready/guard/SDK substitutions, protected settings files or keys.
"""
from __future__ import annotations
from contextlib import contextmanager
import contextlib
import importlib.util
import hashlib
import os
import json
from pathlib import Path
import sqlite3
import sys

_SPEC = importlib.util.spec_from_file_location('publication_episode_peer',
    Path(__file__).with_name('episode_embedding_fixture.py'))
episode = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = episode
_SPEC.loader.exec_module(episode)
claim, peer = episode.claim, episode.peer
publication_case = episode.episode_embedding_case
TEXT = claim.MARKER + ' Verified service uses durable storage for needle semantic retrieval within the current source boundary.'
VECTOR = claim.VECTOR


class Fixture(episode.Fixture):
    def __init__(self, label='publication'):
        super().__init__(label)
        self.puts = []
        self.sink_effect = None
        self.withdrawals = []

    def transport(self, request, timeout):
        body = json.loads(request.data) if request.data is not None else None
        point_put = request.get_method() == 'PUT' and isinstance(body, dict) and 'points' in body
        response = super().transport(request, timeout)
        if point_put:
            # Independent received-effect record survives late DELETE/withholding.
            self.puts.append(body)
            self._emit({'event': 'actual_prepared_point_PUT_received',
                'points': body['points'], 'received_effect_count': len(self.puts)})
            if self.sink_effect is not None:
                try:
                    self.sink_effect()
                except BaseException:
                    response.close()
                    raise
        return response


def produce(f):
    """Supported caller-owned TX -> real preparation/write/outbox producer."""
    cid = f.p._add_claim(TEXT, topic='database', source='tool:publication-source',
        confidence=.9, salience=.9, conn=f.conn, visibility_scope='bot')
    assert cid.startswith('c_'), 'actual_claim_producer_did_not_accept'
    assert not f.conn.in_transaction
    row = f.conn.execute('SELECT * FROM claims WHERE id=?', (cid,)).fetchone()
    assert row['status'] == 'active' and row['normalized_claim'] == TEXT
    jobs = list(f.conn.execute("SELECT * FROM index_outbox WHERE object_type='claim' AND object_id=? AND operation='embed_and_upsert'", (cid,)))
    assert len(jobs) == 1 and json.loads(jobs[0]['payload_json'])['text'] == TEXT
    f._emit({'event': 'genuine_claim_producer', 'claim_id': cid, 'queued': 1})
    return cid


@contextmanager
def remover(f):
    """Second initialized same-home instance, separate lock/SQL owner/context."""
    m = f.m
    enabled = m.SEMANTIC_ENABLED
    episodic = m.os.environ.get('MEMORY_WIKI_EPISODIC_SEMANTIC')
    p = None
    try:
        m.SEMANTIC_ENABLED = False
        f._mp.setenv('MEMORY_WIKI_EPISODIC_SEMANTIC', '0')
        p = m.MemoryWikiProvider()
        p.initialize('session-own', hermes_home=str(f.home), bot_id=f.bot_id,
            project_id='repo-own', agent_context='test')
        assert p is not f.p and p._lock is not f.p._lock
        assert p._owned_conn is not f.conn and p._lifecycle_state == f.p._lifecycle_state == 'ready'
        assert p.home == f.p.home and p.db_path == f.path
        assert p._runtime_identity()['profile_ready'] is True
        f._emit({'event': 'two_genuine_ready_same_home_providers', 'separate_owners': True})
    finally:
        m.SEMANTIC_ENABLED = enabled
        if episodic is None:
            f._mp.delenv('MEMORY_WIKI_EPISODIC_SEMANTIC', raising=False)
        else:
            f._mp.setenv('MEMORY_WIKI_EPISODIC_SEMANTIC', episodic)
    try:
        yield p
    finally:
        if p is not None:
            enabled = m.SEMANTIC_ENABLED
            try:
                m.SEMANTIC_ENABLED = False
                p.shutdown()
                assert p._owned_conn is None and p._conn is None
            finally:
                m.SEMANTIC_ENABLED = enabled
                sys.modules['__main__']._memory_wiki_instance = f.p


def withdraw(f, p, *, cid=None, eid=None, text=TEXT):
    enabled = f.m.SEMANTIC_ENABLED
    try:
        # Supported SOURCE opt-out suppresses only asynchronous wake execution;
        # actual host removal, SQL commit, ledger, triggers and intents run.
        f.m.SEMANTIC_ENABLED = False
        with f.m._native_profile_scope(f.home), f.m._profile_qdrant_scope(f.home), \
                f.m._document_profile_scope(f.home):
            out = p.on_memory_write('remove', 'general', text)
            f._emit({'event': 'host_remove_return', 'output': out})
            if cid is not None:
                # Resume the genuine durable privacy derivative. The claim
                # status trigger cancels queued work but does not scrub a
                # processing hint itself; this supported recovery producer
                # calls the real delete enqueue/scrub, never an authored SQL
                # retirement or invented actor/erasure receipt.
                resumed = f.m._migrate_and_resume_claim_vector_targets(str(f.path))
                assert resumed['queued'] >= 1
    finally:
        f.m.SEMANTIC_ENABLED = enabled
    assert out['privacy_intent_durable'] and out['transaction_pending'] is False
    if cid is not None:
        assert out['claim_ids'] == [cid]
        assert f.conn.execute('SELECT status FROM claims WHERE id=?', (cid,)).fetchone()[0] == 'retired'
    if eid is not None:
        assert out['episodes_deleted'] == 1
        assert not f.conn.execute('SELECT 1 FROM episodic_turns WHERE id=?', (eid,)).fetchone()
    entries = p._privacy_erasure._load_unlocked()
    applied = f.conn.execute("SELECT value FROM meta WHERE key='privacy_erasure_applied_seq'").fetchone()[0]
    assert len(entries) == int(applied) == 1
    jobs = list(f.conn.execute('SELECT operation,payload_json FROM index_outbox'))
    assert jobs and all('text' not in json.loads(r['payload_json']) for r in jobs)
    assert any(r['operation'] == 'delete' for r in jobs)
    assert not f.m._OUTBOX_WORKERS
    f.withdrawals.append(out)
    f._emit({'event': 'genuine_host_withdrawal_committed', 'output': out,
        'authentic_ledger_and_applied': True, 'queue_scrubbed': True,
        'durable_delete_present': True, 'PUTs_before': len(f.puts)})


@contextmanager
def schedule(f, seam, effect):
    """Exact collection GET inside upsert, or final health-observer return.

    Preparation observer is passive except for the one registered owned effect;
    never replace admission, SQL, Request, encoder or transport permission.
    """
    m = f.m
    upsert = m._qdrant_upsert.__code__
    health = m._health_http_check.__code__
    dispatch = peer.unwrapped(m._observed_semantic_http).__code__
    prior, seen = sys.getprofile(), []
    def inject(frame, event, arg):
        parent = frame.f_back
        match = False
        if not seen and seam == 'collection' and event == 'return' and frame.f_code is m._collection_config.__code__:
            outer = parent.f_back if parent else None
            match = parent is not None and parent.f_code is m._ensure_collection.__code__ and outer is not None and outer.f_code is upsert
        if not seen and seam == 'prepared' and event == 'return' and frame.f_code is health and parent is not None and parent.f_code is dispatch:
            request = parent.f_locals['request']
            body = json.loads(request.data) if request.data else None
            match = request.get_method() == 'PUT' and isinstance(body, dict) and 'points' in body
        if match:
            seen.append(seam)
            f._emit({'event': 'publication_seam', 'seam': seam, 'received_PUTs': len(f.puts)})
            effect()
        if prior is not None:
            prior(frame, event, arg)
    sys.setprofile(inject)
    try:
        yield seen
    finally:
        sys.setprofile(prior)


@contextmanager
def observe(f):
    """Record original identity and durable pending BEFORE raw capture and PUT."""
    m, cls = f.m, f.m._DisclosureFence
    prior = sys.getprofile()
    captures, binds, dispatches, pending, before_write = [], [], [], [], []
    dispatch = peer.unwrapped(m._observed_semantic_http).__code__
    def witness(frame, event, arg):
        if event == 'return' and frame.f_code is cls.__init__.__code__:
            captures.append(frame.f_locals['self'])
        if event == 'call' and frame.f_code in (cls.index_claim.__code__, cls.index_episode.__code__):
            source = frame.f_locals['self']
            assert source in captures
            binds.append(source)
            if frame.f_code is cls.index_claim.__code__ and frame.f_locals['purpose'] != 'scoped_reindex':
                cid = frame.f_locals['row']['id']
                rows = list(f.conn.execute("SELECT * FROM claim_vector_targets WHERE claim_id=? AND status='write_pending'", (cid,)))
                assert rows and not f.conn.in_transaction, 'owned_pending_not_durable_before_first_raw_binding'
                pending.append(cid)
        if (event == 'call' and frame.f_code is dispatch
                and frame.f_back is not None
                and frame.f_back.f_code is contextlib._GeneratorContextManager.__enter__.__code__):
            request = frame.f_locals['request']
            if request.get_method() == 'PUT' and request.data and 'points' in json.loads(request.data):
                bound = frame.f_locals.get('_before_dispatch')
                if bound is not None:
                    source = getattr(bound, '__self__', None)
                    assert source in binds and source in captures, 'new_or_empty_purpose_admission'
                    assert not m._EMBED_CACHE_LOCK._is_owned()
                    dispatches.append(source)
        if event == 'call' and frame.f_code is m._qdrant_upsert.__code__:
            if frame.f_locals.get('before_write') is not None:
                before_write.append(frame.f_locals['before_write'])
        if prior is not None:
            prior(frame, event, arg)
    sys.setprofile(witness)
    try:
        yield {'captures': captures, 'binds': binds, 'dispatches': dispatches,
            'pending': pending, 'before_write': before_write}
    finally:
        sys.setprofile(prior)
        f._emit({'event': 'publication_original_correspondence', 'captures': len(captures),
            'bound_originals': len(binds), 'prepared_originals': len(dispatches),
            'durable_claim_pending': len(pending), 'existing_before_write': len(before_write)})


def call(f, producer='outbox'):
    return claim.call(f, producer)


def baseline_counterfactual():
    """Optional evidence-only full-source baseline, never a shipped prerequisite.

    Two earlier physical openings did not prove the property (fixture refusal,
    then an effect assertion caught by the old worker). The remaining child
    executes this one genuine frozen1a62 component before the candidate. Only
    the existing peer's source pathname is selected; no code/guard is replaced.
    Ordinary in-tree pytest has no external ENV and needs no historical files.
    """
    raw = os.environ.get('QDRANT_PUBLICATION_BASELINE_SOURCE')
    if not raw:
        return
    root = Path(raw)
    peer.no_links(root)
    manifest = json.loads((root / 'runtime-manifest.json').read_bytes())
    assert manifest['commit'] == '1a62b087ebc785cef14498da093931423d8c5052'
    for name, digest in manifest['files'].items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == digest
    assert manifest['files']['__init__.py'] == '3671edb1e479e4fa5f9dd2b10af6c3e388c2d2cb79b84d38330f068833105abd'
    previous = claim.llm.SOURCE
    claim.llm.SOURCE = root
    try:
        with Fixture('frozen1a62-counterfactual') as old:
            assert Path(old.m.__file__) == root / '__init__.py'
            cid = produce(old)
            with remover(old) as other:
                with schedule(old, 'collection', lambda: withdraw(old, other, cid=cid)) as seen:
                    out = call(old)
            assert seen == ['collection'] and len(old.withdrawals) == 1
            assert old.calls['post'] == 1 and len(old.puts) == 1
            point = old.puts[0]['points'][0]
            assert point['payload']['claim'] == TEXT and point['vector'] == VECTOR
            assert point['payload']['visibility_scope'] == 'bot'
            assert out['ok'] == 1 and old.calls['delete'] >= 1 and not any(old.points.values())
            old._emit({'event': 'frozen1a62_privacy_counterexample', 'product_privacy_property': 'FAIL',
                'exact_full_source': manifest['files']['__init__.py'], 'actual_received_point_PUTs': 1,
                'later_cleanup_does_not_undo_delivery': True, 'public': out})
    finally:
        claim.llm.SOURCE = previous


def supplied(f, eid):
    snapshot = f.m._load_active_episode_index_snapshot(str(f.path), eid)
    episode.update_hint(f, eid, vector=VECTOR, qdrant_payload={
        'vector_text_hash': f.m.sha(snapshot['content']), 'manifest_hash': snapshot['manifest_hash'],
        'vector_target_hash': snapshot['current_vector_target_hash']})
    f.conn.execute("UPDATE index_outbox SET operation='upsert' WHERE object_id=?", (eid,))
    f.conn.commit()
