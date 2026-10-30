"""SC2: genuine direct-provider/SQLite fixture with authored SQL and HTTP.

Peer is shipped; regular pytest owns its tmp_path when no parent packet root
is supplied. No model/socket/MemoryManager execution or protected file writes.
The explicit parent packet keeps its own root and stronger offline audit fence.
"""
from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import sys
from types import SimpleNamespace, MethodType
from contextlib import ExitStack

import pytest

SOURCE = Path(os.environ.get('SC2_SOURCE_ROOT', str(Path(__file__).resolve().parents[2])))
QUERY = 'needle semantic retrieval'
SAFE = 'Verified durable navigation remains within the current source boundary.'
SOURCE_FILES = ('__init__.py', 'background_jobs.py', 'code_knowledge_graph.py', 'collapse.py', 'current_scope_reindex.py', 'decay.py', 'disclosure_fence.py', 'document_extractors.py', 'document_knowledge_graph.py', 'document_worker.py', 'entity_relation_extractor.py', 'episodic_memory.py', 'extractor.py', 'github_source_adapter.py', 'google_drive_source_adapter.py', 'guard.py', 'http_safety.py', 'memory_events.py', 'memory_observations.py', 'migrations.py', 'online_metrics.py', 'outbox_repair_policy.py', 'patch_secret_context_plugin.py', 'privacy_erasure.py', 'recall_orchestrator.py', 'recall_planner.py', 'sdk.py', 'secret_context_bridge.py', 'semantic_io.py', 'setup.py', 'shared_blocks.py', 'source_connectors.py', 'source_file_observation.py', 'spreadsheet_formulas.py', 'vault.py', 'vault_aead.py', 'vault_registry_adapter.py', 'visual_evidence.py')
# Historical runtime inventory: 284062dc8ce12475ec3714854e8033760d08f5166b7f8cab1dd4c79e93574b6c
# Historical rebound to the 1.24.6 runtime source; no authority from this hash.
# Historical 1.24.6 fixed inventory witness, retained unchanged.
HISTORICAL_SOURCE_INVENTORY_SHA256_1_24_6 = '8f7c7cd40277064072e897284cfcf613578bab6d98ee9d206941f10b035c2c17'
# Historical complete37 observation composition, retained as an exact witness.
HISTORICAL_SOURCE_INVENTORY_SHA256_OBSERVATION_37 = '87e8e1113b3b607d31444fe1b3e4c553c4533551a65c0b88bb32613ae5cdfd29'
# Current complete38 runtime roster, frozen after the addressed-outbox correction.
# Expected is literal, never derived from current input at test time.
SOURCE_INVENTORY_SHA256 = '4c37f37453c31671d0b3faeed8d01c406af72f7d8f9373664bf8dabb0e26fe12'
CASE_IDS = ('sc2_healthy', 'sc2_disabled_initial', 'sc2_late_status_before_rank', 'sc2_late_status_before_http', 'sc2_late_owner_before_http', 'sc2_sql_ABA_before_http', 'sc2_session_before_http', 'sc2_generation_before_http', 'sc2_cache_healthy', 'sc2_cache_late_revoke', 'sc2_response_revoke', 'sc2_tail_false_discards_cache', 'sc2_tail_baseexception_discards_cache', 'sc2_tail_baseexception_preserves_replacement', 'sc3_healthy_cache', 'sc3_unavailable_initial', 'sc3_late_delete_before_http', 'sc3_sql_ABA_before_http', 'sc3_session_before_http', 'sc3_generation_before_http', 'sc3_cache_late_revoke', 'sc3_response_revoke')
CASE_IDS += ('sc4_healthy_cache', 'sc4_ineligible_initial', 'sc4_late_retire_before_http',
             'sc4_sql_ABA_before_http', 'sc4_session_before_http', 'sc4_generation_before_http',
             'sc4_cache_late_revoke', 'sc4_response_revoke')
PREREQUISITE_BLOCKERS = {}  # CURRENT v2 contract below; original blocked gold preserved.
_ACTIVE = None
N = P = doc = code = io_source = Baseline = None

def require(condition, code):
    if not condition:
        raise RuntimeError('RI_R03_PREREQUISITE:' + code)


def no_links(path):
    for item in (path, *path.parents):
        try:
            s = item.lstat()
        except FileNotFoundError:
            continue
        require(not stat.S_ISLNK(s.st_mode) and not getattr(s, 'st_file_attributes', 0) & 1024,
                'owned_path_has_link_or_reparse')


def unwrapped(fn):
    while hasattr(fn, '__wrapped__'):
        fn = fn.__wrapped__
    return fn


@pytest.fixture
def ri_r03_case(request, tmp_path_factory):
    global _ACTIVE
    original = request.node.name.removeprefix('test_')
    require(original in CASE_IDS, 'unknown_original_id')
    # Конкретный статически незамкнутый контракт не превращаем в зелёный stub.
    require(original not in PREREQUISITE_BLOCKERS,
            PREREQUISITE_BLOCKERS.get(original, ''))
    raw_root = os.environ.get('RI_R03_TEST_ROOT', '')
    # numbered=False avoids pytest's optional per-case 'current' symlink.
    root = (Path(raw_root) if raw_root else tmp_path_factory.mktemp(
        'document-egress-' + hashlib.sha256(request.node.nodeid.encode()).hexdigest()[:16],
        numbered=False))
    require(root.is_absolute() and '..' not in root.parts,
            'owned_absolute_test_root_required')
    no_links(root)
    ordinary = sys.modules.get('memory_wiki')
    require(ordinary is not None and Path(ordinary.__file__).resolve() == SOURCE / '__init__.py',
            'parent_genuine_direct_entry_required')
    # A full-suite sibling may import MemoryManager; this fixture never runs it.
    observed_pins = {}
    for name in SOURCE_FILES:
        target = SOURCE / name
        no_links(target)
        observed_pins[name] = hashlib.sha256(target.read_bytes()).hexdigest()
    fingerprint = hashlib.sha256(json.dumps(observed_pins, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    require(fingerprint == SOURCE_INVENTORY_SHA256, 'readonly_source_drift')
    control = root / 'diagnostics' / 'controls' / hashlib.sha256(request.node.nodeid.encode()).hexdigest()[:16]
    no_links(control)
    control.mkdir(parents=True, exist_ok=False)
    require(_ACTIVE is None, 'concurrent_fixture_not_admitted')
    _ACTIVE = {'root': control, 'ordinary': ordinary}
    try:
        yield
    finally:
        _ACTIVE = None


class Stream:
    """Полный bounded BytesIO+Content-Length; не реальное HTTP-соединение."""
    def __init__(self, payload):
        raw = json.dumps(payload).encode('utf-8')
        self.fp = io.BytesIO(raw)
        self.headers = {'Content-Length': str(len(raw))}
        self.status = 200
        self.closed = False
    def read(self, amount):
        return self.fp.read(amount)
    def __enter__(self):
        return self
    def __exit__(self, *exc):
        self.close()
    def close(self):
        self.fp.close()
        self.closed = True


class Fixture:
    """Reused genuine constructor/migrate/owner/guards; authored HTTP streams only."""
    def __init__(self, label, *, bot_id="bot-own", cache_ttl=0, rank_claim_ids=()):
        require(_ACTIVE is not None, 'pytest_fixture_scope_missing')
        self.dir = _ACTIVE['root'] / label
        self.home = self.dir / 'home'
        self.p = self.conn = self.m = None
        self.bot_id = bot_id
        self.cache_ttl = cache_ttl
        self.rank_claim_ids = tuple(rank_claim_ids)  # Explicit authored claim transport cohort.
        self.rank_documents = []
        self._mp = pytest.MonkeyPatch()
        self._scopes = ExitStack()
        self._native_token = None
        self._prior_profile = None
        self._profiling = False
        self._namespace = '_ri_r03_' + _ACTIVE['root'].name + '_' + label.replace('-', '_')
        self._diag = None
        self._diag_bytes = 0
        self._observer_errors = []
        self.calls = dict(health=0, qdrant_metadata=0, embed=0, vector=0, rank=0, rerank_body=0, unexpected=0)
        self.vector_scores = {}
        self.vector_filters, self.rerank_ids, self.streams = [], [], []
        self.stages = []
        self.receipt = {}
        self.rank_failure = False
        self._semantic_enabled = True
        self._witness_seen = 0
        self._main_before = getattr(sys.modules['__main__'], '_memory_wiki_instance', None)

    @property
    def semantic_enabled(self):
        return self._semantic_enabled

    @semantic_enabled.setter
    def semantic_enabled(self, enabled):
        # Настоящий opt-out feature flag ДО capture нового запроса, не guard override.
        self._semantic_enabled = bool(enabled)
        self.m.SEMANTIC_ENABLED = bool(enabled)

    def __enter__(self):
        global N, P, doc, code, io_source, Baseline
        self.home.mkdir(parents=True, exist_ok=False)
        self._diag = (self.dir / 'observations.jsonl').open('x', encoding='utf-8')
        try:
            require(sys.getprofile() is None, 'existing_profiler_not_replaced')
            # Это только собственный дочерний fixture process, не профиль владельца.
            for key in tuple(os.environ):
                if re.search(r'(?i)(api_?key|token|password|credential|secret)', key):
                    self._mp.delenv(key, raising=False)
            settings = {
                'HERMES_HOME': str(self.home), 'HOME': str(self.home), 'USERPROFILE': str(self.home),
                'APPDATA': str(self.home / 'roaming'), 'LOCALAPPDATA': str(self.home / 'local'),
                'HERMES_SECURITY_STRICT': '1', 'MEMORY_WIKI_STRICT_RECALL': '1',
                'MEMORY_WIKI_BOT_ID': self.bot_id, 'MEMORY_WIKI_PROJECT_ID': 'repo-own',
                'MEMORY_WIKI_SEMANTIC': '0',  # initialize без outbox/network workers
                'MEMORY_WIKI_EMBED_PROVIDER': 'stub', 'MEMORY_WIKI_EMBED_MODEL': 'hash-ngram-8',
                'MEMORY_WIKI_EMBED_DIMENSIONS': '8', 'MEMORY_WIKI_VECTOR_SIZE': '8',
                'MEMORY_WIKI_VECTOR_TOP_K': '3', 'MEMORY_WIKI_EMBED_CACHE_MAX_ENTRIES': '0',
                'MEMORY_WIKI_EMBED_URL': 'https://synthetic.invalid/embed',
                'MEMORY_WIKI_QDRANT_URL': 'https://synthetic.invalid/vector',
                'MEMORY_WIKI_QDRANT_COLLECTION': 'source_claims',
                'MEMORY_WIKI_EPISODIC_QDRANT_COLLECTION': 'source_episodes',
                'MEMORY_WIKI_QDRANT_ALIAS': 'source_alias', 'MEMORY_WIKI_QDRANT_ALIAS_MODE': 'physical',
                'MEMORY_WIKI_EMBED_INPUT_MAX_CHARS': '1400',
                'MEMORY_WIKI_QUERY_INSTRUCTION': '', 'MEMORY_WIKI_DOCUMENT_PREFIX': '',
                'MEMORY_WIKI_RERANK_ENABLED': '1',
                'MEMORY_WIKI_RERANK_URL': 'https://synthetic.invalid/rank',
                'MEMORY_WIKI_RERANK_MODEL': 'synthetic-no-model', 'MEMORY_WIKI_RERANK_API_STYLE': 'voyage',
                # Не credential и не embed/profile-ready обход: authored rank transport marker.
                'MEMORY_WIKI_RERANK_API_KEY': 'inert-authored-only',
                'MEMORY_WIKI_RERANK_TOP_K': '20', 'MEMORY_WIKI_RERANK_MIN_CANDIDATES': '3',
                'MEMORY_WIKI_RERANK_CACHE_TTL': str(self.cache_ttl), 'MEMORY_WIKI_RERANK_DOCUMENT_MAX_CHARS': '600',
                'MEMORY_WIKI_RERANK_SKIP_EXACT_TECHNICAL': '0', 'MEMORY_WIKI_RERANK_RULES_ENABLED': '0',
                'MEMORY_WIKI_RERANK_WEIGHT_TECHNICAL': '1', 'MEMORY_WIKI_RERANK_WEIGHT_MIXED': '1',
                'MEMORY_WIKI_BACKGROUND_JOBS_ENABLED': '0', 'MEMORY_WIKI_EPISODIC_ENABLED': '0',
                'MEMORY_WIKI_EPISODIC_SEMANTIC': '0', 'MEMORY_WIKI_EVENT_LEDGER_ENABLED': '0',
                'MEMORY_WIKI_OBSERVATIONS_ENABLED': '0', 'MEMORY_WIKI_LLM_PACK': '0',
                'MEMORY_WIKI_INCLUDE_SESSIONS_IN_PACK': '0', 'MEMORY_WIKI_CODE_GRAPH_ENABLED': '0',
                'MEMORY_WIKI_DOCUMENT_GRAPH_ENABLED': '0', 'MEMORY_WIKI_CODE_GRAPH_RERANK': '1',
                'MEMORY_WIKI_DOCUMENT_RERANK': '1', 'MEMORY_WIKI_DOCUMENT_ALLOW_CROSS_SCOPE': '0',
                'MEMORY_WIKI_DOCUMENT_ALLOW_SCOPE_MIGRATION': '0',
                'MEMORY_WIKI_DOCUMENT_ACCESS_SCOPE_ID': 'repo-own',
                'MEMORY_WIKI_DOCUMENT_ACCESS_REPOSITORY_ID': 'repo-own',
            }
            for key, value in settings.items():
                self._mp.setenv(key, value)
            for directory in ('local', 'roaming'):
                (self.home / directory).mkdir()
            # No .env/config.yaml writes. Fresh genuine importer==provider home
            # uses the supported no-file legacy route from this child-only ENV.
            native = sys.modules.get('hermes_constants')
            spi = sys.modules.get('agent.memory_provider')
            registry = sys.modules.get('tools.registry')
            trust = sys.modules.get('hermes_trust_core')
            require(all(x is not None for x in (native, spi, registry, trust)), 'genuine_SPI_registry_trust_not_loaded')
            self._native = native
            self._native_token = native.set_hermes_home_override(self.home)
            spec = importlib.util.spec_from_file_location(self._namespace, SOURCE / '__init__.py',
                                                         submodule_search_locations=[str(SOURCE)])
            self.m = importlib.util.module_from_spec(spec)
            sys.modules[self._namespace] = self.m
            spec.loader.exec_module(self.m)
            m = self.m
            require(m.MemoryProvider is spi.MemoryProvider and m.MemoryWikiProvider.__bases__ == (spi.MemoryProvider,),
                    'genuine_MemoryProvider_identity')
            require(m.tool_result is registry.tool_result and m.tool_error is registry.tool_error,
                    'genuine_registry_identity')
            require(m._INJECTION_GUARD_AVAILABLE and m._sanitize_recalled is trust.sanitize_recalled,
                    'genuine_trust_identity')
            require(Path(m._IMPORT_HERMES_HOME) == self.home, 'fresh_importer_home_required')
            doc = sys.modules[self._namespace + '.document_knowledge_graph']
            code = sys.modules[self._namespace + '.code_knowledge_graph']
            io_source = sys.modules[self._namespace + '.semantic_io']
            self.doc, self.code, self.io = doc, code, io_source
            require(m._semantic_request_bytes is io_source.request_bytes, 'actual_semantic_encoder_required')
            # Imported adapter не входит в pinned source-owned declaration slots.
            require(m._urlopen_no_redirect.__module__ == self._namespace + '.http_safety', 'genuine_imported_HTTP_seam')
            self._transport_before = m._urlopen_no_redirect
            m._urlopen_no_redirect = self.transport
            self.p = m.MemoryWikiProvider()
            self.p.initialize('session-own', hermes_home=str(self.home), bot_id=self.bot_id,
                              project_id='repo-own', agent_context='test')
            self.conn = self.p._connect()
            self.path = self.p.db_path
            require(self.conn is self.p._owned_conn and self.p._lifecycle_state == 'ready', 'actual_owned_ready_SQLite')
            require(self.path != Path(':memory:') and self.path.is_file(), 'file_backed_SQLite_required')
            self.conn.execute('PRAGMA temp_store=MEMORY')
            # Historical SOURCE carrier также задавал K=3 напрямую. Current ENV reader
            # clamp >=10: сохраняем authored low-K seam, не выдаём его за config proof.
            m.VECTOR_TOP_K = 3
            self.semantic_enabled = True
            self._scopes.enter_context(m._native_profile_scope(self.home))
            self._scopes.enter_context(m._profile_qdrant_scope(self.home))
            self._scopes.enter_context(doc._document_profile_scope(self.home))
            settings_now = m._rerank_settings()
            m._rerank_scope_state(settings_now)  # штатный cache setup до original read fence
            identity = self.p._runtime_identity()
            require(identity['profile_ready'] is True and not identity['missing_key_names'], 'owner_local_route_missing')
            require(identity['loaded_source_binding']['status'] == 'import_snapshot', 'source_owned_binding_drift')
            require(m.VECTOR_TOP_K == 3 and m.QDRANT_VECTOR_SIZE == 8 and m.EMBED_CACHE_MAX_ENTRIES == 0,
                    'actual_vector_and_cache_settings')
            self.gates = {k: settings_now[k] for k in (
                'RERANK_ENABLED', 'RERANK_ENDPOINT_VALID', 'RERANK_API_STYLE', 'RERANK_TOP_K',
                'RERANK_MIN_CANDIDATES', 'RERANK_CACHE_TTL', 'RERANK_DOCUMENT_MAX_CHARS',
                'RERANK_SKIP_EXACT_TECHNICAL', 'RERANK_RULES_ENABLED', 'RERANK_WEIGHT_TECHNICAL')}
            self.gates.update(profile_ready=identity['profile_ready'], missing_key_names=identity['missing_key_names'],
                              embedding_contract_valid=m.EMBED_CONTRACT_VALID, vector_K=m.VECTOR_TOP_K,
                              semantic_enabled=self.semantic_enabled)
            N, P = vars(m), m.MemoryWikiProvider
            self._targets = {
                unwrapped(P._search).__code__: 'search',
                unwrapped(P._search_fallback).__code__: 'fallback',
                unwrapped(P._rerank_rows).__code__: 'rerank',
                doc.query_documents.__code__: 'document_output',
                code.query_code_graph.__code__: 'code_output',
            }
            self._stage_code = m._stage_receipt.__code__
            self._fence_code = m._DisclosureFence.finish.__code__
            self._witness_code = self._witness.__func__.__code__
            self._prior_profile = sys.getprofile()
            sys.setprofile(self._observe)
            self._profiling = True
            self._witness()
            require(self._witness_seen == 2 and not self._observer_errors, 'passive_observer_not_alive')
            self._emit({'event': 'fixture_ready', 'schema': 'genuine_migrate',
                        'authored_SQL_not_ingestion': True, 'gates': self.gates,
                        'source_binding_status': identity['loaded_source_binding']['status']})
            return self
        except BaseException as primary:
            self._finish(primary)
            raise

    def _witness(self):
        return None

    def _ids(self, rows):
        output = []
        for row in list(rows or [])[:300]:
            if isinstance(row, dict) and isinstance(row.get('id'), str):
                value = row['id']
                # Только authored identities, никогда claim/query/headers.
                if len(value) <= 200 and re.fullmatch(r'[A-Za-z0-9_:./-]+', value):
                    output.append(value)
                else:
                    output.append('<unregistered-id>')
        return output

    def _emit(self, data):
        encoded = json.dumps(data, ensure_ascii=False, separators=(',', ':')) + '\n'
        size = len(encoded.encode('utf-8'))
        require(self._diag_bytes + size <= 96000, 'bounded_diagnostics_capacity')
        self._diag.write(encoded)
        self._diag.flush()  # durable carrier до следующего business assert
        self._diag_bytes += size

    def _observe(self, frame, event, arg):
        # Никаких injected exceptions/SQL/guards: observer только точных CodeType.
        try:
            c = frame.f_code
            if c is self._witness_code and event in ('call', 'return'):
                self._witness_seen += 1
                return
            if c is self._stage_code and event == 'call':
                local = frame.f_locals
                if len(self.stages) < 250:
                    self.stages.append({k: local[k] for k in ('stage', 'status', 'reason')
                                        if isinstance(local.get(k), str) and len(local[k]) <= 100})
                return
            if c is self._fence_code and event == 'return':
                fence = frame.f_locals.get('self')
                if getattr(fence, 'provider', None) is self.p:
                    self._emit({'event': 'original_disclosure_finish', 'accepted': arg is True})
                return
            tag = self._targets.get(c)
            if tag is None:
                return
            local = frame.f_locals
            if tag == 'rerank' and event == 'call' and local.get('self') is self.p:
                self.calls['rerank_body'] += 1
                cohort = self._ids(local.get('scored'))
                self.rerank_ids.append(cohort)
                self._emit({'event': 'exact_ranker_input', 'candidate_ids_order': cohort,
                            'calls': dict(self.calls), 'gates': self.gates})
            if event != 'return':
                return
            if tag == 'search':
                self.receipt = self.m._SEARCH_RECEIPT.get() or {}
            data = {'event': tag + '_return', 'calls': dict(self.calls),
                    'rank_input_ids_order': self.rerank_ids[-1] if self.rerank_ids else [],
                    'stage_reasons': self.stages[-12:]}
            if isinstance(arg, list):
                data['final_ids_order'] = self._ids(arg)
            elif isinstance(arg, dict):
                data['final_ids_order'] = self._ids(arg.get('results', []))
                data['retrieval'] = {k: v for k, v in arg.get('retrieval', {}).items()
                                     if isinstance(v, (bool, int, float)) or
                                     (isinstance(v, str) and len(v) < 100 and re.fullmatch(r'[A-Za-z0-9_:. -]*', v))}
                if arg.get('disclosure') == 'withheld':
                    data['disclosure'] = 'withheld'
            if tag in ('search', 'fallback'):
                for stage in ('embedding', 'qdrant', 'rerank'):
                    data[stage] = {k: self.receipt.get(stage, {}).get(k) for k in ('status', 'reason')}
                route = self.receipt.get('route', {})
                data['route_gates'] = {k: route.get(k) for k in ('profile_ready', 'contract_valid', 'reason', 'missing_key_names')}
            self._emit(data)
        except BaseException as exc:
            # Ошибка наблюдателя не управляет продуктом и не исчезает из verdict.
            if len(self._observer_errors) < 8:
                self._observer_errors.append(type(exc).__name__)

    def transport(self, request, timeout, *, _before_dispatch=None):
        """Authored streams под настоящими current HTTP/codec/admission helpers."""
        if _before_dispatch is not None:
            timeout = _before_dispatch()
        require(timeout > 0, 'positive_transport_timeout')
        url, method = request.full_url, request.get_method()
        body = json.loads(request.data) if request.data is not None else None
        m = self.m
        physical = m._physical_collection_name()
        if method == 'GET' and url == m.EMBED_URL + '/health':
            self.calls['health'] += 1
            payload = {'status': 'ok', 'algorithm': 'character-ngram-hashing',
                       'model': m.EMBED_MODEL, 'vector_size': m.QDRANT_VECTOR_SIZE}
        elif method == 'GET' and url == m._qdrant_url() + '/collections':
            self.calls['qdrant_metadata'] += 1
            payload = {'status': 'ok', 'result': {'collections': [{'name': physical}]}}
        elif method == 'GET' and url == m._qdrant_url() + '/collections/' + physical:
            self.calls['qdrant_metadata'] += 1
            payload = {'status': 'ok', 'result': {'config': {'params': {
                'vectors': {'size': m.QDRANT_VECTOR_SIZE, 'distance': 'Cosine'}}}}}
        elif method == 'POST' and url == m.EMBED_URL + '/embeddings':
            self.calls['embed'] += 1
            require(body.get('model') == 'hash-ngram-8' and body.get('dimensions') == 8,
                    'authored_embedding_request_contract')
            payload = {'data': [{'embedding': [0.1, 0.2] + [0.0] * 6}]}
        elif method == 'POST' and url == m._qdrant_url() + '/collections/' + physical + '/points/query':
            self.calls['vector'] += 1
            self.vector_filters.append(body['filter'])
            groups = [v['has_id'] for v in body['filter']['must'] if 'has_id' in v]
            require(len(groups) == 1, 'complete_SQLite_ID_filter_missing')
            point_ids = set(groups[0])
            ordered = sorted(((cid, score) for cid, score in self.vector_scores.items()
                              if m._qdrant_point_id(cid) in point_ids), key=lambda v: -v[1])[:body['limit']]
            self._emit({'event': 'authored_vector_attempt', 'eligible_ids': sorted(self.outbound_ids()),
                        'returned_ids_order': [cid for cid, _ in ordered], 'calls': dict(self.calls)})
            payload = {'status': 'ok', 'result': {'points': [
                {'id': m._qdrant_point_id(cid), 'payload': {'claim_id': cid}, 'score': score}
                for cid, score in ordered]}}
        elif method == 'POST' and url == 'https://synthetic.invalid/rank':
            self.calls['rank'] += 1
            self.rank_documents.append(tuple(body['documents']))
            self._emit({'event': 'authored_rank_attempt', 'candidate_ids_order': self.rerank_ids[-1]
                        if self.rerank_ids else [], 'calls': dict(self.calls), 'injected_timeout': self.rank_failure})
            require(body.get('model') == 'synthetic-no-model' and body.get('return_documents') is False,
                    'authored_rank_request_contract')
            if self.rank_claim_ids:
                require(bool(self.rerank_ids) and len(body['documents']) == len(self.rank_claim_ids)
                        and len(self.rerank_ids[-1]) == len(self.rank_claim_ids)
                        and set(self.rerank_ids[-1]) == set(self.rank_claim_ids),
                        'authored_claim_rank_cohort')
            else:
                require(all('codegraph:' in text or 'docgraph:' in text for text in body['documents']),
                        'inner_claim_rerank_spent')
            if self.rank_failure:
                raise TimeoutError('authored_rank_transport_failure')
            payload = {'results': [{'index': i, 'relevance_score': 1.0 - rank / 100}
                       for rank, i in enumerate(reversed(range(len(body['documents']))))]}
        else:
            self.calls['unexpected'] += 1
            self._emit({'event': 'unregistered_transport_refused', 'calls': dict(self.calls)})
            raise RuntimeError('authored_transport_does_not_admit_other_requests')
        stream = Stream(payload)
        self.streams.append(stream)
        return stream

    def claim(self, cid, *, topic='document-intelligence', text=QUERY+' '+SAFE, visibility='global',
              salience=0.2, vector=0.2, **changes):
        # Synthetic SQL seed, не успешный ingest/parser/provider ответ.
        row = {'id': cid, 'hash': hashlib.sha256(cid.encode()).hexdigest(), 'claim': text,
               'normalized_claim': text, 'topic': topic, 'evidence': '', 'source': 'authored-'+cid,
               'scope': 'global', 'status': 'active', 'risk': 'low', 'quarantined_at': 0,
               'trust_class': 'fact', 'type': 'fact', 'quality': 0.8, 'pinned': 0,
               'visibility_scope': visibility, 'origin_bot_id': self.bot_id,
               'origin_session_id': 'session-own', 'origin_chat_hash': self.p._chat_hash(),
               'project_id': 'repo-own', 'confidence': 0.8, 'salience': salience,
               'freshness_at': self.m.now(), 'updated_at': self.m.now(), 'created_at': self.m.now(),
               'trust_score': 0.8, 'usefulness': 0.5}
        row.update(changes)
        self.conn.execute('INSERT INTO claims('+','.join(row)+') VALUES('+','.join('?' for _ in row)+')', list(row.values()))
        search = self.m.claim_search_text(text, text, topic, '')
        self.conn.execute('INSERT INTO claims_fts(id,claim,normalized,topic,evidence,search_text) VALUES(?,?,?,?,?,?)',
                          (cid, '', '', '', '', search))
        self.vector_scores[cid] = vector

    def document(self, source, cid, *, scope='repo-own', repo='repo-own', extension='.md',
                 active=1, chunk_active=1, text=SAFE, revision=None, stale_fts=False):
        revision = revision or 'rev-'+source
        path = self.home / 'cache' / 'documents' / (source+extension)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text(text, encoding='utf-8')
        digest = hashlib.sha256(text.encode()).hexdigest()
        self.conn.execute('INSERT OR IGNORE INTO document_sources(source_id,scope_id,repository_id,source_path,extension,revision_id,active,title,display_name,file_hash,parser,parser_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                          (source, scope, repo, str(path), extension, 'current-'+source, active,
                           'Source '+source, source, digest, 'authored-SQL-not-parser', 'fixture-v1'))
        for rid in (revision, 'current-'+source):
            self.conn.execute('INSERT OR IGNORE INTO document_revisions(revision_id,source_id,file_hash) VALUES(?,?,?)',
                              (rid, source, digest))
        chunk, unit = 'chunk-'+cid, 'unit-'+cid
        self.conn.execute('INSERT INTO document_units(unit_id,source_id,revision_id,anchor,unit_text,title,active) VALUES(?,?,?,?,?,?,?)',
                          (unit, source, revision, unit, text, 'Title '+cid, chunk_active))
        self.conn.execute('INSERT INTO document_chunks(chunk_id,source_id,revision_id,scope_id,repository_id,embedding_claim_id,chunk_text,embedding_text,title,active) VALUES(?,?,?,?,?,?,?,?,?,?)',
                          (chunk, source, revision, scope, repo, cid, text, text, 'Title '+cid, chunk_active))
        if chunk_active or stale_fts:
            self.conn.execute('INSERT INTO document_units_fts(source_id,unit_id,unit_type,title,anchor,unit_text) VALUES(?,?,?,?,?,?)',
                              (source, unit, 'text', 'Title '+cid, unit, text))
            self.conn.execute('INSERT INTO document_chunks_fts(source_id,chunk_id,title,anchors,chunk_text) VALUES(?,?,?,?,?)',
                              (source, chunk, 'Title '+cid, unit, text))
        return chunk

    def connectors(self, rows):
        # Полная current schema; old минимальная external_sources не используется.
        for source, owner, status in rows:
            scope, repo = self.conn.execute('SELECT scope_id,repository_id FROM document_sources WHERE source_id=?', (source,)).fetchone()
            key = 'authored-' + hashlib.sha256((source+'|'+owner+'|'+status).encode()).hexdigest()
            self.conn.execute('INSERT INTO external_sources(source_key,owner_bot_id,source_type,display_uri,scope_id,repository_id,document_source_id,revision_key,content_hash,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                              (key, owner, 'record', 'urn:ri-r03:'+source, scope, repo, source, 'authored-v1',
                               hashlib.sha256(source.encode()).hexdigest(), status, 1, 1))

    def code_chunk(self, repo, cid, *, text=SAFE):
        self.conn.execute('INSERT OR IGNORE INTO code_graph_repositories(repository_id) VALUES(?)', (repo,))
        # Current disclosure требует настоящую связанную file metadata row.
        self.conn.execute('INSERT OR IGNORE INTO code_graph_files(repository_id,file_path,file_hash) VALUES(?,?,?)',
                          (repo, 'source.py', hashlib.sha256(text.encode()).hexdigest()))
        chunk = 'code-'+cid
        self.conn.execute('INSERT INTO code_graph_chunks(repository_id,chunk_id,file_path,embedding_claim_id,chunk_text,embedding_text,search_text) VALUES(?,?,?,?,?,?,?)',
                          (repo, chunk, 'source.py', cid, text, text, text))
        self.conn.execute('INSERT INTO code_graph_chunks_fts(repository_id,chunk_id,file_path,symbol_id,qualified_name,search_text) VALUES(?,?,?,?,?,?)',
                          (repo, chunk, 'source.py', '', '', text))
        return chunk

    def ready(self):
        self.conn.commit()
        require(not self.conn.in_transaction, 'seed_transaction_not_committed')
        require(self.conn.execute('PRAGMA quick_check').fetchone()[0] == 'ok', 'fixture_SQLite_integrity')
        require(not self.conn.execute('PRAGMA foreign_key_check').fetchall(), 'fixture_foreign_keys')
        self._emit({'event': 'seed_ready', 'authored_claim_ids': list(self.vector_scores), 'calls': dict(self.calls)})

    def search(self, **kwargs):
        return self.p._search(QUERY, limit=50, conn=self.conn, record_retrieval=False, apply_rerank=False, **kwargs)

    def outbound_ids(self):
        point_to_claim = {self.m._qdrant_point_id(cid): cid for cid in self.vector_scores}
        require(bool(self.vector_filters), 'no_authored_vector_request')
        return {point_to_claim[v] for item in self.vector_filters[-1]['must'] if 'has_id' in item for v in item['has_id']}

    def __exit__(self, exc_type, primary, tb):
        self._finish(primary)
        return False

    def _finish(self, primary):
        original = primary
        errors = []
        def attempt(action):
            nonlocal primary
            try:
                action()
            except BaseException as exc:
                errors.append(type(exc).__name__)
                if primary is None:
                    primary = exc
                elif exc is not primary:
                    primary.add_note('RI_R03_fixture_cleanup:' + type(exc).__name__)
        if self._profiling:
            attempt(lambda: sys.setprofile(self._prior_profile))
            self._profiling = False
        if self._diag is not None:
            attempt(lambda: self._emit({'event': 'before_fixture_shutdown',
                'primary_type': type(original).__name__ if original else None,
                'calls': dict(self.calls), 'observer_errors': self._observer_errors}))
        def shutdown():
            if self.p is None:
                return
            # Штатный close; UNKNOWN/owner никогда не сбрасывается и не force-close.
            self.m.SEMANTIC_ENABLED = False
            if self.conn is not None:
                self.conn.execute('PRAGMA query_only=OFF')
            self.p.shutdown()
            require(self.p._conn is None and self.p._owned_conn is None
                    and not self.p._graph_reader_connections, 'provider_owners_not_closed')
            if self.conn is not None:
                try:
                    self.conn.execute('SELECT 1')
                except sqlite3.ProgrammingError:
                    pass
                else:
                    raise RuntimeError('RI_R03_PREREQUISITE:fixture_connection_still_queryable')
        attempt(shutdown)
        attempt(lambda: require(all(stream.closed for stream in self.streams), 'authored_stream_not_closed'))
        attempt(lambda: require(not self._observer_errors and self.calls['unexpected'] == 0,
                                'observer_or_transport_refusal'))
        if self._diag is not None:
            attempt(lambda: self._emit({'event': 'fixture_shutdown', 'owners_closed': self.p is None or
                (self.p._conn is None and self.p._owned_conn is None), 'cleanup_error_types': list(errors)}))
            attempt(self._diag.close)
        attempt(self._scopes.close)
        if self._native_token is not None:
            attempt(lambda: self._native.reset_hermes_home_override(self._native_token))
        if self.m is not None and hasattr(self, '_transport_before'):
            self.m._urlopen_no_redirect = self._transport_before
        sys.modules['__main__']._memory_wiki_instance = self._main_before
        for loaded in tuple(sys.modules):
            if loaded == self._namespace or loaded.startswith(self._namespace + '.'):
                sys.modules.pop(loaded, None)
        attempt(self._mp.undo)
        self.conn = None
        if errors:
            raise primary


def ids(rows):
    return [r['id'] for r in rows]
