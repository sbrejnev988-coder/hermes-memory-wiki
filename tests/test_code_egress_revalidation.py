"""Original code-read fence at rerank handoff, using genuine direct SPI/SQLite.

The SQL seeds and HTTP streams are authored; there is no socket/model execution
or atomic wire-revocation claim. The shared fixture is shipped with these tests.
"""
from contextlib import contextmanager
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys


spec = importlib.util.spec_from_file_location(
    'code_egress_owned_fixture',
    Path(__file__).parent / 'ci_owned/document_egress_fixture.py',
)
fmod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = fmod
spec.loader.exec_module(fmod)
ri_r03_case = fmod.ri_r03_case
Fixture = fmod.Fixture
TOOL = 'memory_wiki_code_graph_query'
REPO = 'repo-own'
MARKER = 'CANARY_CODE_KITE_OWN'
CLAIMS = tuple('sc3-claim-' + str(i) for i in range(3))


def seed(f):
    f.semantic_enabled = False  # lexical code candidates; no semantic transport
    f.m._embedding_cache_state()  # real monotonic owner state before capture
    assert f.p.project_scope == REPO
    for cid in CLAIMS:
        f.claim(cid, topic='code-intelligence')
        f.code_chunk(REPO, cid, text=MARKER + ' ' + fmod.QUERY + ' ' + fmod.SAFE)
    f.ready()
    schema = next(s for s in f.p.get_tool_schemas() if s['name'] == TOOL)
    assert schema['parameters']['required'] == ['query']
    assert schema['parameters']['properties']['limit']['maximum'] == 50


def public(f):
    # Observe the actual private-reader anchor and exact ranker argument. No
    # wrappers replace a provider, fence, guard, SQLite owner or SDK object.
    original = None
    proof = {'original_reader_bound': False, 'same_original_at_rank': False,
             'rank_calls': 0, 'watched_tables': [], 'original_rank_checks': 0}
    disclosure_code = f.code._code_disclosure.__code__
    rank_code = fmod.unwrapped(type(f.p)._rerank_rows).__code__
    finish_code = f.m._DisclosureFence.finish.__code__
    before = sys.getprofile()

    def observe(frame, event, arg):
        nonlocal original
        if event == 'return' and frame.f_code is disclosure_code:
            original = arg
            conn = frame.f_locals['conn']
            proof['original_reader_bound'] = (
                type(conn) is f.code._GraphReaderConnection
                and arg is conn._graph_read_fence and arg.source_conn is conn
                and arg.provider is f.p
            )
        if event == 'call' and frame.f_code is rank_code and frame.f_locals.get('self') is f.p:
            proof['rank_calls'] += 1
            proof['same_original_at_rank'] = (
                original is not None and frame.f_locals.get('_disclosure') is original
            )
            proof['watched_tables'] = sorted({key[0] for key in original.selectors})
        if event == 'call' and frame.f_code is finish_code and frame.f_locals.get('self') is original:
            parent = frame.f_back
            if parent is not None and parent.f_code.co_name == 'check_document_disclosure':
                proof['original_rank_checks'] += 1
        if before is not None:
            before(frame, event, arg)

    sys.setprofile(observe)
    try:
        result = json.loads(f.p.handle_tool_call(TOOL, {
            'query': fmod.QUERY, 'repository_id': REPO, 'limit': 12,
        }))
    finally:
        sys.setprofile(before)
    f.handoff = proof
    f._emit({'event': 'original_code_handoff', **proof,
             'calls': dict(f.calls), 'final_results': len(result.get('results', [])),
             'withheld': result.get('disclosure') == 'withheld'
                         or result.get('disclosure_status') == 'withheld'})
    return result


def changed(f, action):
    if action == 'session':
        previous = f.p.session_id
        f.p.on_session_switch('different-session', reset=False)
        assert previous != f.p.session_id
        return
    if action == 'generation':
        before = f.p._disclosure_context()[1]
        f.m._embedding_cache_clear()
        assert f.p._disclosure_context()[1] != before
        return
    writer = sqlite3.connect(str(f.path))
    try:
        if action == 'retire':
            writer.execute("UPDATE claims SET status='retired' WHERE id IN (?,?,?)", CLAIMS)
        elif action == 'delete':
            cursor = writer.execute(
                'DELETE FROM code_graph_chunks WHERE repository_id=? AND chunk_id=?',
                (REPO, 'code-' + CLAIMS[0]),
            )
            assert cursor.rowcount == 1
        elif action == 'ABA':
            row = writer.execute(
                'SELECT file_hash FROM code_graph_files WHERE repository_id=? AND file_path=?',
                (REPO, 'source.py'),
            ).fetchone()
            assert row is not None and row[0] != 'b' * 64
            writer.execute('UPDATE code_graph_files SET file_hash=? WHERE repository_id=?',
                           ('b' * 64, REPO))
            writer.execute('UPDATE code_graph_files SET file_hash=? WHERE repository_id=?',
                           (row[0], REPO))
        else:
            raise AssertionError('unknown_authority_change')
        writer.commit()
    finally:
        writer.close()
    if action == 'retire':
        assert [r[0] for r in f.conn.execute('SELECT status FROM claims ORDER BY id')] == ['retired'] * 3
    elif action == 'delete':
        assert f.conn.execute('SELECT COUNT(*) FROM code_graph_chunks WHERE repository_id=?',
                              (REPO,)).fetchone()[0] == 2
        # Keep the old FTS row; original source identity must not be rehydrated
        # or replaced with the remaining current rows as a new grant.
        assert f.conn.execute('SELECT COUNT(*) FROM code_graph_chunks_fts WHERE repository_id=?',
                              (REPO,)).fetchone()[0] == 3
    else:
        assert f.conn.execute('SELECT file_hash FROM code_graph_files WHERE repository_id=?',
                              (REPO,)).fetchone()[0] == row[0]


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
                     or seam == 'cache' and frame.f_locals.get('stage') == 'rerank'
                     and frame.f_locals.get('status') == 'cache_hit')
            if match:
                changed(f, action)
                seen.append((seam, action))
                f._emit({'event': 'scheduled_original_code_authority_change',
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
    assert f.m._HYBRID_WORK.get() is None
    state = rank_state(f)
    assert state['stats']['requests'] == expected == f.calls['rank']
    assert state['stats']['failures'] == state['failure_count'] == 0


def assert_original(f):
    assert f.handoff['original_reader_bound'], 'original_private_reader_anchor_not_observed'
    assert f.handoff['rank_calls'] == 1 and f.handoff['same_original_at_rank'], 'ranker_reanchored_or_lost_original_fence'
    assert {'code_graph_chunks', 'code_graph_files', 'code_graph_repositories', 'claims'} <= set(f.handoff['watched_tables'])
    assert f.handoff['original_rank_checks'] > 0, 'original_fence_not_checked_by_ranker'


def assert_withheld(f, payload, seen, *, rank_count):
    f._emit({'event': 'pre_assert_code_egress_observation', 'mutation_seen': bool(seen),
             'calls': dict(f.calls),
             'sent_marker': any(MARKER in text for docs in f.rank_documents for text in docs),
             'final_results': len(payload.get('results', [])),
             'withheld': payload.get('disclosure') == 'withheld'
                         or payload.get('disclosure_status') == 'withheld'})
    assert seen, 'scheduled_change_not_reached'
    assert f.calls['rank'] == rank_count, 'revoked_code_body_reached_rank_transport'
    assert not payload.get('results'), 'revoked_code_rows_published'
    assert payload.get('disclosure') == 'withheld' or payload.get('disclosure_status') == 'withheld'
    assert_original(f)
    assert_accounting(f, rank_count)


def test_sc3_healthy_cache(ri_r03_case):
    with Fixture('sc3-healthy', cache_ttl=60) as f:
        seed(f)
        first = public(f)
        second = public(f)
        assert not first.get('error') and not second.get('error')
        assert [r['id'] for r in first['results']] == [r['id'] for r in second['results']]
        assert {r['id'] for r in second['results']} == {'code-' + cid for cid in CLAIMS}
        assert {r['repository_id'] for r in second['results']} == {REPO}
        assert f.calls['rank'] == 1 and f.calls['rerank_body'] == 2
        assert any(MARKER in text for docs in f.rank_documents for text in docs)
        assert any(s.get('status') == 'cache_hit' for s in f.stages)
        assert second['output_boundary']['authority'] == 'untrusted_data'
        assert_accounting(f, 1)


def test_sc3_unavailable_initial(ri_r03_case):
    with Fixture('sc3-initial') as f:
        seed(f)
        changed(f, 'retire')
        out = public(f)
        assert_withheld(f, out, [('initial', 'retire')], rank_count=0)
        assert not f.rank_documents


def test_sc3_late_delete_before_http(ri_r03_case):
    with Fixture('sc3-late-delete') as f:
        seed(f)
        with schedule(f, 'bytes', 'delete') as seen:
            out = public(f)
        assert_withheld(f, out, seen, rank_count=0)
        assert not f.rank_documents


def test_sc3_sql_ABA_before_http(ri_r03_case):
    with Fixture('sc3-late-ABA') as f:
        seed(f)
        with schedule(f, 'bytes', 'ABA') as seen:
            out = public(f)
        assert_withheld(f, out, seen, rank_count=0)
        assert not f.rank_documents


def test_sc3_session_before_http(ri_r03_case):
    with Fixture('sc3-late-session') as f:
        seed(f)
        with schedule(f, 'bytes', 'session') as seen:
            out = public(f)
        assert_withheld(f, out, seen, rank_count=0)
        assert not f.rank_documents


def test_sc3_generation_before_http(ri_r03_case):
    with Fixture('sc3-late-generation') as f:
        seed(f)
        with schedule(f, 'bytes', 'generation') as seen:
            out = public(f)
        assert_withheld(f, out, seen, rank_count=0)
        assert not f.rank_documents


def test_sc3_cache_late_revoke(ri_r03_case):
    with Fixture('sc3-cache-revoke', cache_ttl=60) as f:
        seed(f)
        assert public(f).get('results')
        with schedule(f, 'cache', 'retire') as seen:
            out = public(f)
        assert_withheld(f, out, seen, rank_count=1)
        assert any(s.get('status') == 'cache_hit' for s in f.stages)


def test_sc3_response_revoke(ri_r03_case):
    with Fixture('sc3-response-revoke', cache_ttl=60) as f:
        seed(f)
        with schedule(f, 'response', 'retire') as seen:
            out = public(f)
        assert_withheld(f, out, seen, rank_count=1)
        assert not rank_state(f)['cache'], 'revoked_code_response_entered_rank_cache'
