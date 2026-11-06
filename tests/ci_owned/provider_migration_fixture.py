"""Real SPI/SQLite/ACL and optional real disposable Qdrant; no paid model.

Only embedding/model-list responses are synthetic. The Qdrant branch uses the
real no-redirect opener against the caller's isolated loopback test server.
No SDK, source fence, visibility policy, registry or readiness predicate is
replaced. Both principals are native provider instances for synthetic owners.
"""
from __future__ import annotations

from contextlib import ExitStack
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sqlite3
import sys
import urllib.parse

import pytest

SOURCE = Path(__file__).resolve().parents[2]
MODEL = 'qwen/qwen3-embedding-0.6b'
VECTOR_NOUS = [1.0] + [0.0] * 7
VECTOR_OPENROUTER = [0.0, 1.0] + [0.0] * 6
INERT_AUTH = 'inert-synthetic-migration-transport-not-a-credential'


class Response:
    def __init__(self, payload):
        raw = json.dumps(payload).encode('utf-8')
        self._stream = io.BytesIO(raw)
        self.headers = {'Content-Length': str(len(raw))}
        self.status = 200
        self.closed = False

    def read(self, amount):
        return self._stream.read(amount)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self._stream.close()
        self.closed = True


class MigrationFixture:
    def __init__(self, root, monkeypatch):
        self.root = root
        self.home = root / 'home'
        self.mp = monkeypatch
        self.stack = ExitStack()
        self.providers = []
        self.modules = []
        self.embedding_posts = []
        self.qdrant_requests = []
        self.foreign_text = 'Owner B only: migration cobalt nebula receiver calibration.'
        self.own_text = 'Owner A only: migration amber cactus receiver calibration.'
        self.before_request = None
        self.fail_request = None
        self.responses = []
        self.native = sys.modules['hermes_constants']
        self._native_token = None
        self._main_before = getattr(sys.modules['__main__'], '_memory_wiki_instance', None)
        self.vector_url = os.environ['MW_MIGRATION_TEST_QDRANT_URL'].rstrip('/')
        self.namespace = hashlib.sha256(str(root).encode()).hexdigest()[:8]
        parsed = urllib.parse.urlsplit(self.vector_url)
        assert parsed.scheme == 'http' and parsed.hostname == '127.0.0.1'
        assert not parsed.username and not parsed.password and not parsed.path
        assert parsed.port == 6333

    def __enter__(self):
        self.home.mkdir(parents=True, exist_ok=False)
        # This fixture runs only in the explicitly isolated child. No live
        # dotenv/config/credential source is inherited or read by its importer.
        for key in tuple(os.environ):
            if any(word in key.lower() for word in ('api_key', 'token', 'password', 'credential', 'secret')):
                self.mp.delenv(key, raising=False)
        settings = {
            'HERMES_HOME': str(self.home), 'HOME': str(self.home),
            'USERPROFILE': str(self.home), 'APPDATA': str(self.home / 'roaming'),
            'LOCALAPPDATA': str(self.home / 'local'),
            'HERMES_SECURITY_STRICT': '1', 'MEMORY_WIKI_STRICT_RECALL': '1',
            'MEMORY_WIKI_SEMANTIC': '0', 'MEMORY_WIKI_EMBED_MODEL': MODEL,
            'MEMORY_WIKI_EMBED_DIMENSIONS': '8', 'MEMORY_WIKI_VECTOR_SIZE': '8',
            'MEMORY_WIKI_EMBED_API_KEY': INERT_AUTH,
            'MEMORY_WIKI_EMBED_CACHE_MAX_ENTRIES': '0',
            'MEMORY_WIKI_EMBED_INPUT_MAX_CHARS': '1400',
            'MEMORY_WIKI_QUERY_INSTRUCTION': '', 'MEMORY_WIKI_DOCUMENT_PREFIX': '',
            'MEMORY_WIKI_QDRANT_URL': self.vector_url,
            'MEMORY_WIKI_QDRANT_COLLECTION': 'migration_claims_' + self.namespace,
            'MEMORY_WIKI_QDRANT_ALIAS': 'migration_active_' + self.namespace,
            'MEMORY_WIKI_QDRANT_ALIAS_MODE': 'require',
            'MEMORY_WIKI_EPISODIC_QDRANT_COLLECTION': 'migration_episodes_' + self.namespace,
            'MEMORY_WIKI_RERANK_ENABLED': '0',
            'MEMORY_WIKI_BACKGROUND_JOBS_ENABLED': '0',
            'MEMORY_WIKI_EPISODIC_ENABLED': '0', 'MEMORY_WIKI_EPISODIC_SEMANTIC': '0',
            'MEMORY_WIKI_EVENT_LEDGER_ENABLED': '0', 'MEMORY_WIKI_OBSERVATIONS_ENABLED': '0',
            'MEMORY_WIKI_ENV_META_SYNC': '0', 'MEMORY_WIKI_GRAPH_EXTRACT_ENABLED': '0',
            'MEMORY_WIKI_GRAPH_AUTO_EXTRACT': '0', 'MEMORY_WIKI_LLM_PACK': '0',
            'MEMORY_WIKI_INCLUDE_SESSIONS_IN_PACK': '0',
            'MEMORY_WIKI_CODE_GRAPH_ENABLED': '0', 'MEMORY_WIKI_DOCUMENT_GRAPH_ENABLED': '0',
            'MEMORY_WIKI_DOCUMENT_AUTO_SCAN_CACHE': '0',
        }
        for key, value in settings.items():
            self.mp.setenv(key, value)
        self._native_token = self.native.set_hermes_home_override(self.home)
        try:
            self.old = self.load('nous')
            self.old_a = self.create_owner(self.old, 'a')
            self.old_b = self.create_owner(self.old, 'b')
            self.ids = {}
            for label, provider, text, scope in (
                ('a_private', self.old_a, self.own_text, 'private'),
                ('a_chat', self.old_a, self.own_text + ' Chat-only operating note.', 'chat'),
                ('b_private', self.old_b, self.foreign_text, 'private'),
                ('b_chat', self.old_b, self.foreign_text + ' Chat-only operating note.', 'chat'),
            ):
                cid = provider._add_claim(text, topic='general', source='memory_tool:synthetic',
                    confidence=.95, salience=.95, visibility_scope=scope)
                assert cid.startswith('c_'), cid
                self.ids[label] = cid
            self.old.SEMANTIC_ENABLED = True
            self.old_target = self.old._physical_collection_name()
            assert self.old._ensure_collection(self.old_target)
            for label, cid in self.ids.items():
                provider = self.old_a if label.startswith('a_') else self.old_b
                conn = provider._connect()
                row = conn.execute('SELECT id FROM claims WHERE id=?', (cid,)).fetchone()
                with provider._claim_transaction(conn):
                    self.old._record_claim_vector_target(conn, cid, collection=self.old_target,
                        manifest_hash=self.old._manifest_hash(self.old._embedding_manifest()),
                        status='write_pending')
                fence = self.old._DisclosureFence(provider, conn)
                image = fence.index_claim(row, 'full_reindex')
                vector = self.old._embed_document(image['normalized_claim'], _admit=fence.admit_index)
                assert vector == VECTOR_NOUS
                payload = self.old._qdrant_claim_payload(cid, image['normalized_claim'], image)
                payload.pop('claim')
                assert self.old._qdrant_upsert(cid, vector, payload, self.old_target,
                                               _admit=fence.admit_index)
                fence.admit_index()
                with provider._claim_transaction(conn):
                    self.old._record_claim_vector_target(conn, cid, collection=self.old_target,
                        manifest_hash=self.old._manifest_hash(self.old._embedding_manifest()),
                        status='active', indexed_at=self.old.now())
            assert self.old._switch_alias(self.old_target)
            self.old_hash = self.old._manifest_hash(self.old._embedding_manifest())
            self.old_state = self.old._qdrant_claim_state(self.old_target)
            assert set(self.old_state) == set(self.ids.values())
            # The old instances remain real, but do not run against new settings.
            for p in (self.old_a, self.old_b):
                p.shutdown()
            self.m = self.load('openrouter')
            self.a = self.create_owner(self.m, 'a')
            self.b = self.create_owner(self.m, 'b')
            self.m.SEMANTIC_ENABLED = True
            self.new_hash = self.m._manifest_hash(self.m._embedding_manifest())
            assert self.new_hash != self.old_hash
            assert self.m.EMBED_PROVIDER == 'openrouter'
            assert self.m._embedding_manifest()['dimensions'] == 8
            self.embedding_posts.clear()
            self.qdrant_requests.clear()
            return self
        except BaseException:
            self.close()
            raise

    def load(self, provider):
        self.mp.setenv('MEMORY_WIKI_EMBED_PROVIDER', provider)
        self.mp.setenv('MEMORY_WIKI_EMBED_URL',
            'https://inference-api.nousresearch.com/v1' if provider == 'nous' else 'https://openrouter.ai/api/v1')
        name = '_migration_' + hashlib.sha256((str(self.home) + provider).encode()).hexdigest()[:16]
        spec = importlib.util.spec_from_file_location(name, SOURCE / '__init__.py',
                                                    submodule_search_locations=[str(SOURCE)])
        module = importlib.util.module_from_spec(spec)
        self.mp.setitem(sys.modules, name, module)
        spec.loader.exec_module(module)
        spi, registry, trust = (sys.modules[n] for n in
                               ('agent.memory_provider', 'tools.registry', 'hermes_trust_core'))
        assert module.MemoryProvider is spi.MemoryProvider
        assert module.MemoryWikiProvider.__bases__ == (spi.MemoryProvider,)
        assert module.tool_result is registry.tool_result
        assert module._INJECTION_GUARD_AVAILABLE and module._sanitize_recalled is trust.sanitize_recalled
        assert module._set_native_home is self.native.set_hermes_home_override
        assert Path(module._IMPORT_HERMES_HOME) == self.home
        assert module.EMBED_CONTRACT_VALID
        original = module._urlopen_no_redirect
        self.mp.setattr(module, '_urlopen_no_redirect',
                        lambda request, timeout, m=module, op=original: self.transport(m, op, request, timeout))
        self.modules.append(module)
        return module

    def create_owner(self, module, suffix):
        provider = module.MemoryWikiProvider()
        self.providers.append(provider)
        provider.initialize('migration-chat-' + suffix, hermes_home=str(self.home),
                            bot_id='migration-owner-' + suffix, agent_context='test')
        conn = provider._connect()
        assert conn is provider._owned_conn and provider._lifecycle_state == 'ready'
        assert provider._runtime_identity()['profile_ready'] is True
        assert provider._runtime_identity()['conn_path_matches'] is True
        conn.execute('PRAGMA temp_store=MEMORY')
        return provider

    def transport(self, module, opener, request, timeout):
        url = request.full_url
        method = request.get_method()
        body = json.loads(request.data) if request.data is not None else None
        if url.startswith(self.vector_url + '/'):
            assert not request.has_header('Authorization') and not request.has_header('Api-key')
            event = (method, urllib.parse.urlsplit(url).path, body)
            self.qdrant_requests.append(event)
            if self.before_request is not None:
                self.before_request(event)
            if self.fail_request is not None:
                self.fail_request(event)
            return opener(request, timeout=timeout)  # Real Qdrant HTTP, not a dictionary stand-in.
        assert url.startswith(module.EMBED_URL + '/')
        assert request.get_header('Authorization') == 'Bearer ' + INERT_AUTH
        if method == 'GET' and url.endswith('/models'):
            payload = {'data': [{'id': MODEL}]}
        else:
            assert method == 'POST' and url.endswith('/embeddings')
            assert body['model'] == MODEL and body['dimensions'] == 8
            self.embedding_posts.append({'provider':module.EMBED_PROVIDER,'input':body['input']})
            payload = {'data': [{'embedding': VECTOR_NOUS if module.EMBED_PROVIDER == 'nous'
                                 else VECTOR_OPENROUTER}]}
        response = Response(payload)
        self.responses.append(response)
        return response

    def public(self, owner='a', **args):
        p = self.a if owner == 'a' else self.b
        return json.loads(p.handle_tool_call('memory_wiki_reindex', args))

    def alias(self):
        return self.m._qdrant_alias_target()

    def old_unchanged(self):
        return self.m._qdrant_claim_state(self.old_target) == self.old_state

    def close(self):
        try:
            for p in reversed(self.providers):
                if getattr(p, '_conn', None) is not None:
                    p.shutdown()
            assert all(response.closed for response in self.responses)
        finally:
            if self._native_token is not None:
                self.native.reset_hermes_home_override(self._native_token)
                self._native_token = None
            if self._main_before is None:
                if hasattr(sys.modules['__main__'], '_memory_wiki_instance'):
                    del sys.modules['__main__']._memory_wiki_instance
            else:
                sys.modules['__main__']._memory_wiki_instance = self._main_before
            self.stack.close()

    def __exit__(self, *args):
        self.close()


@pytest.fixture
def provider_migration_case(tmp_path, monkeypatch):
    with MigrationFixture(tmp_path / 'provider-migration', monkeypatch) as fixture:
        yield fixture
