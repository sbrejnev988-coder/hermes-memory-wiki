"""ONE six-group SOURCE packet, original/final actual public callers.
Reuse the frozen closure and owned SQLite Fixture. No SDK, producer authority,
network, model, live profile, package boot or replacement permission engine.
"""
from __future__ import annotations
import __future__, ast, copy, hashlib, json, sqlite3, sys, traceback
from pathlib import Path

# Controller-declared current repo-relative inputs. No private owner paths.
SOURCE=Path(__file__).resolve().parents[2]
FREEZE={
    'after':{name:str(SOURCE/name) for name in ('__init__.py','code_knowledge_graph.py',
        'disclosure_fence.py','document_knowledge_graph.py','source_connectors.py')},
    'readthrough':{name:str(SOURCE/name) for name in ('recall_orchestrator.py','online_metrics.py',
        'shared_blocks.py','privacy_erasure.py','guard.py','semantic_io.py','memory_events.py',
        'recall_planner.py','episodic_memory.py','memory_observations.py','document_extractors.py','http_safety.py')},
    'support':{name:str(SOURCE/'tests/helpers'/name) for name in
        ('cases_disclosure.py','cases_shared_closed.py','cases_terminal.py')},
}

SUPPORT_PATH=FREEZE['support']['cases_terminal.py']
SUPPORT_TREE=ast.parse(devtools_read_bound(SUPPORT_PATH))
CUT=len(SUPPORT_TREE.body)
ADDED={'__init__','_retain_read_fence','_visible_code_claim_result','_code_claim_query',
       '_symbol_history','_repository_context','_code_graph_identity','_canonical_code_path',
       '_release_connection_for_retry','_shutdown_lifecycle','_retain_code_claim_images'}
SOURCE_ENV={
    'MEMORY_WIKI_DOCUMENT_RERANK':'0','MEMORY_WIKI_CODE_GRAPH_RERANK':'0',
    'MEMORY_WIKI_ONLINE_METRICS_ENABLED':'0',
}
RESULTS=[];DETAILS=[];TRACES=[];SOURCE_BIND=[];F=None;S=None;PEAK=0
PUBLIC_CALLS=0;READERS_CLOSED=0;FINAL_FIXTURE_CLOSES=0
BODY='Atlas carrier notes describe stable deterministic source navigation.'
CODE_BODY='def atlas_carrier(value): return value  # literal <tag> [data]'
DOCID='doc_carrier_original';REV='doc_revision_original';UNIT='unit_carrier_original'
CHUNK='doc_chunk_original';REPO='atlas-project';FILE='atlas_carrier.py'
SYMBOL='atlas_carrier';CODECHUNK='code_chunk_original';EDGE='edge_original'
CLAIM='code_claim_original';OWN_CODE='embedded_code_original';OWN_DOC='embedded_doc_original'
DIGEST=hashlib.sha256(CODE_BODY.encode()).hexdigest()
CALLS={
 'memory_wiki_document_query':({'query':'atlas carrier','source_id':DOCID},'results'),
 'memory_wiki_document_source':({'source_id':DOCID},'source_id'),
 'memory_wiki_document_unit_context':({'source_id':DOCID,'unit_id':UNIT},'units'),
 'memory_wiki_document_neighbors':({'source_id':DOCID,'anchor':'paragraph:1'},'edges'),
 'memory_wiki_document_status':({},'sources'),
 'memory_wiki_source_list':({},'sources'),
 'memory_wiki_code_graph_query':({'query':'atlas carrier','repository_id':REPO},'results'),
 'memory_wiki_code_line_context':({'repository_id':REPO,'file_path':FILE,'line_no':1},'lines'),
 'memory_wiki_code_graph_neighbors':({'repository_id':REPO,'node_id':SYMBOL},'nodes'),
 'memory_wiki_code_graph_status':({'repository_id':REPO},'repositories'),
 'memory_wiki_code_claim_query':({'repository_id':REPO},'claims'),
 'memory_wiki_symbol_history':({'repository_id':REPO,'symbol_id':SYMBOL},'history'),
 'memory_wiki_repository_context':({'repository_id':REPO},'claims'),
}
QUERY_TOOLS=('memory_wiki_document_query','memory_wiki_code_graph_query')


def prefix(mode):
    nodes=copy.deepcopy(SUPPORT_TREE.body[:CUT])
    tr=ast.parse(devtools_read_bound(FREEZE[mode]['__init__.py']))
    cl=next(n for n in tr.body if isinstance(n,ast.ClassDef) and n.name=='MemoryWikiProvider')
    available={n.name for n in cl.body if isinstance(n,ast.FunctionDef)}
    assignment=next(n for n in nodes if isinstance(n,ast.Assign)
                    and any(isinstance(t,ast.Name) and t.id=='M' for t in n.targets))
    assignment.value.elts.extend(ast.Constant(n) for n in sorted((ADDED&available)-ast.literal_eval(assignment.value)))
    # Only physical page layout is changed in the old owned fixture, before DDL.
    # Both modes run identical declarations, owner/ACL and business data.
    ns={'__name__':'upper_source_support_'+mode,'__file__':SUPPORT_PATH,
        'DEVTOOLS_SCRATCH':DEVTOOLS_SCRATCH,
        'DEVTOOLS_INPUTS':{**FREEZE['readthrough'],**FREEZE['support'],**FREEZE[mode]},
        'devtools_read_bound':devtools_read_bound,'devtools_case_started':devtools_case_started}
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes,type_ignores=[])),SUPPORT_PATH,'exec',dont_inherit=True),ns)
    ns['os'].environ.update(SOURCE_ENV)
    # All public module aliases resolve to real SHA-bound source bodies.
    doc=ns['documents'];code=ns['code'];N=ns['N']
    connectors=ns['source_module']('source_connectors','source_connectors.py')
    http=ns['source_module']('http_safety','http_safety.py')
    for key,val in {
        '_document_query':doc.query_documents,'_document_source':doc.document_source,
        '_document_unit_context':doc.document_unit_context,'_document_neighbors':doc.document_neighbors,
        '_document_status':doc.document_status,'_list_external_sources':connectors.list_sources,
        '_query_code_graph':code.query_code_graph,'_code_line_context':code.code_line_context,
        '_code_graph_neighbors':code.code_graph_neighbors,'_code_graph_status':code.code_graph_status,
        '_map_code_graph_identity':code._graph_lookup_identity,
        '_AUDIT_PREPARATION':ns['fencing'].AUDIT_PREPARATION,
        '_semantic_response_json':ns['semantic'].response_json,
        '_semantic_json_body':ns['semantic'].json_body,
        '_semantic_curl_capture':ns['semantic'].curl_capture,
        '_SEMANTIC_CURL_CONFIG_OVERHEAD_BYTES':ns['semantic'].CURL_CONFIG_OVERHEAD_BYTES,
        '_urlopen_no_redirect':http.urlopen_no_redirect,
    }.items():N[key]=val
    old=ns['old_fixture']
    fixture_node=copy.deepcopy(next(n for n in old.body if isinstance(n,ast.ClassDef) and n.name=='Fixture'))
    init=next(n for n in fixture_node.body if isinstance(n,ast.FunctionDef) and n.name=='__init__')
    index=next(i for i,n in enumerate(init.body) if isinstance(n,ast.Assign)
               and any(isinstance(v,ast.Attribute) and v.attr=='conn' for v in n.targets))
    init.body[index+1:index+1]=ast.parse("self.conn.execute('PRAGMA page_size=512')").body
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fixture_node],type_ignores=[])),ns['INPUTS']['cases_shared_closed.py'],'exec',dont_inherit=True),ns)
    base=ns['Fixture']
    terminal_fixture=next(n for n in SUPPORT_TREE.body[:CUT] if isinstance(n,ast.ClassDef) and n.name=='Fixture')
    ns['PreviousFixture']=base
    exec(compile(ast.Module(body=[terminal_fixture],type_ignores=[]),SUPPORT_PATH,'exec',dont_inherit=True),ns)
    ns['sample']=sample
    f=ns['Fixture']('upper-'+mode)
    ns['N']['_RECALL_REQUEST'].set(None)
    f.p._graph_writer_connections={}
    f.p._transaction_primary=None;f.p._transaction_cleanup_notes=()
    assert f.conn.execute('PRAGMA page_size').fetchone()[0]==512
    assert f.p._conn is f.p._owned_conn is f.conn
    ctor=next(n for n in cl.body if isinstance(n,ast.FunctionDef) and n.name=='__init__')
    # Actual constructor is loaded, not a fabricated provider SDK.
    assert ns['P'].__dict__['__init__'].__code__.co_firstlineno==ctor.lineno
    if mode=='after':assert type(f.p._graph_reader_connections) is dict and not f.p._graph_reader_connections
    f.p._canonical_code_path(f'./{FILE}')  # ordinary actual method, no normalization of identifiers
    doc.install_document_graph_schema(f.conn)
    code.install_code_graph_schema(f.conn)
    connectors.install_source_connector_schema(f.conn)
    # Existing actual code-claim metadata declaration, no invented schema.
    f.conn.execute(ns['ddl']('CREATE TABLE IF NOT EXISTS code_claim_metadata('))
    present={r[1] for r in f.conn.execute('PRAGMA table_info(code_claim_metadata)')}
    # Include only literal additive declarations reachable in current schema.
    for node in ast.walk(cl):
        if not isinstance(node,ast.Call) or not node.args or not isinstance(node.args[0],ast.Constant):continue
        sql=node.args[0].value
        if isinstance(sql,str) and sql.startswith('ALTER TABLE code_claim_metadata ADD COLUMN '):
            name=sql.split()[5]
            if name not in present:f.conn.execute(sql);present.add(name)
    f.conn.commit()
    for cid,topic in ((CLAIM,'code-shrinker'),(OWN_CODE,'code-intelligence'),(OWN_DOC,'document-intelligence')):
        f.add(cid,BODY,owner=f.p)
        f.mutate('UPDATE claims SET topic=? WHERE id=?',(topic,cid))
    f.add('foreign_code_claim',BODY,owner=f.creator)
    globals()['S']=ns;globals()['F']=f
    seed()
    sample()
    for name,path in FREEZE[mode].items():
        SOURCE_BIND.append({'mode':mode,'module':name,'sha256':hashlib.sha256(devtools_read_bound(path)).hexdigest()})
    return ns,f


def sample():
    global PEAK
    import stat
    files=[]
    root=Path(DEVTOOLS_SCRATCH)
    for p in root.rglob('*'):
        v=p.lstat()
        assert not stat.S_ISLNK(v.st_mode) and not getattr(v,'st_file_attributes',0)&1024
        if stat.S_ISREG(v.st_mode):files.append((p,v.st_size))
    size=sum(s for _,s in files)+max((s for p,s in files if p.suffix=='.sqlite3'),default=0)+16000
    PEAK=max(PEAK,size);assert size<=550000,('owned_SOURCE_fixture_cap',size)


def insert(table,row):
    assert not F.conn.in_transaction
    with F.conn:
        F.conn.execute('INSERT OR REPLACE INTO '+table+'('+','.join(row)+') VALUES('+','.join('?' for _ in row)+')',tuple(row.values()))


def seed():
    import time
    stamp=int(time.time())
    insert('document_sources',{'source_id':DOCID,'scope_id':REPO,'repository_id':REPO,
        'source_path':str(F.root/'atlas-notes.txt'),'display_name':'Atlas carrier notes','title':'Atlas carrier',
        'extension':'.txt','revision_id':REV,'file_hash':DIGEST,'updated_at':stamp})
    insert('document_revisions',{'revision_id':REV,'source_id':DOCID,'file_hash':DIGEST,'unit_count':1,'chunk_count':1})
    insert('document_units',{'unit_id':UNIT,'source_id':DOCID,'revision_id':REV,'anchor':'paragraph:1',
        'ordinal':1,'title':'Atlas carrier','unit_text':BODY,'content_hash':DIGEST,'updated_at':stamp})
    insert('document_chunks',{'chunk_id':CHUNK,'source_id':DOCID,'revision_id':REV,
        'scope_id':REPO,'repository_id':REPO,'title':'Atlas carrier','chunk_text':BODY,'embedding_text':BODY,
        'start_anchor':'paragraph:1','end_anchor':'paragraph:1','content_hash':DIGEST,
        'embedding_claim_id':OWN_DOC,'updated_at':stamp})
    insert('document_edges',{'edge_id':'doc_edge_original','source_id':DOCID,'revision_id':REV,
        'source_anchor':'paragraph:1','target_anchor':'paragraph:2','predicate':'next','evidence':BODY})
    insert('external_sources',{'source_key':'connector_original','owner_bot_id':F.p.bot_id,'source_type':'record',
        'display_uri':'urn:atlas:carrier','scope_id':REPO,'repository_id':REPO,'document_source_id':DOCID,
        'revision_key':REV,'content_hash':DIGEST,'status':'active','created_at':stamp,'updated_at':stamp})
    insert('code_graph_repositories',{'repository_id':REPO,'root':'atlas-source-root','snapshot_hash':DIGEST,'updated_at':stamp})
    insert('code_graph_files',{'repository_id':REPO,'file_path':FILE,'file_hash':DIGEST,'line_count':1,'updated_at':stamp})
    insert('code_graph_symbols',{'repository_id':REPO,'symbol_id':SYMBOL,'file_path':FILE,
        'qualified_name':SYMBOL,'short_name':SYMBOL,'signature':'def atlas_carrier(value)',
        'kind':'function','search_text':CODE_BODY,'content_hash':DIGEST,'start_line':1,'end_line':1,'updated_at':stamp})
    insert('code_graph_chunks',{'repository_id':REPO,'chunk_id':CODECHUNK,'file_path':FILE,'symbol_id':SYMBOL,
        'qualified_name':SYMBOL,'chunk_text':CODE_BODY,'embedding_text':CODE_BODY,'search_text':CODE_BODY,
        'content_hash':DIGEST,'embedding_claim_id':OWN_CODE,'updated_at':stamp})
    insert('code_graph_lines',{'repository_id':REPO,'file_path':FILE,'line_no':1,'line_id':'line_original',
        'line_text':CODE_BODY,'symbol_id':SYMBOL,'chunk_id':CODECHUNK,'text_hash':DIGEST,'anchor_hash':DIGEST,'updated_at':stamp})
    insert('code_graph_edges',{'repository_id':REPO,'edge_id':EDGE,'source_id':SYMBOL,'target_id':SYMBOL,
        'source_file':FILE,'target_file':FILE,'predicate':'calls','evidence':BODY,'confidence':.8})
    for cid in (CLAIM,'foreign_code_claim'):
        insert('code_claim_metadata',{'claim_id':cid,'repository_id':REPO,'file_path':FILE,'symbol_id':SYMBOL,
            'content_hash':DIGEST,'symbol_revision':'original-symbol-revision','claim_type':'code_claim'})
    with F.conn:
        for table in ('document_units_fts','document_chunks_fts','code_graph_symbols_fts','code_graph_chunks_fts','code_graph_lines_fts'):
            F.conn.execute('DELETE FROM '+table)
        F.conn.execute('INSERT INTO document_units_fts VALUES(?,?,?,?,?,?)',(DOCID,UNIT,'text','Atlas carrier','paragraph:1',BODY))
        F.conn.execute('INSERT INTO document_chunks_fts VALUES(?,?,?,?,?)',(DOCID,CHUNK,'Atlas carrier','paragraph:1',BODY))
        F.conn.execute('INSERT INTO code_graph_symbols_fts VALUES(?,?,?,?,?,?)',(REPO,SYMBOL,FILE,SYMBOL,'def atlas_carrier(value)',CODE_BODY))
        F.conn.execute('INSERT INTO code_graph_chunks_fts VALUES(?,?,?,?,?,?,?)',(REPO,CODECHUNK,FILE,SYMBOL,SYMBOL,CODE_BODY,CODE_BODY))
        F.conn.execute('INSERT INTO code_graph_lines_fts VALUES(?,?,?,?)',(REPO,FILE,1,CODE_BODY))
    sample()


def invoke(tool,args=None):
    global PUBLIC_CALLS
    PUBLIC_CALLS+=1
    payload=json.loads(F.p.handle_tool_call(tool,dict(CALLS[tool][0]) if args is None else args))
    assert isinstance(payload,dict)
    assert S['fencing'].current_delivery() is None
    assert S['N']['_RECALL_REQUEST'].get() is None
    return payload


def healthy(tool,payload):
    assert payload.get('success') is True and not payload.get('disclosure_status') and payload.get('disclosure')!='withheld',(tool,payload.get('error'))
    assert payload.get(CALLS[tool][1]),('healthy_public_data_missing',tool,payload.get('error'))
    encoded=json.dumps(payload)
    assert 'foreign_code_claim' not in encoded
    if tool in QUERY_TOOLS:
        assert payload['retrieval']['fusion']=='weighted_rrf_k60'
        assert payload['retrieval']['semantic_chunks']>=1,('actual_semantic_claim_mapping_lost',tool,payload['retrieval'])
        assert not payload['retrieval']['semantic_error'],(tool,payload['retrieval']['semantic_error'])
    if tool=='memory_wiki_code_line_context':
        assert payload['output_boundary']['schema']=='code_graph_navigation_data/v1'
        represented=payload['lines'][0]['line_text']
        assert json.loads('"'+represented+'"')==CODE_BODY
        assert '<tag>' not in represented and '[data]' not in represented
        assert payload['lines'][0]['text_hash']==DIGEST


def withheld(tool,payload):
    assert payload.get('disclosure_status')=='withheld',('old_source_not_withdrawn',tool,payload.get('error'))
    encoded=json.dumps(payload)
    assert not any(x in encoded for x in (BODY,CODE_BODY,DOCID,REV,UNIT,CHUNK,REPO,FILE,SYMBOL,CODECHUNK,EDGE,CLAIM,OWN_CODE,OWN_DOC,'connector_original'))
    assert not F.conn.in_transaction and F.p._transaction_quarantine is None
    assert F.counts()==(0,0),'readonly_query_acquired_accounting_effect'
    if hasattr(F.p,'_graph_reader_connections'):assert not F.p._graph_reader_connections
    TRACES.append({'tool':tool,'outcome':'withheld','no_old_text_identity_metadata':True})


def mutate_source(tool,external=False,aba=False):
    if tool.startswith('memory_wiki_document_'):
        table,column,key,identity='document_sources','title','source_id',DOCID
    elif tool=='memory_wiki_source_list':
        table,column,key,identity='external_sources','display_uri','source_key','connector_original'
    elif tool in {'memory_wiki_code_claim_query','memory_wiki_symbol_history','memory_wiki_repository_context'}:
        table,column,key,identity='code_claim_metadata','symbol_revision','claim_id',CLAIM
    else:table,column,key,identity='code_graph_repositories','root','repository_id',REPO
    before=F.conn.execute('SELECT '+column+' FROM '+table+' WHERE '+key+'=?',(identity,)).fetchone()[0]
    F.mutate('UPDATE '+table+' SET '+column+'=? WHERE '+key+'=?',('later-source-image',identity),external=external)
    if aba:F.mutate('UPDATE '+table+' SET '+column+'=? WHERE '+key+'=?',(before,identity),external=external)


def serialization(tool,callback):
    original=S['N']['tool_result'];seen=[]
    def late(*a,**kw):
        output=original(*a,**kw)
        if not seen:
            seen.append(True);callback()
        return output
    S['N']['tool_result']=late
    try:out=invoke(tool)
    finally:S['N']['tool_result']=original
    assert seen,'actual_tool_result_serialization_not_reached'
    return out


def baseline_witness_and_healthy_full_roster():
    global F,S,FINAL_FIXTURE_CLOSES
    # Earlier vulnerable witnesses remain in the preserved source-only receipt
    # 6f108bbce135a8d1427dda92534285299592d1774fc9f354aecb2e731eda8a37.
    # They are historical, not re-executed on current main or fake baseline code.
    prefix('after')
    for tool in CALLS:healthy(tool,invoke(tool))
    assert F.counts()==(0,0) and not F.p._graph_reader_connections
    return {'historical_baseline_witnesses_reexecuted':False,'current_healthy_public_roster':sorted(CALLS),
            'actual_semantic_restrictions_and_code_representation':True,'no_blanket_deny':True}


def all_registry_public_serialization_original_carriers():
    for tool in CALLS:
        seed();out=serialization(tool,lambda:mutate_source(tool,external=True))
        withheld(tool,out)
    return {'closed_public_roster':sorted(CALLS),'actual_serialization_after_module_finish':True}


def private_close_callbacks_use_original_genuine_parent():
    global READERS_CLOSED
    code=S['code'];original=code._open_graph_reader_connection
    observed=[]
    for tool in ('memory_wiki_code_graph_query','memory_wiki_code_line_context','memory_wiki_code_graph_neighbors','memory_wiki_code_graph_status'):
        seed();stage=[]
        def factory(provider,**kw):
            conn,owned=original(provider,**kw)
            assert owned and type(conn) is code._GraphReaderConnection
            fence=conn._graph_read_fence;terminal=S['fencing'].current_delivery(provider)
            assert fence in terminal.fences and fence.conn is F.conn and fence.source_conn is conn
            assert conn not in provider._graph_writer_connections
            initial=(fence.anchor,fence.epoch,dict(fence.selectors))
            close=conn.close
            def late():
                close()
                assert conn._graph_read_state=='closed' and conn not in provider._graph_reader_connections
                stage.append('native_closed_before_mutation')
                mutate_source(tool,external=True)
                assert fence.anchor==initial[0] and fence.epoch==initial[1]
            conn.close=late
            observed.append((conn,fence,initial));return conn,owned
        code._open_graph_reader_connection=factory
        try:out=invoke(tool)
        finally:code._open_graph_reader_connection=original
        assert stage==['native_closed_before_mutation'];withheld(tool,out)
        conn,fence,initial=observed[-1]
        assert fence.images and fence.selectors and fence.conn is F.p._owned_conn
        try:conn.execute('SELECT 1')
        except sqlite3.ProgrammingError:READERS_CLOSED+=1
        else:raise AssertionError('private_native_connection_not_closed')
    seed();healthy('memory_wiki_code_graph_query',invoke('memory_wiki_code_graph_query'))
    return {'actual_factory_original_parent_fence':True,'closed_private_reader_never_read_again':True,
            'four_finally_close_callback_withdrawals':4,'healthy_query_after_completed_close':True}


def source_owner_privacy_erasure_and_ABA_no_rebase():
    import time
    for tool in QUERY_TOOLS:
        for mode in ('source','bot','project','exact_owner','erasure','ABA_same','ABA_external'):
            seed();field=None;original=None;replacement=None
            ledger_before=F.ledger.log_path.read_bytes()
            if mode in ('bot','project'):
                field='bot_id' if mode=='bot' else 'project_scope';original=getattr(F.p,field)
                cb=lambda:setattr(F.p,field,'different-original-owner')
            elif mode=='exact_owner':
                replacement=sqlite3.connect(str(F.path));replacement.row_factory=sqlite3.Row;F.extra.append(replacement)
                cb=lambda:setattr(F.p,'_conn',replacement)
            elif mode=='erasure':
                def cb():
                    S['privacy'].ErasureLedger.append(F.ledger,F.p,BODY,claim_ids=[OWN_DOC if tool==QUERY_TOOLS[0] else OWN_CODE],event_ids=[],episode_ids=[],episode_surface='')
            else:cb=lambda:mutate_source(tool,external=mode in ('source','ABA_external'),aba=mode.startswith('ABA'))
            try:out=serialization(tool,cb)
            finally:
                if field:setattr(F.p,field,original)
                if replacement is not None:F.p._conn=F.conn
            withheld(tool,out)
            if mode=='erasure':
                # Restore test-owned synthetic log via exact original bytes;
                # not a production replay/recovery or erasure waiver.
                entries=F.ledger._load_unlocked();assert entries
                F.ledger.log_path.write_bytes(ledger_before)
                with F.conn:F.conn.execute("UPDATE meta SET value='0' WHERE key='privacy_erasure_applied_seq'")
    seed()
    return {'query_tools':list(QUERY_TOOLS),'raw_source_owner_privacy_erasure_ABA_modes':7,
            'original_identity_and_epoch_not_rebased':True,'same_and_external_SQLite_ABA':True}


def last_cleanup_and_prepare_callbacks_precede_original_reread():
    from contextlib import contextmanager
    N=S['N'];native=S['N']['_native_profile_scope']
    for tool in QUERY_TOOLS:
        for seam in ('native_cleanup','last_journal_prepare','last_guard'):
            seed();seen=[]
            def cb():seen.append(True);mutate_source(tool,external=True)
            if seam=='native_cleanup':
                # Actual public wrapper/contextmanager body, synthetic host
                # callback only. This is not execution of the real native SDK.
                old_set=N['_set_native_home'];old_reset=N['_reset_native_home']
                old_result=N['tool_result'];armed=[]
                def serialized(*a,**kw):
                    value=old_result(*a,**kw);armed.append(True);return value
                N['tool_result']=serialized
                native_var=S['contextvars'].ContextVar('owned_source_native_scope',default=None)
                N['_set_native_home']=lambda home:native_var.set(str(home))
                def reset(token):
                    native_var.reset(token)
                    if armed and not seen:cb()
                N['_reset_native_home']=reset
            elif seam=='last_journal_prepare':F.arm=cb
            else:
                if tool==QUERY_TOOLS[0]:
                    actual=S['documents']._guard_document_output
                    def guard(*a,**kw):
                        out=actual(*a,**kw)
                        if not seen and isinstance(a[0],dict) and 'results' in a[0]:cb()
                        return out
                    S['documents']._guard_document_output=guard
                else:
                    actual=S['code']._graph_read_output
                    def render(*a,**kw):
                        out=actual(*a,**kw)
                        if not seen:cb()
                        return out
                    S['code']._graph_read_output=render
            try:out=invoke(tool)
            finally:
                F.arm=None
                if seam=='native_cleanup':
                    N['_set_native_home']=old_set;N['_reset_native_home']=old_reset;N['tool_result']=old_result
                elif seam=='last_guard':
                    if tool==QUERY_TOOLS[0]:S['documents']._guard_document_output=actual
                    else:S['code']._graph_read_output=actual
            assert seen,'final_cleanup_or_prepare_callback_not_reached';withheld(tool,out)
    seed()
    # Foreign handles with identical path and database UUID do NOT gain writer
    # or read-carrier authority. Real factory/public healthy flow still works.
    foreign=sqlite3.connect(str(F.path));foreign.row_factory=sqlite3.Row;F.extra.append(foreign)
    try:S['code']._code_disclosure(F.p,foreign)
    except RuntimeError:pass
    else:raise AssertionError('ad_hoc_reader_gained_original_owner')
    try:F.p._require_claim_writer(foreign)
    except RuntimeError:pass
    else:raise AssertionError('ad_hoc_reader_gained_writer_permission')
    for tool in QUERY_TOOLS:healthy(tool,invoke(tool))
    return {'real_final_native_cleanup_last_guard_and_journal_prepare_seams':6,
            'path_UUID_are_not_reader_or_writer_grants':True,'healthy_positive_after_finished_callbacks':True,
            'future_host_speech_atomicity_claimed':False}


def primary_UNKNOWN_cleanup_reaches_same_current_caller():
    code=S['code'];factory=code._open_graph_reader_connection;body=code._query_code_graph_on_connection
    observations=[]
    for has_primary in (True,False):
        seed();primary=RuntimeError('SOURCE_original_query_primary');cleanup=sqlite3.OperationalError('SOURCE_permanent_close_refusal')
        owned=[]
        def open_reader(provider,**kw):
            conn,flag=factory(provider,**kw);owned.append(conn)
            def refusal():raise cleanup
            conn.close=refusal
            return conn,flag
        def query(*a,**kw):
            out=body(*a,**kw)
            if has_primary:raise primary
            return out
        code._open_graph_reader_connection=open_reader;code._query_code_graph_on_connection=query
        reached=None
        try:invoke('memory_wiki_code_graph_query')
        except BaseException as exc:reached=exc
        finally:code._open_graph_reader_connection=factory;code._query_code_graph_on_connection=body
        expected=primary if has_primary else cleanup
        assert reached is expected,'primary_cleanup_UNKNOWN_lost_at_actual_upper_caller'
        conn=owned[0]
        assert F.p._transaction_primary is expected and F.p._transaction_quarantine is conn
        assert F.p._lifecycle_state=='quarantined' and conn._graph_read_state=='quarantined'
        assert F.p._graph_reader_connections.get(conn) is conn._graph_read_lifetime
        assert F.p._conn is F.p._owned_conn is F.conn and conn.execute('SELECT 1').fetchone()[0]==1
        assert not F.p._release_connection_for_retry(expected)
        try:F.p._connect()
        except RuntimeError:pass
        else:raise AssertionError('UNKNOWN_reader_owner_reconnected')
        assert conn in F.p._graph_reader_connections and F.p._transaction_primary is expected
        observations.append({'has_primary':has_primary,'same_exception_at_public_caller':True,
             'exact_private_reader_retained_live_before_fixture_teardown':True,
             'shared_owner_preserved_no_reconnect':True,'outcome':'UNKNOWN'})
        # Exact fixture-owned safety close only, never production success.
        sqlite3.Connection.close(conn)
        try:conn.execute('SELECT 1')
        except sqlite3.ProgrammingError:pass
        else:raise AssertionError('fixture_safety_close_failed')
        F.p._graph_reader_connections.clear()
        F.p._transaction_quarantine=None;F.p._transaction_primary=None
        F.p._lifecycle_state='ready';F.p._degraded=False
    return {'production_before_teardown':observations,'cleanup_refusal_not_suppressed':True,
            'fixture_safety_cleanup_is_not_production_recovery':True}

CASES=[baseline_witness_and_healthy_full_roster,all_registry_public_serialization_original_carriers,
       private_close_callbacks_use_original_genuine_parent,source_owner_privacy_erasure_and_ABA_no_rebase,
       last_cleanup_and_prepare_callbacks_precede_original_reread,primary_UNKNOWN_cleanup_reaches_same_current_caller]
stop=False;cleanup_error=None
try:
    for case in CASES:
        devtools_case_started(case.__name__)
        if stop:
            RESULTS.append({'id':case.__name__,'outcome':'skipped','reason':'retained_failure_STOP_no_auto_cycle'});continue
        try:
            detail=case();DETAILS.append({'case':case.__name__,**detail});RESULTS.append({'id':case.__name__,'outcome':'passed'})
        except BaseException as exc:
            RESULTS.append({'id':case.__name__,'outcome':'failed' if isinstance(exc,AssertionError) else 'error','error':type(exc).__name__})
            traceback.print_exc(limit=6);stop=True
finally:
    if F is not None:
        try:sample();F.close(False);FINAL_FIXTURE_CLOSES+=1
        except BaseException as exc:cleanup_error=type(exc).__name__;traceback.print_exc(limit=4);stop=True
print(json.dumps({'schema':'memory-stack.cases/v1','cases':RESULTS,'details':DETAILS,'traces':TRACES,
    'source_actual_SHA':SOURCE_BIND,'fixture_peak_bytes':PEAK,'fixture_peak_kind':'sampled no-follow bytes + largest DELETE journal +16000, not OS continuous peak',
    'actual_public_invocations':PUBLIC_CALLS,'final_fixture_closes':FINAL_FIXTURE_CLOSES,
    'verified_closed_private_readers':READERS_CLOSED,'cleanup_error':cleanup_error,
    'scope':'SOURCE-only real selected handler/module/factory/ACL/SQLite bodies, no native SDK or live proof'},separators=(',',':')))
raise SystemExit(1 if stop else 0)
