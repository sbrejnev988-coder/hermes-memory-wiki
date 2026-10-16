"""Original claim-read fence across the shared rerank handoff.

Genuine direct MemoryProvider/registry/trust and file-backed SQLite. SQL seeds,
changes and bounded HTTP streams are authored; no model/socket/MemoryManager.
The public query uses claims, default hybrid search and synchronous dispatch,
not the document/code results schema or the bounded prefetch worker.
"""
from contextlib import contextmanager
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import threading


spec = importlib.util.spec_from_file_location(
    'claim_egress_owned_fixture',
    Path(__file__).parent / 'ci_owned/document_egress_fixture.py',
)
fmod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = fmod
spec.loader.exec_module(fmod)
ri_r03_case = fmod.ri_r03_case
Fixture = fmod.Fixture
TOOL = 'memory_wiki_query'
MARKER = 'CANARY_CLAIM_KITE_OWN'
FOREIGN_MARKER = 'CANARY_CLAIM_FOREIGN'
CLAIMS = tuple('sc4-claim-' + str(i) for i in range(3))
FOREIGN = 'sc4-foreign'


def seed(f):
    f.semantic_enabled = False  # genuine lexical hybrid path; no vector/model work
    f.m._embedding_cache_state()  # existing monotonic owner state before capture
    for cid in CLAIMS:
        f.claim(cid, visibility='bot', topic='general',
                text=MARKER + ' ' + fmod.QUERY + ' ' + fmod.SAFE)
    # Keep a stable ineligible row physically present, including its FTS entry.
    f.claim(FOREIGN, visibility='bot', origin_bot_id='foreign-owner', salience=1.0,
            text=FOREIGN_MARKER + ' ' + fmod.QUERY + ' ' + fmod.SAFE)
    f.ready()
    schema = next(s for s in f.p.get_tool_schemas() if s['name'] == TOOL)
    assert schema['parameters']['required'] == ['query']
    props = schema['parameters']['properties']
    assert props['limit'] == {'type': 'integer', 'default': 10}
    assert props['include_stale'] == {'type': 'boolean', 'default': True}
    assert set(props) == {'query', 'limit', 'include_stale', 'topic'}
    assert f.m._detect_query_mode(fmod.QUERY) in {'technical', 'semantic', 'mixed'}


def public(f):
    # Observe the real caller, its original constructor/read set, and the exact
    # handoff. No authority/fence/SQL/SDK function is replaced by this observer.
    original = None
    search_code = fmod.unwrapped(type(f.p)._search).__code__
    rank_code = fmod.unwrapped(type(f.p)._rerank_rows).__code__
    init_code = f.m._DisclosureFence.__init__.__code__
    finish_code = f.m._DisclosureFence.finish.__code__
    caller_thread = threading.get_ident()
    proof = {'captures': 0, 'owned_original': False, 'same_original_at_rank': False,
             'rank_calls': 0, 'original_rank_checks': 0, 'watched_tables': [],
             'search_hybrid_default': False, 'same_caller_thread': True}
    before = sys.getprofile()

    def observe(frame, event, arg):
        nonlocal original
        parent = frame.f_back
        if event == 'return' and frame.f_code is init_code and parent is not None and parent.f_code is search_code:
            original = frame.f_locals['self']
            proof['captures'] += 1
            proof['owned_original'] = (
                type(original) is f.m._DisclosureFence and original.provider is f.p
                and original.conn is f.conn and original.owner_conn is f.p._owned_conn
                and original.source_conn is None
            )
        if event == 'call' and frame.f_code in {search_code, rank_code} and frame.f_locals.get('self') is f.p:
            proof['same_caller_thread'] &= threading.get_ident() == caller_thread
            if frame.f_code is search_code:
                proof['search_hybrid_default'] = (
                    frame.f_locals['retrieval_mode'] == 'hybrid'
                    and frame.f_locals['apply_rerank'] is True
                    and frame.f_locals['record_retrieval'] is False
                    and frame.f_locals['conn'] is None
                )
            else:
                proof['rank_calls'] += 1
                proof['same_original_at_rank'] = original is not None and frame.f_locals.get('_disclosure') is original
                proof['watched_tables'] = sorted({key[0] for key in original.selectors}) if original is not None else []
        if (event == 'call' and frame.f_code is finish_code and frame.f_locals.get('self') is original
                and parent is not None and parent.f_code.co_name == 'check_document_disclosure'):
            proof['original_rank_checks'] += 1
        if before is not None:
            before(frame, event, arg)

    sys.setprofile(observe)
    try:
        # Use actual schema defaults; never invent a public retrieval-mode flag.
        result = json.loads(f.p.handle_tool_call(TOOL, {'query': fmod.QUERY}))
    finally:
        sys.setprofile(before)
    f.handoff = proof
    f._emit({'event': 'original_claim_handoff', **proof, 'calls': dict(f.calls),
             'final_claims': len(result.get('claims', [])),
             'public_keys': sorted(result), 'public_error': result.get('error'),
             'disclosure_status': result.get('disclosure_status')})
    return result


def changed(f, action):
    if action == 'session':
        previous = f.p.session_id
        f.p.on_session_switch('different-session', reset=False)
        assert previous != f.p.session_id
        return
    if action == 'generation':
        previous = f.p._disclosure_context()[1]
        f.m._embedding_cache_clear()
        assert f.p._disclosure_context()[1] != previous
        return
    version = f.conn.execute('PRAGMA data_version').fetchone()[0]
    writer = sqlite3.connect(str(f.path))
    try:
        if action == 'retire':
            cursor = writer.execute("UPDATE claims SET status='retired' WHERE id IN (?,?,?)", CLAIMS)
            assert cursor.rowcount == len(CLAIMS)
        elif action == 'ABA':
            before = writer.execute('SELECT * FROM claims WHERE id=?', (CLAIMS[0],)).fetchone()
            assert before is not None
            # origin_bot_id is not in the historical claims revision trigger.
            # Raw row equality after A->foreign->A cannot license the old read.
            writer.execute("UPDATE claims SET origin_bot_id='foreign-owner' WHERE id=?", (CLAIMS[0],))
            assert writer.execute('SELECT origin_bot_id FROM claims WHERE id=?', (CLAIMS[0],)).fetchone()[0] == 'foreign-owner'
            writer.execute('UPDATE claims SET origin_bot_id=? WHERE id=?', (f.bot_id, CLAIMS[0]))
            assert writer.execute('SELECT * FROM claims WHERE id=?', (CLAIMS[0],)).fetchone() == before
        else:
            raise AssertionError('unknown_authority_change')
        writer.commit()
    finally:
        writer.close()
    assert f.conn.execute('PRAGMA data_version').fetchone()[0] != version
    if action == 'retire':
        assert [r[0] for r in f.conn.execute('SELECT status FROM claims WHERE id IN (?,?,?) ORDER BY id', CLAIMS)] == ['retired'] * len(CLAIMS)
    else:
        assert tuple(f.conn.execute('SELECT * FROM claims WHERE id=?', (CLAIMS[0],)).fetchone()) == before
    assert f.conn.execute('SELECT COUNT(*) FROM claims').fetchone()[0] == len(CLAIMS) + 1


@contextmanager
def schedule(f, seam, action):
    rank_code = fmod.unwrapped(type(f.p)._rerank_rows).__code__
    target = {'bytes': f.io.request_bytes.__code__,
              'response': f.io.response_json.__code__,
              'cache': f.m._stage_receipt.__code__}[seam]
    before = sys.getprofile()
    seen = []

    def inject(frame, event, arg):
        if event == 'return' and frame.f_code is target and not seen:
            parent = frame.f_back
            match = (seam in {'bytes', 'response'} and parent is not None and parent.f_code is rank_code
                     or seam == 'cache' and parent is not None and parent.f_code is rank_code
                     and frame.f_locals.get('stage') == 'rerank'
                     and frame.f_locals.get('status') == 'cache_hit')
            if match:
                changed(f, action)
                seen.append((seam, action))
                f._emit({'event': 'scheduled_original_claim_authority_change',
                         'seam': seam, 'action': action, 'calls': dict(f.calls)})
        if before is not None:
            before(frame, event, arg)

    sys.setprofile(inject)
    try:
        yield seen
    finally:
        sys.setprofile(before)


def rank_state(f):
    return f.m._rerank_scope_state(f.m._rerank_settings())


def assert_accounting(f, expected):
    assert f.m._HYBRID_WORK.get() is None, 'optional_collector_not_absent'
    state = rank_state(f)
    assert state['stats']['requests'] == expected == f.calls['rank'], 'physical_request_not_counted_once'
    assert state['stats']['failures'] == state['failure_count'] == 0
    assert not state['circuit_until']
    assert all(f.calls[k] == 0 for k in ('health', 'qdrant_metadata', 'embed', 'vector', 'unexpected'))


def assert_original(f, *, checks=True, watched=True):
    assert f.handoff['captures'] == 1 and f.handoff['owned_original'], 'original_search_fence_not_observed'
    assert f.handoff['rank_calls'] == 1 and f.handoff['same_original_at_rank'], 'ranker_reanchored_or_lost_original_fence'
    assert f.handoff['same_caller_thread'] and f.handoff['search_hybrid_default']
    if watched:
        assert 'claims' in f.handoff['watched_tables'], 'original_claim_read_set_missing'
    if checks:
        assert f.handoff['original_rank_checks'] > 0, 'original_fence_not_checked_by_ranker'


def assert_denied(f, payload, seen, *, rank_count, recall_count=0, cache_error=False):
    f._emit({'event': 'pre_assert_claim_egress_observation', 'mutation_seen': bool(seen),
             'calls': dict(f.calls),
             'sent_marker': any(MARKER in text for docs in f.rank_documents for text in docs),
             'final_claims': len(payload.get('claims', [])),
             'public_keys': sorted(payload), 'public_error': payload.get('error')})
    assert seen, 'scheduled_change_not_reached'
    assert f.calls['rank'] == rank_count, 'revoked_claim_body_reached_rank_transport'
    assert not payload.get('claims'), 'revoked_claim_rows_published'
    assert MARKER not in json.dumps(payload) and FOREIGN_MARKER not in json.dumps(payload)
    # Unlike graph APIs, _search can return an empty success without a withheld
    # flag. Cache admission raises outside the ranker's transport try boundary
    # and therefore returns the native safe tool_error envelope instead.
    if cache_error:
        assert payload == {'error': f.m._SemanticIOError.__name__}
    else:
        assert payload['success'] is True and payload['claims'] == [] and 'error' not in payload
    assert_original(f)
    assert_accounting(f, rank_count)
    assert [r[0] for r in f.conn.execute('SELECT recall_count FROM claims WHERE id IN (?,?,?) ORDER BY id', CLAIMS)] == [recall_count] * len(CLAIMS)
    assert f.conn.execute('SELECT COUNT(*) FROM recall_events').fetchone()[0] == recall_count * len(CLAIMS)


def test_sc4_healthy_cache(ri_r03_case):
    with Fixture('sc4-healthy', cache_ttl=60, rank_claim_ids=CLAIMS) as f:
        seed(f)
        first = public(f)
        second = public(f)
        assert first['success'] is True and second['success'] is True
        assert [r['id'] for r in first['claims']] == [r['id'] for r in second['claims']]
        assert {r['id'] for r in second['claims']} == set(CLAIMS)
        assert {r['rerank_rank'] for r in second['claims']} == {1, 2, 3}
        assert all(MARKER in r['claim'] and '_rerank_order' not in r for r in second['claims'])
        assert FOREIGN_MARKER not in json.dumps(first) and FOREIGN_MARKER not in json.dumps(second)
        assert f.calls['rank'] == 1 and f.calls['rerank_body'] == 2
        assert len(f.rank_documents) == 1 and all(MARKER in text for text in f.rank_documents[0])
        assert any(s.get('status') == 'cache_hit' for s in f.stages)
        assert second['retrieval_receipt']['entrypoint'] == TOOL
        assert f.handoff['owned_original'] and f.handoff['search_hybrid_default'] and f.handoff['same_caller_thread']
        assert_accounting(f, 1)
        assert [r[0] for r in f.conn.execute('SELECT recall_count FROM claims WHERE id IN (?,?,?) ORDER BY id', CLAIMS)] == [2] * len(CLAIMS)
        assert f.conn.execute('SELECT recall_count FROM claims WHERE id=?', (FOREIGN,)).fetchone()[0] == 0
        assert f.conn.execute('SELECT COUNT(*) FROM recall_events').fetchone()[0] == 2 * len(CLAIMS)


def test_sc4_ineligible_initial(ri_r03_case):
    with Fixture('sc4-initial', rank_claim_ids=CLAIMS) as f:
        seed(f)
        changed(f, 'retire')
        out = public(f)
        assert out['success'] is True and out['claims'] == [] and 'error' not in out
        assert not f.rank_documents
        assert_original(f, checks=False, watched=False)
        assert_accounting(f, 0)
        assert f.conn.execute('SELECT COUNT(*) FROM recall_events').fetchone()[0] == 0


def test_sc4_late_retire_before_http(ri_r03_case):
    with Fixture('sc4-late-retire', rank_claim_ids=CLAIMS) as f:
        seed(f)
        with schedule(f, 'bytes', 'retire') as seen:
            out = public(f)
        assert_denied(f, out, seen, rank_count=0)
        assert not f.rank_documents


def test_sc4_sql_ABA_before_http(ri_r03_case):
    with Fixture('sc4-ABA', rank_claim_ids=CLAIMS) as f:
        seed(f)
        with schedule(f, 'bytes', 'ABA') as seen:
            out = public(f)
        assert_denied(f, out, seen, rank_count=0)
        assert not f.rank_documents


def test_sc4_session_before_http(ri_r03_case):
    with Fixture('sc4-session', rank_claim_ids=CLAIMS) as f:
        seed(f)
        with schedule(f, 'bytes', 'session') as seen:
            out = public(f)
        assert_denied(f, out, seen, rank_count=0)
        assert not f.rank_documents


def test_sc4_generation_before_http(ri_r03_case):
    with Fixture('sc4-generation', rank_claim_ids=CLAIMS) as f:
        seed(f)
        with schedule(f, 'bytes', 'generation') as seen:
            out = public(f)
        assert_denied(f, out, seen, rank_count=0)
        assert not f.rank_documents


def test_sc4_cache_late_revoke(ri_r03_case):
    with Fixture('sc4-cache', cache_ttl=60, rank_claim_ids=CLAIMS) as f:
        seed(f)
        assert public(f)['claims']
        with schedule(f, 'cache', 'retire') as seen:
            out = public(f)
        assert_denied(f, out, seen, rank_count=1, recall_count=1, cache_error=True)
        assert any(s.get('status') == 'cache_hit' for s in f.stages)


def test_sc4_response_revoke(ri_r03_case):
    with Fixture('sc4-response', cache_ttl=60, rank_claim_ids=CLAIMS) as f:
        seed(f)
        with schedule(f, 'response', 'retire') as seen:
            out = public(f)
        assert_denied(f, out, seen, rank_count=1)
        assert not rank_state(f)['cache'], 'revoked_claim_response_entered_rank_cache'
