"""Genuine direct SPI/SQLite graph fixture; authored SQL/HTTP, never host boot.

Reuse the shipped document peer's owner, seed and shutdown layout. Settings
are no-file ENV inputs. Codex SDK hook proof is separate from native adapter
bootstrap/auth/YAML qualification; none of those roles is replaced by a stub.
"""
from __future__ import annotations
from contextlib import contextmanager
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import sys
import urllib.request
from types import SimpleNamespace

import pytest

_SPEC = importlib.util.spec_from_file_location('graph_document_peer',
    Path(__file__).with_name('document_egress_fixture.py'))
peer = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = peer
_SPEC.loader.exec_module(peer)
SOURCE = Path(__file__).resolve().parents[2]
CID = 'graph-own'
TEXT = 'CANARY_GRAPH_ATLAS runs on Boreal server.'
PROPOSAL = dict(subject='CANARY_GRAPH_ATLAS', predicate='runs_on', object='Boreal server',
                evidence=TEXT, confidence=.9)  # Full lexical endpoint, not a cropped name.
AUTO_TEXT = ('User owns Boreal service server; durable vector search backup storage uses isolated '
             'replica nodes with reliable archive retention and verified daily integrity checks.')
AUTO_PROPOSAL = dict(subject='User', predicate='owns', object='Boreal service server',
                     evidence='User owns Boreal service server', confidence=.9)


@pytest.fixture
def graph_case(request, tmp_path_factory):
    assert peer._ACTIVE is None
    ordinary = sys.modules['memory_wiki']
    assert Path(ordinary.__file__).resolve() == SOURCE / '__init__.py'
    token = hashlib.sha256(request.node.nodeid.encode()).hexdigest()[:16]
    root = tmp_path_factory.mktemp('document-egress-' + token, numbered=False)
    peer.no_links(root)
    control = root / 'diagnostics/controls' / token
    control.mkdir(parents=True, exist_ok=False)
    peer._ACTIVE = dict(root=control, ordinary=ordinary)
    try:
        yield
    finally:
        peer._ACTIVE = None


class Fixture(peer.Fixture):
    def __init__(self, label):
        super().__init__(label)
        self.posts = []
        self.on_prepare = self.on_response = None
        self.empty = False
        self.failure = None
        self.fences = []
        self.calls['post'] = 0

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
                'MEMORY_WIKI_ENV_META_SYNC': '0', 'MEMORY_WIKI_GRAPH_EXTRACT_ENABLED': '1',
                'MEMORY_WIKI_GRAPH_AUTO_EXTRACT': '1', 'MEMORY_WIKI_CODE_GRAPH_ENABLED': '0',
                'MEMORY_WIKI_DOCUMENT_GRAPH_ENABLED': '0', 'MEMORY_WIKI_DOCUMENT_AUTO_SCAN_CACHE': '0',
                'MEMORY_WIKI_LLM_PACK': '0', 'MEMORY_WIKI_GRAPH_EXTRACT_URL': 'http://127.0.0.1:18649/v1',
                'MEMORY_WIKI_GRAPH_EXTRACT_MODEL': 'authored-no-model',
                'MEMORY_WIKI_GRAPH_EXTRACT_TIMEOUT': '3',
                # Nonsecret transport header marker, not an OAuth/key validator.
                'MEMORY_WIKI_GRAPH_EXTRACT_API_KEY': 'authored-header-only',
                'MEMORY_WIKI_EXTRACT_ENABLED': '0',
            }
            for key, value in settings.items():
                self._mp.setenv(key, value)
            for name in ('local', 'roaming'):
                (self.home / name).mkdir()
            self._native = sys.modules['hermes_constants']
            self._native_token = self._native.set_hermes_home_override(self.home)
            spec = importlib.util.spec_from_file_location(self._namespace, SOURCE / '__init__.py',
                submodule_search_locations=[str(SOURCE)])
            self.m = importlib.util.module_from_spec(spec)
            sys.modules[self._namespace] = self.m
            spec.loader.exec_module(self.m)
            m = self.m
            spi, registry, trust = (sys.modules[n] for n in (
                'agent.memory_provider', 'tools.registry', 'hermes_trust_core'))
            assert m.MemoryProvider is spi.MemoryProvider and m.MemoryWikiProvider.__bases__ == (spi.MemoryProvider,)
            assert m.tool_result is registry.tool_result and m.tool_error is registry.tool_error
            assert m._sanitize_recalled is trust.sanitize_recalled and m._IMPORT_HERMES_HOME == self.home
            self.p = m.MemoryWikiProvider()
            self.p.initialize('session-own', hermes_home=str(self.home), bot_id=self.bot_id,
                              project_id='repo-own', agent_context='test')
            self.conn = self.p._connect()
            self.path = self.p.db_path
            assert self.conn is self.p._owned_conn and self.p._lifecycle_state == 'ready'
            assert self.path.is_file()
            self._scopes.enter_context(m._native_profile_scope(self.home))
            self._scopes.enter_context(m._profile_qdrant_scope(self.home))
            doc = sys.modules[self._namespace + '.document_knowledge_graph']
            self._scopes.enter_context(doc._document_profile_scope(self.home))
            m._embedding_cache_state()
            assert self.p._runtime_identity()['profile_ready'] is True
            assert self.p._runtime_identity()['missing_key_names'] == []
            # Actual product request/helper/preparation; only opener transport
            # is authored. Keep urllib.urlopen identity unchanged.
            assert urllib.request.urlopen is sys.modules[self._namespace + '.http_safety']._ORIGINAL_URLOPEN
            self._mp.setattr(urllib.request, 'build_opener', self.opener)
            self.claim(CID, text=TEXT, visibility='bot')
            self.ready()
            self._emit(dict(event='graph_fixture_ready', roles='genuine_SPI_SQL_ACL_erasure; authored_ENV_SQL_opener',
                            native_MemoryManager_auth_YAML='NOT_RUN'))
            return self
        except BaseException as primary:
            self._finish(primary)
            raise

    def opener(self, *handlers):
        assert any(isinstance(h, urllib.request.HTTPRedirectHandler) for h in handlers)
        assert any(isinstance(h, urllib.request.ProxyHandler) and h.proxies == {} for h in handlers)
        if self.on_prepare is not None:
            action, self.on_prepare = self.on_prepare, None
            action()
        return SimpleNamespace(open=self.transport)

    def transport(self, request, timeout):
        assert 0 < timeout <= 3 and not self.conn.in_transaction
        assert request.full_url == 'http://127.0.0.1:18649/v1/chat/completions'
        assert request.get_method() == 'POST' and request.get_header('Authorization') == 'Bearer authored-header-only'
        body = json.loads(request.data)
        source = body['messages'][-1]['content']
        assert source in {TEXT, TEXT.rstrip('.'), AUTO_TEXT, AUTO_TEXT.rstrip('.')}
        self.posts.append(body)
        self.calls['post'] += 1
        self._emit(dict(event='actual_authored_HTTP_sink', canary=TEXT in json.dumps(body), requests=len(self.posts)))
        if self.failure is not None:
            raise self.failure
        proposal = AUTO_PROPOSAL if source.startswith('User owns ') else {**PROPOSAL, 'evidence': source}
        stream = peer.Stream({'choices': [{'message': {'content': json.dumps(
            {'relations': [] if self.empty else [proposal]})}}]})
        self.streams.append(stream)
        if self.on_response is not None:
            action, self.on_response = self.on_response, None
            action()
        return stream

    def call(self, apply=False, direct=False):
        args = dict(claim_id=CID, apply=apply)
        out = self.p._graph_extract_claim(args) if direct else json.loads(
            self.p.handle_tool_call('memory_wiki_graph_extract_claim', args))
        self._emit(dict(event='actual_upper_return', payload=out, requests=len(self.posts)))
        return out

    def _finish(self, primary):
        if not getattr(self, 'safety_close_unknown', False):
            return super()._finish(primary)
        # This is NOT provider recovery. Keep exact quarantine/stage/primary
        # references on the object; close only this fixture's owned handle
        # after the retained production-state assertions/receipt were saved.
        p, c = self.p, self.conn
        assert p._transaction_quarantine is c and p._claim_tx_connection is c
        original = p._transaction_primary
        c.set_authorizer(None)
        sqlite3.Connection.rollback(c)
        c.close()
        assert p._transaction_quarantine is c and p._transaction_primary is original
        self._emit(dict(event='fixture_safety_close_NOT_production_recovery', exact_retained_owner=True))
        self._diag.close()
        self._scopes.close()
        self._native.reset_hermes_home_override(self._native_token)
        sys.modules['__main__']._memory_wiki_instance = self._main_before
        for loaded in tuple(sys.modules):
            if loaded == self._namespace or loaded.startswith(self._namespace + '.'):
                sys.modules.pop(loaded, None)
        self._mp.undo()


def withdraw(case, action='status'):
    if action == 'session':
        case.p.on_session_switch('foreign-session', reset=False)
    elif action == 'erasure':
        with case.p._claim_transaction(case.conn):
            case.p._privacy_erasure.append(case.p, '', claim_ids=[CID], event_ids=[], episode_ids=[], episode_surface='')
    else:
        writer = sqlite3.connect(str(case.path))
        try:
            old = writer.execute('SELECT * FROM claims WHERE id=?', (CID,)).fetchone()
            if action == 'status':
                writer.execute("UPDATE claims SET status='retired' WHERE id=?", (CID,))
            elif action in {'owner', 'ABA'}:
                writer.execute("UPDATE claims SET origin_bot_id='foreign-owner' WHERE id=?", (CID,))
                if action == 'ABA':
                    writer.execute('UPDATE claims SET origin_bot_id=? WHERE id=?', (case.bot_id, CID))
                    assert writer.execute('SELECT * FROM claims WHERE id=?', (CID,)).fetchone() == old
            else:
                raise AssertionError('undeclared_withdrawal')
            writer.commit()
        finally:
            writer.close()
    case._emit(dict(event='completed_original_withdrawal', action=action))


@contextmanager
def schedule(case, seam, action):
    """Deterministic callback fault; no guard/SDK/identity replacement."""
    prior = sys.getprofile()
    assert prior is None
    seen = []
    registry_code = case.m.tool_result.__code__
    def inject(frame, event, arg):
        local = frame.f_locals
        upper_cleanup = False
        if seam == 'cleanup' and event == 'return' and frame.f_code.co_name == '_native_profile_scope':
            caller = frame.f_back
            for _ in range(6):
                if caller is None:
                    break
                if (caller.f_code.co_name == 'scoped' and caller.f_locals.get('__name') == 'handle_tool_call'
                        and caller.f_locals.get('delivery_token') is not None and 'refused' in caller.f_locals):
                    upper_cleanup = True
                caller = caller.f_back
            caller = None
        match = (
            seam == 'validation' and frame.f_code.co_name == '_grounded_relation_clause' and event == 'return'
            or seam == 'serialization' and frame.f_code is registry_code and event == 'return'
                and local.get('kwargs', {}).get('proposals') is not None
            or upper_cleanup
            or seam == 'journal' and event == 'return' and local.get('__name') == '_append_journal_event'
                and isinstance(arg, dict) and local.get('kwargs', {}).get('phase') == 'after'
            or seam == 'mutation' and event == 'return' and local.get('__name') == '_record_mutation'
        )
        if match and not seen:
            seen.append(seam)
            action()
        if event == 'return' and frame.f_code is case.m._DisclosureFence.__init__.__code__:
            fence = local['self']
            if fence.provider is case.p:
                case.fences.append(fence)
    sys.setprofile(inject)
    try:
        yield seen
    finally:
        sys.setprofile(prior)


def denied(out):
    assert not out.get('proposals') and not out.get('relation_ids')
    assert out.get('disclosure_status') == 'withheld' or 'error' in out or out.get('success') is False
