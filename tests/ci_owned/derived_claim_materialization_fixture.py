"""Direct genuine SPI/SQLite derivatives; no host, model or protected config.

Reuse the shipped document fixture's ownership/diagnostic/teardown layout.
The parser seam runs the real plain-text extractor in-process; no worker child.
Faults use native SQLite authorizers/triggers and exact Python callback seams,
never a replacement provider, SDK, ACL, profile-ready or claim producer.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import threading

import pytest

_SPEC = importlib.util.spec_from_file_location(
    'derived_document_peer', Path(__file__).with_name('document_egress_fixture.py'))
peer = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = peer
_SPEC.loader.exec_module(peer)
SOURCE = Path(__file__).resolve().parents[2]
TEXT = ('The Boreal archive retains verified transaction records with deterministic '
        'recovery, immutable source revisions, explicit ownership and reliable daily integrity checks.')
NEW_TEXT = ('The Cedar scheduler preserves durable queued operations with bounded '
            'retries, exact source provenance, independent validation and atomic publication boundaries.')


@pytest.fixture
def derived_case(request, tmp_path_factory):
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
    def __enter__(self):
        self.home.mkdir(parents=True, exist_ok=False)
        self._diag = (self.dir / 'observations.jsonl').open('x', encoding='utf-8')
        try:
            assert sys.getprofile() is None
            for key in tuple(os.environ):
                if re.search(r'(?i)(api_?key|token|password|credential|secret)', key):
                    self._mp.delenv(key, raising=False)
            settings = {
                'HERMES_HOME': str(self.home), 'HOME': str(self.home), 'USERPROFILE': str(self.home),
                'APPDATA': str(self.home / 'roaming'), 'LOCALAPPDATA': str(self.home / 'local'),
                'HERMES_SECURITY_STRICT': '1', 'MEMORY_WIKI_STRICT_RECALL': '1',
                'MEMORY_WIKI_BOT_ID': self.bot_id, 'MEMORY_WIKI_PROJECT_ID': 'repo-own',
                'MEMORY_WIKI_SEMANTIC': '0', 'MEMORY_WIKI_EMBED_PROVIDER': 'stub',
                'MEMORY_WIKI_EMBED_MODEL': 'hash-ngram-8', 'MEMORY_WIKI_EMBED_DIMENSIONS': '8',
                'MEMORY_WIKI_VECTOR_SIZE': '8', 'MEMORY_WIKI_EMBED_CACHE_MAX_ENTRIES': '0',
                'MEMORY_WIKI_QDRANT_ALIAS_MODE': 'physical',
                'MEMORY_WIKI_BACKGROUND_JOBS_ENABLED': '0', 'MEMORY_WIKI_RERANK_ENABLED': '0',
                'MEMORY_WIKI_EPISODIC_ENABLED': '0', 'MEMORY_WIKI_EPISODIC_SEMANTIC': '0',
                'MEMORY_WIKI_EVENT_LEDGER_ENABLED': '0', 'MEMORY_WIKI_OBSERVATIONS_ENABLED': '0',
                'MEMORY_WIKI_ENV_META_SYNC': '0', 'MEMORY_WIKI_GRAPH_EXTRACT_ENABLED': '0',
                'MEMORY_WIKI_GRAPH_AUTO_EXTRACT': '0', 'MEMORY_WIKI_CODE_GRAPH_ENABLED': '0',
                'MEMORY_WIKI_CODE_GRAPH_EMBED': '1', 'MEMORY_WIKI_CODE_GRAPH_EMBED_MAX_UNITS': '0',
                'MEMORY_WIKI_DOCUMENT_GRAPH_ENABLED': '0', 'MEMORY_WIKI_DOCUMENT_AUTO_SCAN_CACHE': '0',
                'MEMORY_WIKI_LLM_PACK': '0', 'MEMORY_WIKI_EXTRACT_ENABLED': '0',
                'MEMORY_WIKI_DOCUMENT_ACCESS_SCOPE_ID': 'repo-own',
                'MEMORY_WIKI_DOCUMENT_ACCESS_REPOSITORY_ID': 'repo-own',
                'MEMORY_WIKI_DOCUMENT_ALLOW_CROSS_SCOPE': '0',
                'MEMORY_WIKI_DOCUMENT_ALLOW_SCOPE_MIGRATION': '0',
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
            assert 'agent.memory_manager' not in sys.modules and 'hermes_cli.config' not in sys.modules
            self.p = m.MemoryWikiProvider()
            self.p.initialize('session-own', hermes_home=str(self.home), bot_id=self.bot_id,
                              project_id='repo-own', agent_context='test')
            self.conn = self.p._connect()
            self.path = self.p.db_path
            assert self.conn is self.p._owned_conn and self.p._lifecycle_state == 'ready'
            assert self.path.is_file() and not self.conn.in_transaction
            self.doc = sys.modules[self._namespace + '.document_knowledge_graph']
            self.code = sys.modules[self._namespace + '.code_knowledge_graph']
            self._scopes.enter_context(m._native_profile_scope(self.home))
            self._scopes.enter_context(m._profile_qdrant_scope(self.home))
            self._scopes.enter_context(self.doc._document_profile_scope(self.home))
            assert self.p._runtime_identity()['profile_ready'] is True
            assert self.p._runtime_identity()['missing_key_names'] == []
            extractor = sys.modules[self._namespace + '.document_extractors']
            self._mp.setattr(self.doc, '_extract', lambda snapshot, args: extractor.extract_document(
                snapshot, args.get('_effective_extraction_options')))
            # Real SQL enqueue is exercised; this existing recovery flag prevents
            # starting external semantic workers. It is not an authority override.
            self.p._journal_recovery_active = True
            self.callbacks = []
            self._emit(dict(event='derived_fixture_ready', roles='genuine_SPI_registry_trust_ENV_SQLite_claim_patch',
                            parser='actual_plain_extractor_in_process', native_host_model_network='NOT_RUN'))
            return self
        except BaseException as primary:
            self._finish(primary)
            raise

    def ingest(self, name='source', text=TEXT, *, embed=False):
        path = self.home / 'cache/documents' / (name + '.txt')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
        result = self.doc.ingest_document(self.p, dict(path=str(path), embed=embed))
        assert result.get('source_id') and result.get('revision_id'), result
        self._emit(dict(event='actual_document_ingest', result=result))
        return result

    def embed(self, source_id=''):
        result = self.doc.embed_pending_documents(self.p, dict(source_id=source_id, limit=100))
        self._emit(dict(event='actual_document_materialization', result=result))
        return result

    def snapshot(self, event_id='snapshot-old', *, text=TEXT, repo='repo-own',
                 file='src/main.py', symbol='main', chunk='chunk-main', mode='full', files=None):
        digest = hashlib.sha256(text.encode()).hexdigest()
        event = dict(event_version=2, type='code_graph_snapshot', graph_schema_version=1,
                     producer='code-shrinker', repository_id=repo, event_id=event_id,
                     snapshot_mode=mode, commit_sha=hashlib.sha1(event_id.encode()).hexdigest(),
                     files=files or [dict(file_path=file, file_hash=digest, language='python', line_count=3)],
                     chunks=[dict(chunk_id=chunk, file_path=file, symbol_id=symbol, qualified_name=symbol,
                                  start_line=1, end_line=3, chunk_text=text, embedding_text=text,
                                  content_hash=digest)])
        result = self.code.ingest_code_graph_event(self.p, event)
        assert result.get('status') == 'completed', result
        self._emit(dict(event='actual_code_snapshot', result=result))
        return event, result

    def patch(self, name='verified-patch', *, file='src/main.py', repo='repo-own',
              new_hash=None, outcome='verified applied', per_file=None):
        # Genuine supported two-file patch. Its per-file hashes reach the real
        # invalidator; no raw digest is copied into the outcome prose. The
        # single-file summary-hash path needs secret-core, outside this packet.
        digest = new_hash or hashlib.sha256(NEW_TEXT.encode()).hexdigest()
        event = dict(event_version=1, type='patch_applied', producer='code-shrinker',
                     event_id='event-' + name, repository_id=repo, patch_id=name, outcome=outcome,
                     commit_sha=hashlib.sha1(name.encode()).hexdigest()[:7],
                     changed_files=[file, 'src/auxiliary.py'],
                     per_file=per_file if per_file is not None else [
                         dict(file_path=file, new_content_hash=digest),
                         dict(file_path='src/auxiliary.py', new_content_hash=digest)])
        result = self.p._apply_code_shrinker_patch_event(event)
        self._emit(dict(event='actual_patch_application', result=result))
        return event, result

    def backfill(self, repo='repo-own'):
        result = self.code.embed_pending_chunks(self.p, dict(repository_id=repo, limit=100))
        self._emit(dict(event='actual_code_backfill', result=result))
        return result

    def durable(self):
        reader = sqlite3.connect(str(self.path))
        try:
            tables = ('claims', 'evidence', 'memory_mutations', 'claim_write_fingerprints',
                      'index_outbox', 'claims_fts', 'document_chunks', 'code_graph_chunks',
                      'code_graph_chunks_fts', 'patch_outcomes', 'integration_events')
            rows = {table: reader.execute('SELECT * FROM ' + table + ' ORDER BY rowid').fetchall()
                    for table in tables}
            result = {table: len(items) for table, items in rows.items()}
            result['images'] = {table: hashlib.sha256(json.dumps(items, separators=(',', ':')).encode()).hexdigest()
                                for table, items in rows.items()}
        finally:
            reader.close()
        self._emit(dict(event='independent_durable_read', state=result))
        return result

    def _finish(self, primary):
        if not getattr(self, 'safety_close_unknown', False):
            return super()._finish(primary)
        p, c = self.p, self.conn
        assert p._transaction_quarantine is c
        owner = p._claim_tx_connection
        original, stage = p._transaction_primary, p._claim_tx_document_stage
        c.set_authorizer(None)
        sqlite3.Connection.rollback(c)
        c.close()
        assert p._transaction_quarantine is c and p._transaction_primary is original
        assert p._claim_tx_document_stage is stage and p._claim_tx_connection is owner
        self._emit(dict(event='fixture_safety_close_NOT_production_recovery', exact_owner_primary_stage_retained=True))
        self._diag.close()
        self._scopes.close()
        self._native.reset_hermes_home_override(self._native_token)
        sys.modules['__main__']._memory_wiki_instance = self._main_before
        for loaded in tuple(sys.modules):
            if loaded == self._namespace or loaded.startswith(self._namespace + '.'):
                sys.modules.pop(loaded, None)
        self._mp.undo()


@contextmanager
def observe_callbacks(case):
    """Passive observer: real postcommit callable and independent durable link."""
    assert sys.getprofile() is None
    code = peer.unwrapped(case.p._after_claim_commit).__code__
    thread = threading.get_ident()
    def observer(frame, event, arg):
        if event == 'call' and frame.f_code is code and frame.f_locals.get('self') is case.p:
            assert threading.get_ident() == thread
            cid = frame.f_locals['cid']
            reader = sqlite3.connect(str(case.path))
            try:
                linked = reader.execute('SELECT COUNT(*) FROM document_chunks WHERE active=1 AND embedding_claim_id=?', (cid,)).fetchone()[0]
                durable_claim = reader.execute('SELECT COUNT(*) FROM claims WHERE id=?', (cid,)).fetchone()[0]
            finally:
                reader.close()
            case.callbacks.append(dict(cid=cid, idle=not case.conn.in_transaction,
                                       durable_links=linked, durable_claims=durable_claim))
    sys.setprofile(observer)
    try:
        yield case.callbacks
    finally:
        sys.setprofile(None)


@contextmanager
def callback_seam(case, method, action, *, event='return'):
    """One exact same-thread provider callback, with no callable replacement."""
    assert sys.getprofile() is None
    code = peer.unwrapped(getattr(case.p, method)).__code__
    seen = []
    def inject(frame, kind, result):
        if kind == event and frame.f_code is code and frame.f_locals.get('self') is case.p and not seen:
            seen.append(method)
            action()
    sys.setprofile(inject)
    try:
        yield seen
    finally:
        sys.setprofile(None)


@contextmanager
def deny_link(case, *, rollback=False, commit=False):
    """Actual native known SQL DENY, or retained UNKNOWN on rollback DENY."""
    seen = []
    def authorizer(op, one, two, db, trigger):
        denied = (not commit and op == sqlite3.SQLITE_UPDATE and one == 'document_chunks' and two == 'embedding_claim_id'
                  or rollback and op == sqlite3.SQLITE_TRANSACTION and one == 'ROLLBACK'
                  or commit and op == sqlite3.SQLITE_TRANSACTION and one == 'COMMIT'
                     and not any(row[1] == 'COMMIT' for row in seen))
        if denied:
            seen.append((op, one, two))
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK
    case.conn.set_authorizer(authorizer)
    try:
        yield seen
    finally:
        case.conn.set_authorizer(None)
