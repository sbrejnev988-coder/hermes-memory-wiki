"""ONE SOURCE terminal packet; reuse the existing closure/owned SQLite fixture.

Actual handler, scoped wrapper, guard, sharing SQL, ledger, recorder, ACK,
transaction and metrics bodies. Only host spill/remote rank and expressly
synthetic late callbacks are seams. No SDK stand-in, package boot or model I/O.
"""
from __future__ import annotations
import __future__, ast, contextvars, hashlib, hmac, ipaddress, json, math, os, re, shutil, sqlite3, stat, sys, threading, time, traceback, types, uuid
import functools, inspect, marshal, html, unicodedata, urllib.error, urllib.parse, urllib.request
from pathlib import Path
from collections import defaultdict, deque, OrderedDict
from contextlib import contextmanager, nullcontext, ExitStack
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
ROOT=Path(DEVTOOLS_SCRATCH); INPUTS=DEVTOOLS_INPUTS
os.environ.update(HERMES_SECURITY_STRICT='0', MEMORY_WIKI_STRICT_RECALL='1',
    MEMORY_WIKI_SEMANTIC='0', MEMORY_WIKI_RERANK_ENABLED='0',
    MEMORY_WIKI_EPISODIC_ENABLED='0', MEMORY_WIKI_EPISODIC_PREFETCH='0',
    MEMORY_WIKI_CODE_GRAPH_PREFETCH='0', MEMORY_WIKI_DOCUMENT_PREFETCH='0',
    MEMORY_WIKI_ALLOW_SHARED_SECRET_METADATA='0', MEMORY_WIKI_ENABLE_LEGACY_SECRET_INDEX='0',
    MEMORY_WIKI_ONLINE_METRICS_ENABLED='1', MEMORY_WIKI_LLM_PACK='0',
    MEMORY_WIKI_INCLUDE_SESSIONS_IN_PACK='0')
RAW=devtools_read_bound(INPUTS['__init__.py']); TREE=ast.parse(RAW)
CLASS=next(n for n in TREE.body if isinstance(n,ast.ClassDef) and n.name=='MemoryWikiProvider')
previous=ast.parse(devtools_read_bound(INPUTS['cases_disclosure.py']))
selector=next(n for n in previous.body if isinstance(n,ast.FunctionDef) and n.name=='closure')
exec(compile(ast.Module(body=[selector],type_ignores=[]),INPUTS['cases_disclosure.py'],'exec',flags=__future__.annotations.compiler_flag,dont_inherit=True))
old_fixture=ast.parse(devtools_read_bound(INPUTS['cases_shared_closed.py']))

def source_module(name,file):
    module=types.ModuleType(name);module.__file__=INPUTS[file];sys.modules[name]=module
    exec(compile(devtools_read_bound(module.__file__),module.__file__,'exec',dont_inherit=True),module.__dict__)
    return module
shared=source_module('shared_blocks','shared_blocks.py')
privacy=source_module('privacy_erasure','privacy_erasure.py')
guard=source_module('guard','guard.py')
fencing=source_module('disclosure_fence','disclosure_fence.py')
semantic=source_module('semantic_io','semantic_io.py')
events=source_module('memory_events','memory_events.py')
planner=source_module('recall_planner','recall_planner.py')
episodes=source_module('episodic_memory','episodic_memory.py')
observations=source_module('memory_observations','memory_observations.py')
code=source_module('code_knowledge_graph','code_knowledge_graph.py')
extract=source_module('document_extractors','document_extractors.py')
documents=source_module('document_knowledge_graph','document_knowledge_graph.py')
metrics=source_module('online_metrics','online_metrics.py')
recall=source_module('recall_orchestrator','recall_orchestrator.py')

M={
 '_runtime_identity','_disclosure_context','_disclosure_ledger_type','_disclosure_normalize','_disclosure_document_access','_disclosure_code_repository',
 '_claim_visibility_sql','_claim_metadata_eligibility_sql','_claim_visible','_chat_hash','_scoped_backup_owner','_contradiction_visible',
 '_consumer_identity','_register_consumer','_last_seen_revision','_mark_seen_revision','_revision_delta','_select_recall_rows',
 '_sanitize_row','_redact_code_graph_text','_search','_search_fallback','_claim_id_restriction_sql','_hydrate_semantic_candidates','_apply_diversity',
 '_model_safe_row','_model_safe_claim_rows','_inspect_recall_text','_inspect_recall_item','_is_stale','_escape_like',
 '_record_recall_rows','_record_prefetch_rows','_record_recall_feedback','_require_visible_claim',
 '_memory_cache_state_contract','_cache_component_partition','_cache_component_revision','_meta_text','_meta_int',
 'prefetch','_prefetch_impl','_commit_prefetch_delivery','_lexical_prefetch_fallback','_prefetch_row_relevant','_format_claim_time',
 '_shared_prefetch_fragments','_shared_block_secret_scan','_prefetch_delivery_budget','_finish_prefetch_diagnostics',
 '_connect','_recall_plan','_env_metadata_context','_env_files','_parse_env_metadata','_secret_context','_query_secrets','_get_secret_store','_cols','_topic_alias',
 '_top_evidence','_related_contradictions','_audit','_claim_transaction','_require_claim_writer',
 '_quarantine_claim_connection','_rollback_claim_transaction','_claim_journal_pending_commit','_claim_journal_committed',
 '_claim_journal_state','_claim_mutation_columns',
 'handle_tool_call','_enforce_write_namespace','_should_journal_tool','_nonmutating_journal_tools','_pack_context','_pack_selected_claims','_llm_pack_context',
 '_memory_diff','_graph_query','_graph_row_visible','_preference_layer','_owned_aux_row_visible','_preference_rule_is_trusted',
}
methods=[n for n in CLASS.body if isinstance(n,ast.FunctionDef) and n.name in M]
assert {n.name for n in methods}==M
N=dict(globals(),__name__='terminal_source_component',__file__=INPUTS['__init__.py'],
       _REQUEST_HOME=contextvars.ContextVar('source_owner',default=None),
       _QDRANT_PROFILE_SCOPE=contextvars.ContextVar('source_config',default=None),
       _SEARCH_RECEIPT=contextvars.ContextVar('source_search',default=None),
       _RECALL_REQUEST=contextvars.ContextVar('source_request',default=None),
       _CLAIM_JOURNAL_CAPTURE=contextvars.ContextVar('source_journal',default=None),
       _IMPORT_HERMES_HOME=ROOT,_LOADED_CODE_IDENTITY='SOURCE-not-native',
       _DisclosureFence=fencing.DisclosureFence,_TerminalDelivery=fencing.TerminalDelivery,
       _DELIVERY=fencing.DELIVERY,_current_delivery=fencing.current_delivery,
       _withheld_payload=fencing.withheld_payload,_DeliveryWithheld=fencing.DeliveryWithheld,
       _privacy_erasure=privacy,_episodic_memory=episodes,_memory_events=events,
       _memory_observations=observations,_recall_orchestrator=recall,
       _semantic_request_bytes=semantic.request_bytes,_SemanticIOError=semantic.SemanticIOError,
       _INJECTION_GUARD_AVAILABLE=False,_sanitize_recalled=None,_SECRET_CORE_AVAILABLE=False,
       _SECRET_CORE_ERROR='SOURCE_native_Core_not_loaded_not_installation_diagnosis',
       sanitize_context_text=guard.sanitize_context_text,is_social_close=guard.is_social_close,
       _render_attached_shared_blocks=shared.render_attached,_online_metrics=metrics,
       _maybe_prefetch_code_context=code.maybe_prefetch_code_context,
       _maybe_prefetch_document_context=documents.maybe_prefetch_document_context,
       _document_profile_scope=documents._document_profile_scope,
       _owns_private_graph_writer=code._owns_graph_writer,
       _disclosure_assert_source_access=documents._assert_source_access,
       _EMBED_PROFILE_STATES={},_RERANK_DEFAULT_STATE={},_RERANK_PROFILE_STATES={},
       _OPENROUTER_HEALTH_CACHE={},_OPENROUTER_HEALTH_BY_PROFILE={},
       _set_native_home=None,_reset_native_home=None,
       EMBED_API_KEY='',RERANK_API_KEY='',QDRANT_API_KEY='',SEMANTIC_ENABLED=False,_FAULT_INJECT_STALE=False)
# Genuine published no-native fallback bodies, not fabricated tool-result SDK.
fallbacks=[n for block in TREE.body if isinstance(block,ast.Try) for handler in block.handlers for n in handler.body
           if isinstance(n,ast.FunctionDef) and n.name in {'_native_home','tool_result','tool_error'}]
assert {n.name for n in fallbacks}=={'_native_home','tool_result','tool_error'} and len(fallbacks)==3
closure(ast.Module(body=fallbacks,type_ignores=[]),[n.name for n in fallbacks],N)
SEEDS=['now','sha','short','slug','normalize_claim','tokens','claim_search_text','scrub_memory_artifacts',
       'redact_secrets','_profile_configuration_generation','_profile_secret_setting','_bound_profile_home',
       '_embed_api_key','_rerank_api_key','_qdrant_api_key','_stage_receipt','_freeze_recall_receipt','_new_recall_request',
       '_rrf_fusion','score_breakdown','safe_fts_query','_context_data','_env_int','secret_scan',
       '_qdrant_admit_filter','_qdrant_visibility_filter','_qdrant_point_id',
       '_semantic_profile_ready','_qdrant_url','_qdrant_collection','_qdrant_alias','_validated_http_endpoint','_embedding_manifest','_manifest_hash',
       '_bind_memory_wiki_profile_methods']
SELECTED=closure(TREE,SEEDS,N,methods=methods)
P=N['MemoryWikiProvider'];assert P.__bases__==(object,)
# Bind exactly the real scoped wrapper. Its full receipt stages execute in cases.
N['_bind_memory_wiki_profile_methods']()
runtime=types.ModuleType(N['__name__']);runtime.__dict__.update(N);sys.modules[N['__name__']]=runtime
assert not any(k.startswith(('hermes','tools.')) for k in sys.modules)

# Reuse existing fixture selector/DDL/connection-close bodies verbatim.
def old_node(name):
    values=[n for n in old_fixture.body if isinstance(n,(ast.FunctionDef,ast.ClassDef)) and n.name==name]
    assert len(values)==1
    return values[0]
exec(compile(ast.Module(body=[old_node('ddl')],type_ignores=[]),INPUTS['cases_shared_closed.py'],'exec',flags=__future__.annotations.compiler_flag,dont_inherit=True))
column_loops=[n for n in ast.walk(CLASS) if isinstance(n,ast.For) and isinstance(n.target,ast.Tuple)
              and [t.id for t in n.target.elts if isinstance(t,ast.Name)]==['col','typ','default']
              and isinstance(n.iter,ast.List) and any(isinstance(v,ast.Tuple) and isinstance(v.elts[0],ast.Constant)
                  and v.elts[0].value=='expires_at' for v in n.iter.elts)]
assert len(column_loops)==1
COLUMNS=ast.literal_eval(column_loops[0].iter)
DDL=[ddl('CREATE TABLE IF NOT EXISTS '+name+'(') for name in ('claims','meta','memory_consumers','evidence','contradictions','recall_events','recall_feedback','audit_log')]
EXTRA_DDL=[ddl('CREATE TABLE IF NOT EXISTS '+name+'(') for name in ('entities','relations','project_profiles','preference_rules','topic_aliases')]
TRIGGERS=[ddl('CREATE TRIGGER '+name) for name in ('trg_claims_revision_insert','trg_claims_revision_update','trg_claims_revision_delete')]
FTS=ddl('CREATE VIRTUAL TABLE IF NOT EXISTS claims_fts ')
SAFE='Atlas notes preserve durable project decisions with concise source explanations.'
RESULTS=[];DETAILS=[];PEAK=0;CLOSED=0;EXTERNAL_CLOSED=0;CONNECTIONS_CLOSED=0

def sample():
    global PEAK
    files=[p for p in ROOT.rglob('*') if p.is_file()]
    size=sum(p.stat().st_size for p in files)
    size+=max([p.stat().st_size for p in files if p.suffix=='.sqlite3'] or [0])+16000
    PEAK=max(PEAK,size);assert size<=650000,'fixture_budget_exceeded'
exec(compile(ast.Module(body=[old_node('no_links'),old_node('PendingIntent'),old_node('Fixture')],type_ignores=[]),INPUTS['cases_shared_closed.py'],'exec',flags=__future__.annotations.compiler_flag,dont_inherit=True))
PreviousFixture=Fixture

class Fixture(PreviousFixture):
    def __init__(self,name):
        super().__init__(name)
        N['_RECALL_REQUEST'].set(None) # public wrapper owns the real request
        self.p._claim_tx_connection=self.creator._claim_tx_connection=None
        self.p._claim_tx_thread=self.creator._claim_tx_thread=None
        for statement in EXTRA_DDL:self.conn.execute(statement)
        metrics.install_schema(self.conn);self.conn.commit()

        self.p.origin_chat_hash=self.p._chat_hash(self.p.session_id)
        self.creator.origin_chat_hash=self.creator._chat_hash(self.creator.session_id)
        self.delivery_observations=[];self.callbacks=[];self.arm=None
        actual_tx=self.p._claim_transaction
        def observe_tx(conn=None,**kw):
            if kw.get('_terminal') is not None:
                self.delivery_observations.append(kw['_terminal'])
            return actual_tx(conn,**kw)
        self.p._claim_transaction=observe_tx
        actual=self.p._claim_journal_pending_commit
        def pending(conn):
            delivery=fencing.current_delivery(self.p)
            if delivery is not None:
                self.callbacks.append(('journal_prepare',conn.in_transaction))
                if self.arm:
                    callback=self.arm;self.arm=None;callback()
            result=actual(conn)
            return result
        self.p._claim_journal_pending_commit=pending
    def row(self,cid):return dict(self.conn.execute('SELECT * FROM claims WHERE id=?',(cid,)).fetchone())
    def query(self):return json.loads(self.p.handle_tool_call('memory_wiki_query',{'query':'atlas documentation','limit':10}))
    def unified(self):return json.loads(self.p.handle_tool_call('memory_wiki_recall',{'query':'atlas documentation','mode':'fast','limit':10}))
    def pack(self):return json.loads(self.p.handle_tool_call('memory_wiki_pack_context',{'query':'atlas documentation','max_chars':12000,'output_mode':'debug'}))
    def owned(self,cid='c_owned'):
        self.add(cid,owner=self.p);return cid
    def force_fallback(self):
        actual=self.p._env_metadata_context
        def fail(query):
            actual(query)
            raise RuntimeError('synthetic_pre_return_runtime_failure')
        self.p._env_metadata_context=fail
    def neutral(self,cid,count=1):
        row=self.row(cid);assert row['recall_count']==row['access_count']==count
        events_rows=self.conn.execute('SELECT * FROM recall_events WHERE claim_id=?',(cid,)).fetchall()
        feedback=self.conn.execute('SELECT * FROM recall_feedback WHERE claim_id=?',(cid,)).fetchall()
        assert len(events_rows)==len(feedback)==count
        assert all(r['used']==-1 and r['outcome']=='pending' for r in events_rows)
        assert all(r['retrieved']==1 and r['used']==0 and r['helpful']==0 and r['outcome']=='neutral' for r in feedback)
        assert {r['id'] for r in events_rows}=={r['recall_event_id'] for r in feedback}
        assert row['last_recalled']>0 and row['usefulness']==.5
    def no_accounting(self):
        assert self.counts()==(0,0)
        assert self.conn.execute('SELECT count(*) FROM memory_consumers').fetchone()[0]==0
        assert self.conn.execute('SELECT count(*) FROM memory_online_metrics').fetchone()[0]==0
    def clean(self,payload):
        encoded=json.dumps(payload)
        assert not any(cid in encoded for cid in self.ids)
        assert not any(bid in encoded for bid in self.bids)
        if isinstance(payload,dict):
            assert not payload.get('claims') and not payload.get('items') and not payload.get('context')
            assert not payload.get('results') and not payload.get('structured_pack') and not payload.get('sources')
            assert not payload.get('plan') and not payload.get('intent_plan')
            for k in ('evidence_count','chars_used','used_chars','chunk_count','memory_revision_watermark'):
                assert not payload.get(k)
            receipt=payload.get('retrieval_receipt')
            if receipt:assert receipt['final']['emitted_claim_count']==0 and not receipt['searches']
        else:assert payload==''
        self.no_accounting()
    def close(self,cleanup):
        global CONNECTIONS_CLOSED
        for delivery in self.delivery_observations:
            self.callbacks.append(('terminal',delivery.phase,delivery.reason,delivery.measurement))
        self.delivery_observations=[]
        super().close(cleanup)
        try:self.conn.execute('SELECT 1')
        except sqlite3.ProgrammingError:CONNECTIONS_CLOSED+=1
        else:raise AssertionError('owned_connection_not_closed')
        for conn in self.extra:
            try:conn.execute('SELECT 1')
            except sqlite3.ProgrammingError:CONNECTIONS_CLOSED+=1
            else:raise AssertionError('exact_extra_connection_not_closed')
        assert not any(t.name=='memory-wiki-bounded-prefetch' and t.is_alive() for t in threading.enumerate())
