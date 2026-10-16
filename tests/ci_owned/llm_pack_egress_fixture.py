"""LLM-pack peer of the shipped document fixture; no SDK/model/socket boot.

Reuse its SQL seed, bounded Stream and exact owner shutdown. The separate
setup is necessary: the frozen rank fixture opts into semantic/rerank work and
an authored key, neither of which belongs to this key-free loopback packet.
The no-file ENV route and own home precede imports/context capture.
"""
from __future__ import annotations

from contextlib import contextmanager
import ast
import builtins
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import sys
import threading

import pytest

_SPEC = importlib.util.spec_from_file_location(
    'llm_pack_document_peer', Path(__file__).with_name('document_egress_fixture.py'))
peer = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = peer
_SPEC.loader.exec_module(peer)
SOURCE = Path(__file__).resolve().parents[2]
QUERY = peer.QUERY
MARKER = 'CANARY_LLM_PACK_KITE_OWN'
FOREIGN_MARKER = 'CANARY_LLM_PACK_FOREIGN'
CLAIM = 'llm-pack-own'
FOREIGN = 'llm-pack-foreign'
REPLY = '- ' + MARKER + ' needle semantic retrieval remains within the current source boundary.'


@pytest.fixture
def llm_pack_case(request, tmp_path_factory):
    """Same default peer layout; no external/private root ENV prerequisite."""
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


class Fixture(peer.Fixture):
    def __init__(self, label):
        super().__init__(label)
        self.posts = []
        self.failure = None
        self.calls['post'] = 0
        self.handoff = {}

    def __enter__(self):
        self.home.mkdir(parents=True, exist_ok=False)
        self._diag = (self.dir / 'observations.jsonl').open('x', encoding='utf-8')
        try:
            assert sys.getprofile() is None
            for key in tuple(os.environ):
                if peer.re.search(r'(?i)(api_?key|token|password|credential|secret)', key):
                    self._mp.delenv(key, raising=False)
            settings = {
                'HERMES_HOME': str(self.home), 'HOME': str(self.home), 'USERPROFILE': str(self.home),
                'APPDATA': str(self.home / 'roaming'), 'LOCALAPPDATA': str(self.home / 'local'),
                'HERMES_SECURITY_STRICT': '1', 'MEMORY_WIKI_STRICT_RECALL': '1',
                'MEMORY_WIKI_BOT_ID': self.bot_id, 'MEMORY_WIKI_PROJECT_ID': 'repo-own',
                'MEMORY_WIKI_SEMANTIC': '0', 'MEMORY_WIKI_EMBED_PROVIDER': 'stub',
                'MEMORY_WIKI_EMBED_MODEL': 'hash-ngram-8', 'MEMORY_WIKI_EMBED_DIMENSIONS': '8',
                'MEMORY_WIKI_VECTOR_SIZE': '8', 'MEMORY_WIKI_EMBED_CACHE_MAX_ENTRIES': '0',
                'MEMORY_WIKI_RERANK_ENABLED': '0', 'MEMORY_WIKI_BACKGROUND_JOBS_ENABLED': '0',
                'MEMORY_WIKI_EPISODIC_ENABLED': '0', 'MEMORY_WIKI_EPISODIC_SEMANTIC': '0',
                'MEMORY_WIKI_EVENT_LEDGER_ENABLED': '0', 'MEMORY_WIKI_OBSERVATIONS_ENABLED': '0',
                'MEMORY_WIKI_ENV_META_SYNC': '0', 'MEMORY_WIKI_GRAPH_EXTRACT_ENABLED': '0',
                'MEMORY_WIKI_GRAPH_AUTO_EXTRACT': '0', 'MEMORY_WIKI_INCLUDE_SESSIONS_IN_PACK': '0',
                'MEMORY_WIKI_CODE_GRAPH_ENABLED': '0', 'MEMORY_WIKI_DOCUMENT_GRAPH_ENABLED': '0',
                'MEMORY_WIKI_DOCUMENT_AUTO_SCAN_CACHE': '0',
                'MEMORY_WIKI_LLM_PACK': '1',
                'MEMORY_WIKI_LLM_BASE_URL': 'http://127.0.0.1:18646/v1',
                'MEMORY_WIKI_LLM_MODEL': 'authored-no-model', 'MEMORY_WIKI_LLM_TIMEOUT': '2',
            }
            for key, value in settings.items():
                self._mp.setenv(key, value)
            for name in ('local', 'roaming'):
                (self.home / name).mkdir()
            self._native = sys.modules['hermes_constants']
            self._native_token = self._native.set_hermes_home_override(self.home)
            spec = importlib.util.spec_from_file_location(
                self._namespace, SOURCE / '__init__.py', submodule_search_locations=[str(SOURCE)])
            self.m = importlib.util.module_from_spec(spec)
            sys.modules[self._namespace] = self.m
            spec.loader.exec_module(self.m)
            m = self.m
            spi, registry, trust = (sys.modules[n] for n in (
                'agent.memory_provider', 'tools.registry', 'hermes_trust_core'))
            assert m.MemoryProvider is spi.MemoryProvider
            assert m.MemoryWikiProvider.__bases__ == (spi.MemoryProvider,)
            assert m.tool_result is registry.tool_result and m.tool_error is registry.tool_error
            assert m._INJECTION_GUARD_AVAILABLE and m._sanitize_recalled is trust.sanitize_recalled
            assert Path(m._IMPORT_HERMES_HOME) == self.home
            assert m._urlopen_no_redirect.__module__ == self._namespace + '.http_safety'
            self._transport_before = m._urlopen_no_redirect
            m._urlopen_no_redirect = self.transport  # The only authored I/O boundary.
            self.p = m.MemoryWikiProvider()
            self.p.initialize('session-own', hermes_home=str(self.home), bot_id=self.bot_id,
                              project_id='repo-own', agent_context='test')
            self.conn = self.p._connect()
            self.path = self.p.db_path
            assert self.conn is self.p._owned_conn and self.p._lifecycle_state == 'ready'
            assert self.path.is_file() and self.path != Path(':memory:')
            self.conn.execute('PRAGMA temp_store=MEMORY')
            self._scopes.enter_context(m._native_profile_scope(self.home))
            self._scopes.enter_context(m._profile_qdrant_scope(self.home))
            doc = sys.modules[self._namespace + '.document_knowledge_graph']
            self._scopes.enter_context(doc._document_profile_scope(self.home))
            m._embedding_cache_state()
            identity = self.p._runtime_identity()
            assert identity['profile_ready'] is True and identity['missing_key_names'] == []
            assert identity['loaded_source_binding']['status'] == 'import_snapshot'
            assert not m.SEMANTIC_ENABLED and not m._rerank_settings()['RERANK_ENABLED']
            self._emit({'event': 'fixture_ready', 'genuine_SPI_registry_trust': True,
                        'file_backed_SQLite': True, 'no_file_ENV_route': True,
                        'profile_ready': identity['profile_ready'], 'missing_key_names': [],
                        'authored_SQL_and_transport': True, 'MemoryManager_SDK_model_socket': 'NOT_RUN'})
            return self
        except BaseException as primary:
            self._finish(primary)
            raise

    def transport(self, request, timeout):
        assert 1 <= timeout <= 60
        assert request.full_url == 'http://127.0.0.1:18646/v1/chat/completions'
        assert request.get_method() == 'POST'
        assert not request.has_header('Authorization')
        body = json.loads(request.data.decode('utf-8'))
        assert [m['role'] for m in body['messages']] == ['system', 'user']
        assert body['model'] == 'authored-no-model'
        self.posts.append(body)
        self.calls['post'] += 1
        self._emit({'event': 'authored_POST_received', 'post': self.calls['post'],
                    'canary': MARKER in json.dumps(body),
                    'foreign_canary': FOREIGN_MARKER in json.dumps(body)})
        if self.failure is not None:
            raise self.failure
        reply = REPLY if MARKER in json.dumps(body) or 'Atlas' in json.dumps(body) else '- Authored policy-only context; no eligible claim content.'
        stream = peer.Stream({'choices': [{'message': {'content': reply}}]})
        self.streams.append(stream)
        return stream


def seed(f):
    f.claim(CLAIM, visibility='bot', topic='general', pinned=1,
            text=MARKER + ' ' + QUERY + ' ' + peer.SAFE)
    f.claim(FOREIGN, visibility='bot', topic='general', pinned=1,
            origin_bot_id='foreign-owner', salience=1.0,
            text=FOREIGN_MARKER + ' ' + QUERY + ' ' + peer.SAFE)
    f.ready()
    schema = next(s for s in f.p.get_tool_schemas() if s['name'] == 'memory_wiki_pack_context')
    assert schema['parameters']['required'] == ['query']
    assert schema['parameters']['properties']['output_mode']['default'] == 'canonical'
    assert f.p._inspect_recall_text(REPLY, source='fixture:reply', mem_type='data',
                                    audit=False, max_len=12000)['status'] == 'safe'


def changed(f, action):
    if action == 'lifecycle':
        assert f.p._lifecycle_state == 'ready'
        # Session switching is an actual lifecycle API, not a state override.
        f.p.on_session_switch('different-session', reset=False)
        assert f.p.session_id == 'different-session'
        return
    version = f.conn.execute('PRAGMA data_version').fetchone()[0]
    writer = sqlite3.connect(str(f.path))
    try:
        if action == 'status':
            cur = writer.execute("UPDATE claims SET status='retired' WHERE id=?", (CLAIM,))
        elif action == 'owner':
            cur = writer.execute("UPDATE claims SET origin_bot_id='foreign-owner' WHERE id=?", (CLAIM,))
        elif action == 'ABA':
            before = writer.execute('SELECT * FROM claims WHERE id=?', (CLAIM,)).fetchone()
            cur = writer.execute("UPDATE claims SET origin_bot_id='foreign-owner' WHERE id=?", (CLAIM,))
            writer.execute('UPDATE claims SET origin_bot_id=? WHERE id=?', (f.bot_id, CLAIM))
            assert writer.execute('SELECT * FROM claims WHERE id=?', (CLAIM,)).fetchone() == before
        else:
            raise AssertionError('unknown_authority_change')
        assert cur.rowcount == 1
        writer.commit()
    finally:
        writer.close()
    assert f.conn.execute('PRAGMA data_version').fetchone()[0] != version
    assert f.conn.execute('SELECT COUNT(*) FROM claims').fetchone()[0] == 2
    if action == 'status':
        assert f.conn.execute('SELECT status FROM claims WHERE id=?', (CLAIM,)).fetchone()[0] == 'retired'
    if action == 'owner':
        assert f.conn.execute('SELECT origin_bot_id FROM claims WHERE id=?', (CLAIM,)).fetchone()[0] == 'foreign-owner'


@contextmanager
def schedule(f, seam, action=None, primary=None):
    """Fault at exact current helper frames, never replace SQL/guard/SDK code."""
    llm_code = peer.unwrapped(type(f.p)._llm_pack_context).__code__
    inspect_wrapper_code = type(f.p)._inspect_recall_text.__code__
    finish_code = f.m._DisclosureFence.finish.__code__
    prior = sys.getprofile()
    seen = []

    def inject(frame, event, arg):
        parent = frame.f_back
        match = (
            seam == 'prepared' and event == 'c_return' and frame.f_code is llm_code
            and arg is builtins.max and 'req' in frame.f_locals
            # The genuine scoped-method binder, not the raw inspection body,
            # returns directly to the LLM helper after its context cleanup.
            or seam == 'response' and event == 'return' and frame.f_code is inspect_wrapper_code
            and frame.f_locals.get('__name') == '_inspect_recall_text'
            and parent is not None and parent.f_code is llm_code
            or seam == 'guard' and event == 'call' and frame.f_code is finish_code
            and parent is not None and parent.f_code.co_name == 'check_pack_disclosure'
        )
        if match and not seen:
            seen.append((seam, action))
            f._emit({'event': 'scheduled_pack_change', 'seam': seam, 'action': action,
                     'post_before_change': f.calls['post'], 'primary_type': type(primary).__name__ if primary else None})
            if primary is not None:
                raise primary
            changed(f, action)
        if prior is not None:
            prior(frame, event, arg)

    sys.setprofile(inject)
    try:
        yield seen
    finally:
        sys.setprofile(prior)


def public(f, **options):
    original = None
    pack_code = peer.unwrapped(type(f.p)._pack_context).__code__
    llm_code = peer.unwrapped(type(f.p)._llm_pack_context).__code__
    init_code = f.m._DisclosureFence.__init__.__code__
    finish_code = f.m._DisclosureFence.finish.__code__
    proof = {'captures': 0, 'owned_original': False, 'same_original_at_llm': False,
             'llm_calls': 0, 'original_llm_checks': 0, 'watched_tables': [],
             'helper_published_response': False, 'terminal_retained_original': False}
    thread = threading.get_ident()
    prior = sys.getprofile()

    def observe(frame, event, arg):
        nonlocal original
        parent = frame.f_back
        if event == 'return' and frame.f_code is init_code and parent is not None and parent.f_code is pack_code:
            original = frame.f_locals['self']
            proof['captures'] += 1
            proof['owned_original'] = (type(original) is f.m._DisclosureFence and original.provider is f.p
                                       and original.conn is f.conn and original.owner_conn is f.p._owned_conn)
        elif frame.f_code is llm_code and frame.f_locals.get('self') is f.p:
            if event == 'call':
                proof['llm_calls'] += 1
                proof['same_original_at_llm'] = original is not None and frame.f_locals.get('_disclosure') is original
                proof['watched_tables'] = sorted({key[0] for key in original.selectors}) if original else []
                terminal = f.m._current_delivery(f.p)
                proof['terminal_retained_original'] = terminal is not None and any(x is original for x in terminal.fences)
                assert threading.get_ident() == thread
            elif event == 'return':
                proof['helper_published_response'] = bool(arg)
        elif (event == 'call' and frame.f_code is finish_code and frame.f_locals.get('self') is original
              and parent is not None and parent.f_code.co_name == 'check_pack_disclosure'):
            proof['original_llm_checks'] += 1
        if prior is not None:
            prior(frame, event, arg)

    sys.setprofile(observe)
    try:
        result = json.loads(f.p.handle_tool_call('memory_wiki_pack_context', {'query': QUERY, 'max_chars': 12000, **options}))
    finally:
        sys.setprofile(prior)
        f.handoff = proof
        f.original = original
        f._emit({'event': 'original_pack_handoff', **proof, 'post_count': f.calls['post']})
    f._emit({'event': 'public_pack_return', 'keys': sorted(result),
             'canary': MARKER in json.dumps(result), 'foreign_canary': FOREIGN_MARKER in json.dumps(result),
             'public_error': result.get('error'), 'disclosure_status': result.get('disclosure_status')})
    return result


def assert_original(f, *, checks=True):
    assert f.handoff['captures'] == 1 and f.handoff['owned_original']
    assert f.handoff['same_original_at_llm'] and f.handoff['llm_calls'] == 1
    assert f.handoff['terminal_retained_original'] and 'claims' in f.handoff['watched_tables']
    if checks:
        assert f.handoff['original_llm_checks'] > 0


def assert_denied(f, out, seen, *, posts):
    assert seen, 'scheduled_change_not_reached'
    # This assertion distinguishes egress prevention from late public withholding.
    assert f.calls['post'] == posts, 'revoked_pack_canary_reached_authored_POST'
    assert MARKER not in json.dumps(out) and FOREIGN_MARKER not in json.dumps(out)
    assert not out.get('context')
    assert not f.handoff['helper_published_response'], 'revoked_response_returned_to_pack_caller'
    assert_original(f)
    assert f.conn.execute('SELECT COUNT(*) FROM claims').fetchone()[0] == 2
    assert f.conn.execute('SELECT recall_count FROM claims WHERE id=?', (CLAIM,)).fetchone()[0] == 0
    assert f.conn.execute('SELECT COUNT(*) FROM recall_events').fetchone()[0] == 0


def legacy_boundary(f, name):
    """Execute exact old private-helper assertions without its MemoryManager imports.

    This is SOURCE-extracted test code, not a native renderer/host qualification.
    Only the two secondary-request functions and their pure prerequisite closure
    are admitted; no old fixture or MemoryManager constructor is executed.
    """
    path = SOURCE / 'tests/test_continuation_context_boundary.py'
    tree = ast.parse(path.read_bytes(), filename=str(path))
    names = {'assert_admit_safe', 'display_tokens', 'decode_data', name}
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in {'ADMIT_DATA', 'RAW_MARKERS'} for t in node.targets):
            nodes.append(node)
    assert len(nodes) == 6 and len({n.name for n in nodes if isinstance(n, ast.FunctionDef)}) == 4
    namespace = {'mw': f.m, 'json': json, 'OBSERVED': []}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), 'exec'), namespace)
    with pytest.MonkeyPatch.context() as patch:
        namespace[name]((f.p, f.conn), patch)
