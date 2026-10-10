"""One SOURCE8 sharing group. Actual sharing SQL/render/ACL/MAC/guards.

Reuse the previous closure selector verbatim, not a new loader. Projected class
has no SDK base/constructor. Only host spill budget and remote rank order are
fixture seams; mutation callbacks run AFTER the actual guard decision. Optional
code/document/episode/secret enrichments are disabled by their real settings.
"""
from __future__ import annotations
import __future__, ast, contextvars, hashlib, hmac, ipaddress, json, math, os, re, shutil, sqlite3, stat, sys, threading, time, traceback, types, uuid
import html, unicodedata, urllib.error, urllib.parse
from pathlib import Path
from collections import defaultdict, deque, OrderedDict
from contextlib import contextmanager, nullcontext, ExitStack
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
ROOT=Path(DEVTOOLS_SCRATCH)
INPUTS=DEVTOOLS_INPUTS
os.environ.update(HERMES_SECURITY_STRICT='0', MEMORY_WIKI_STRICT_RECALL='1',
    MEMORY_WIKI_SEMANTIC='0', MEMORY_WIKI_RERANK_ENABLED='0',
    MEMORY_WIKI_EPISODIC_ENABLED='0', MEMORY_WIKI_EPISODIC_PREFETCH='0',
    MEMORY_WIKI_CODE_GRAPH_PREFETCH='0', MEMORY_WIKI_DOCUMENT_PREFETCH='0',
    MEMORY_WIKI_ALLOW_SHARED_SECRET_METADATA='0', MEMORY_WIKI_ENABLE_LEGACY_SECRET_INDEX='0',
    MEMORY_WIKI_ONLINE_METRICS_ENABLED='0')
RAW=devtools_read_bound(INPUTS['__init__.py']);TREE=ast.parse(RAW)
CLASS=next(n for n in TREE.body if isinstance(n,ast.ClassDef) and n.name=='MemoryWikiProvider')
previous=ast.parse(devtools_read_bound(INPUTS['cases_disclosure.py']))
selector=next(n for n in previous.body if isinstance(n,ast.FunctionDef) and n.name=='closure')
exec(compile(ast.Module(body=[selector],type_ignores=[]),INPUTS['cases_disclosure.py'],'exec',flags=__future__.annotations.compiler_flag,dont_inherit=True))

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
code=source_module('code_knowledge_graph','code_knowledge_graph.py')
extract=source_module('document_extractors','document_extractors.py')
documents=source_module('document_knowledge_graph','document_knowledge_graph.py')
metrics=source_module('online_metrics','online_metrics.py')

M={
 '_runtime_identity','_disclosure_context','_disclosure_ledger_type','_disclosure_normalize',
 '_claim_visibility_sql','_claim_metadata_eligibility_sql','_claim_visible','_chat_hash','_scoped_backup_owner',
 '_consumer_identity','_register_consumer','_last_seen_revision','_mark_seen_revision','_revision_delta','_select_recall_rows',
 '_sanitize_row','_redact_code_graph_text','_search','_search_fallback','_claim_id_restriction_sql','_hydrate_semantic_candidates','_apply_diversity',
 '_model_safe_row','_model_safe_claim_rows','_inspect_recall_text','_inspect_recall_item','_is_stale','_escape_like',
 '_record_recall_rows','_record_prefetch_rows','_record_recall_feedback','_require_visible_claim',
 '_memory_cache_state_contract','_cache_component_partition','_cache_component_revision','_meta_text','_meta_int',
 'prefetch','_prefetch_impl','_commit_prefetch_delivery','_lexical_prefetch_fallback','_prefetch_row_relevant','_format_claim_time',
 '_shared_prefetch_fragments','_shared_block_secret_scan','_prefetch_delivery_budget','_finish_prefetch_diagnostics',
 '_connect','_recall_plan','_env_metadata_context','_secret_context','_query_secrets','_cols','_topic_alias',
 '_top_evidence','_related_contradictions','_audit','_claim_transaction','_require_claim_writer',
 '_quarantine_claim_connection','_rollback_claim_transaction','_claim_journal_pending_commit','_claim_journal_committed',
}
methods=[n for n in CLASS.body if isinstance(n,ast.FunctionDef) and n.name in M]
assert {n.name for n in methods}==M
N=dict(globals(),__name__='shared_social_source_component',__file__=INPUTS['__init__.py'],
       _REQUEST_HOME=contextvars.ContextVar('source_owner',default=None),
       _QDRANT_PROFILE_SCOPE=contextvars.ContextVar('source_config',default=None),
       _SEARCH_RECEIPT=contextvars.ContextVar('source_search',default=None),
       _RECALL_REQUEST=contextvars.ContextVar('source_request',default=None),
       _CLAIM_JOURNAL_CAPTURE=contextvars.ContextVar('source_journal',default=None),
       _IMPORT_HERMES_HOME=ROOT,_LOADED_CODE_IDENTITY='SOURCE-not-native',
       _DisclosureFence=fencing.DisclosureFence,_privacy_erasure=privacy,_episodic_memory=episodes,
       _semantic_request_bytes=semantic.request_bytes,_SemanticIOError=semantic.SemanticIOError,
       _INJECTION_GUARD_AVAILABLE=False,_sanitize_recalled=None,_SECRET_CORE_AVAILABLE=False,
       sanitize_context_text=guard.sanitize_context_text,is_social_close=guard.is_social_close,
       _render_attached_shared_blocks=shared.render_attached,_online_metrics=metrics,
       _maybe_prefetch_code_context=code.maybe_prefetch_code_context,
       _maybe_prefetch_document_context=documents.maybe_prefetch_document_context,
       _owns_private_graph_writer=code._owns_graph_writer,
       _EMBED_PROFILE_STATES={},_RERANK_DEFAULT_STATE={},_RERANK_PROFILE_STATES={},
       _OPENROUTER_HEALTH_CACHE={},_OPENROUTER_HEALTH_BY_PROFILE={},
       EMBED_API_KEY='',RERANK_API_KEY='',QDRANT_API_KEY='',SEMANTIC_ENABLED=False,_FAULT_INJECT_STALE=False)
source_home=[n for block in TREE.body if isinstance(block,ast.Try) for handler in block.handlers for n in handler.body
             if isinstance(n,ast.FunctionDef) and n.name=='_native_home']
assert len(source_home)==1
closure(ast.Module(body=source_home,type_ignores=[]),['_native_home'],N)
SEEDS=['now','sha','short','slug','normalize_claim','tokens','claim_search_text','scrub_memory_artifacts',
       'redact_secrets','_profile_configuration_generation','_profile_secret_setting','_bound_profile_home',
       '_embed_api_key','_rerank_api_key','_qdrant_api_key','_stage_receipt','_freeze_recall_receipt','_new_recall_request',
       '_rrf_fusion','score_breakdown','safe_fts_query','_context_data','_env_int','secret_scan',
       '_qdrant_admit_filter','_qdrant_visibility_filter','_qdrant_point_id',
       '_semantic_profile_ready','_qdrant_url','_qdrant_collection','_qdrant_alias','_validated_http_endpoint','_embedding_manifest','_manifest_hash']
SELECTED=closure(TREE,SEEDS,N,methods=methods)
P=N['MemoryWikiProvider'];assert P.__bases__==(object,)
assert not any(k.startswith(('hermes','tools.')) for k in sys.modules)

# Unmodified existing claims/schema/columns/revision triggers, no migration.
def ddl(prefix):
    values=[n.args[0].value for n in ast.walk(CLASS) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)
            and n.func.attr=='execute' and n.args and isinstance(n.args[0],ast.Constant)
            and isinstance(n.args[0].value,str) and n.args[0].value.startswith(prefix)]
    assert len(values)==1,'schema_selector_not_unique:'+prefix
    return values[0]
column_loops=[n for n in ast.walk(CLASS) if isinstance(n,ast.For) and isinstance(n.target,ast.Tuple)
              and [t.id for t in n.target.elts if isinstance(t,ast.Name)]==['col','typ','default']
              and isinstance(n.iter,ast.List) and any(isinstance(v,ast.Tuple) and isinstance(v.elts[0],ast.Constant)
                  and v.elts[0].value=='expires_at' for v in n.iter.elts)]
assert len(column_loops)==1
COLUMNS=ast.literal_eval(column_loops[0].iter)
DDL=[ddl('CREATE TABLE IF NOT EXISTS '+name+'(') for name in ('claims','meta','memory_consumers','evidence','contradictions','recall_events','recall_feedback','audit_log')]
TRIGGERS=[ddl('CREATE TRIGGER '+name) for name in ('trg_claims_revision_insert','trg_claims_revision_update','trg_claims_revision_delete')]
FTS=ddl('CREATE VIRTUAL TABLE IF NOT EXISTS claims_fts ')
SAFE='Atlas notes preserve durable project decisions with concise source explanations.'
RESULTS=[];DETAILS=[];PEAK=0;CLOSED=0;EXTERNAL_CLOSED=0

def sample():
    global PEAK
    files=[p for p in ROOT.rglob('*') if p.is_file()]
    size=sum(p.stat().st_size for p in files)
    # One sequential DELETE-mode writer, no WAL or parallel fixtures. Reserve
    # a full DB before-image plus page/header overhead for transient journals.
    size+=max([p.stat().st_size for p in files if p.suffix=='.sqlite3'] or [0])+16000
    PEAK=max(PEAK,size)
    assert size<=400000,'fixture_budget_exceeded'

def no_links(root):
    for p in (root,*root.parents,*root.rglob('*')):
        s=p.lstat();assert not stat.S_ISLNK(s.st_mode) and not getattr(s,'st_file_attributes',0)&1024

class PendingIntent(Exception):pass

class Fixture:
    def __init__(self,name):
        self.dir=ROOT/name;self.home=self.dir/'home';self.root=self.home/'memory-wiki';self.root.mkdir(parents=True)
        self.path=self.root/'memory_wiki.sqlite3';self.conn=sqlite3.connect(str(self.path),check_same_thread=False)
        self.conn.row_factory=sqlite3.Row;self.conn.execute('PRAGMA journal_mode=DELETE');self.conn.execute('PRAGMA foreign_keys=ON')
        for s in DDL:self.conn.execute(s)
        present={r[1] for r in self.conn.execute('PRAGMA table_info(claims)')}
        for col,typ,default in COLUMNS:
            if col not in present:self.conn.execute(f'ALTER TABLE claims ADD COLUMN {col} {typ} NOT NULL DEFAULT {default}')
        self.conn.execute("ALTER TABLE recall_feedback ADD COLUMN outcome TEXT NOT NULL DEFAULT 'neutral'")
        self.conn.execute("ALTER TABLE recall_feedback ADD COLUMN idempotency_key TEXT NOT NULL DEFAULT ''")
        self.conn.execute("CREATE UNIQUE INDEX rf_keys ON recall_feedback(idempotency_key) WHERE idempotency_key<>''")
        # Existing additive audit fields as declared by the actual source.
        for col,typ,default in [('visibility_scope','TEXT',"'legacy'"),('origin_bot_id','TEXT',"''"),('origin_session_id','TEXT',"''"),('origin_chat_hash','TEXT',"''"),('project_id','TEXT',"''")]:
            self.conn.execute(f"ALTER TABLE audit_log ADD COLUMN {col} {typ} NOT NULL DEFAULT {default}")
        self.conn.execute(FTS);shared.install_shared_block_schema(self.conn)
        self.dbid=hashlib.sha256(('SOURCE-db-'+name).encode()).hexdigest()[:32]
        self.conn.executemany('INSERT OR REPLACE INTO meta VALUES(?,?)',[('database_instance_id',self.dbid),('memory_revision','0'),
              ('cache_state_revision','0'),('privacy_erasure_applied_seq','0'),('claims_fts_format','v3'),('fts_latest_revision','0'),('qdrant_latest_revision','0')])
        for s in TRIGGERS:self.conn.execute(s)
        self.conn.commit();self.ledger=privacy.ErasureLedger(self.root);self.extra=[]
        self.p=self.actor('source-recipient','recipient-chat');self.creator=self.actor('source-creator','creator-chat')
        self.request_token=N['_REQUEST_HOME'].set(str(self.home))
        self.scope_token=N['_QDRANT_PROFILE_SCOPE'].set({'__home':str(self.home),'__semantic_compatible':'1',
              'MEMORY_WIKI_EMBED_API_KEY':'','MEMORY_WIKI_RERANK_API_KEY':'','MEMORY_WIKI_QDRANT_API_KEY':''})
        N['_EMBED_PROFILE_STATES'][str(self.home.resolve())]={'generation':0}
        self.guard_seen=[];self.on_guard=None;self.target='';self.budget=12000
        actual=self.p._inspect_recall_text
        def inspect(text,**kw):
            answer=actual(text,**kw);self.guard_seen.append((kw.get('source'),kw.get('item_id')))
            if self.on_guard and kw.get('source')==self.target:
                callback=self.on_guard;self.on_guard=None;callback()
            return answer
        self.p._inspect_recall_text=inspect
        self.p._prefetch_delivery_budget=lambda:self.budget # host spill seam only
        self.p._rerank_rows=lambda q,rows,mode:list(rows) # remote rank-order seam, no authority
        self.ids=[];self.bids=[];self.receipt=N['_new_recall_request'](self.p,'prefetch')
        self.root_token=N['_RECALL_REQUEST'].set(self.receipt)
        sample()
    def actor(self,bot,session):
        p=P();p._conn=p._owned_conn=self.conn;p.home=self.home;p.root=self.root;p.db_path=self.path
        p.bot_id=bot;p.session_id=session;p.project_scope='atlas-project';p.database_instance_id=self.dbid
        p.platform='source-component';p.agent_context='primary';p._bot_scope_trusted=True
        p._lifecycle_state='ready';p._transaction_quarantine=None;p._lock=threading.RLock();p._privacy_erasure=self.ledger
        return p
    def add(self,cid,text=SAFE,owner=None):
        owner=owner or self.creator;stamp=int(time.time())
        values={'id':cid,'claim':text,'normalized_claim':text,'topic':'atlas','status':'active','confidence':.8,'salience':.8,
              'source':'tool:synthetic','evidence':'Atlas has literal documentation.','created_at':stamp,'updated_at':stamp,'freshness_at':stamp,
              'hash':hashlib.sha256((cid+text).encode()).hexdigest(),'quality':.9,'risk':'low','type':'fact','trust_class':'fact','trust_score':.55,
              'visibility_scope':'bot','origin_bot_id':owner.bot_id,'origin_chat_hash':owner._chat_hash(owner.session_id),'secrecy_level':'public'}
        self.conn.execute('INSERT INTO claims('+','.join(values)+') VALUES('+','.join('?' for _ in values)+')',tuple(values.values()))
        self.conn.execute('INSERT INTO claims_fts VALUES(?,?,?,?,?,?)',(cid,'','','','',N['claim_search_text'](text,text,'atlas',values['evidence'])))
        self.conn.commit();self.ids.append(cid);return cid
    def share(self,cid='c_shared',*,principal='bot',owner=None,grant=True,attach=True):
        owner=owner or self.creator;self.add(cid,owner=owner)
        result=shared.create_block(owner,'Atlas shared notes',[cid]);bid=result['block_id'];self.bids.append(bid)
        assert result['claim_count']==1
        if grant:shared.grant_block(owner,bid,principal,self.p.bot_id if principal=='bot' else self.p.project_scope)
        if attach and grant:shared.attach_block(self.p,bid,principal)
        self.conn.commit();return bid
    def mutate(self,sql,args=(),*,external=False):
        global EXTERNAL_CLOSED
        if external:
            writer=sqlite3.connect(str(self.path))
            try:
                with writer:writer.execute(sql,args)
            finally:
                writer.close();EXTERNAL_CLOSED+=1
        else:
            with self.conn:self.conn.execute(sql,args)
    def guard(self,callback,target='memory_wiki_shared_block_prefetch'):
        self.target=target;self.on_guard=callback
    def counts(self):return tuple(self.conn.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in ('recall_events','recall_feedback'))
    def frozen(self):return N['_freeze_recall_receipt'](self.receipt)
    def reset_request(self):
        self.receipt=N['_new_recall_request'](self.p,'prefetch');N['_RECALL_REQUEST'].set(self.receipt)
    def refused(self,out,*,expect_guard=True):
        assert out=='' and self.counts()==(0,0)
        if expect_guard:assert self.on_guard is None,'mutation_callback_not_reached'
        value=self.frozen();assert value['final']['emitted_claim_count']==0
        assert not any(cid in json.dumps(value) for cid in self.ids)
        assert not any(bid in json.dumps(value) for bid in self.bids)
        for s in value['searches']:
            assert s['lexical']['visible_count']==s['qdrant']['visible_count']==s['rerank']['safe_candidate_count']==0
            assert s['fusion']['items']==[] and not s['rerank'].get('ranks',[])
            assert all(s['fusion'][k]==0 for k in ('lexical_count','vector_count','overlap_count','union_count','prior_count','like_count'))
    def append_erasure(self,*,pending=False):
        try:
            with self.creator._claim_transaction() as conn:
                seq=self.ledger.append(self.creator,N['normalize_claim'](SAFE),claim_ids=['c_shared'],event_ids=[],episode_ids=[],episode_surface='')
                if pending:raise PendingIntent()
                conn.execute("UPDATE meta SET value=? WHERE key='privacy_erasure_applied_seq'",(str(seq),))
        except PendingIntent:pass
    def close(self,cleanup):
        global CLOSED
        self.on_guard=None
        for c in self.extra:c.close()
        self.conn.close()
        N['_RECALL_REQUEST'].reset(self.root_token);N['_REQUEST_HOME'].reset(self.request_token);N['_QDRANT_PROFILE_SCOPE'].reset(self.scope_token)
        no_links(self.dir);sample()
        if cleanup:
            shutil.rmtree(self.dir);assert not self.dir.exists();CLOSED+=1
    def __enter__(self):return self
    def __exit__(self,*args):self.close(args[0] is None)
