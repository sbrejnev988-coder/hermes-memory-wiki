"""Local connector/document metadata share real SQL COMMIT.

Authored retained document caches exercise existing SQL/SPI paths; not parser
execution, hard process kill, live indexing, OS sandbox or native admission.
"""
from __future__ import annotations
import importlib.util
from pathlib import Path
import sqlite3
import sys
import pytest
import memory_wiki as wiki
from memory_wiki import source_connectors as connectors
from memory_wiki import document_knowledge_graph as graph

_spec=importlib.util.spec_from_file_location('_local_tx_authority_fixture',Path(__file__).with_name('test_document_runtime_authority.py'))
_authority=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(_authority)
owned=_authority.owned
store=_authority.store

def cached(store,label='local-file'):
    return _authority.cached(store,label,physical=False)

def call(provider,path,*,embed=False):
    return connectors.sync_local_file(provider,{'path':str(path),'scope_id':'diagnostic','repository_id':'diagnostic','embed':embed})

def deny_metadata(conn):
    def authorizer(action,a,b,database,trigger):
        return sqlite3.SQLITE_DENY if action in (sqlite3.SQLITE_INSERT,sqlite3.SQLITE_UPDATE) and a=='external_sources' else sqlite3.SQLITE_OK
    conn.set_authorizer(authorizer)

def image(conn):
    return _authority.image(conn)

def key_for(provider,path):
    return connectors._source_key(provider,path.resolve().as_uri(),'diagnostic','diagnostic','local_file')

def test_baseline_metadata_denial_reproduces_split_document_commit(store):
    p,c,sid,path,*_=cached(store,'baseline-opening')
    with p._claim_transaction(c):
        c.execute("UPDATE document_sources SET display_name='before-ingest-owned-name' WHERE source_id=?",(sid,))
    before=image(c)
    source=Path(__file__).with_name('baseline-source_connectors.py')
    spec=importlib.util.spec_from_file_location('memory_wiki._local_tx_baseline',source)
    module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
    deny_metadata(c)
    try:
        with pytest.raises(sqlite3.DatabaseError):module.sync_local_file(p,{'path':str(path),'scope_id':'diagnostic','repository_id':'diagnostic','embed':False})
    finally:c.set_authorizer(None)
    after=image(c)
    assert after['external_sources']==before['external_sources']
    assert after!=before,'Baseline must exhibit actual independently committed document metadata, not a fake failure.'
    assert not c.in_transaction and p._transaction_quarantine is None

@pytest.mark.parametrize('existing',[False,True])
@pytest.mark.parametrize('embed',[False,True])
def test_metadata_denial_rolls_back_document_and_connector_beforeimage(store,existing,embed):
    p,c,sid,path,*_=cached(store,'denial-'+str(existing))
    if existing:call(p,path)
    before=image(c);body=path.read_bytes();deny_metadata(c)
    try:
        with pytest.raises(sqlite3.DatabaseError):call(p,path,embed=embed)
    finally:c.set_authorizer(None)
    assert image(c)==before and path.read_bytes()==body
    assert not c.in_transaction and p._claim_tx_connection is None and p._transaction_quarantine is None

@pytest.mark.parametrize('repeat',[False,True])
@pytest.mark.parametrize('embed',[False,True])
def test_healthy_local_file_tuple_is_published_once_in_actual_owner_commit(store,repeat,embed):
    p,c,sid,path,*_=cached(store,'healthy-'+str(repeat));key=key_for(p,path)
    if repeat:call(p,path)
    observer=sqlite3.connect(str(p.db_path),timeout=0);observed=[];embedded=[]
    observer.row_factory=sqlite3.Row
    before_observer=image(observer)
    target=connectors._RecordCommitHook.apply.__code__
    def profile(frame,event,arg):
        if event=='call' and frame.f_code is graph.embed_pending_documents.__code__:
            embedded.append('after-owning-commit')
            assert not c.in_transaction and len(observed)==1 and observed[0].outcome()=='committed'
        if event=='return' and frame.f_code is target:
            hook=frame.f_locals['self'];observed.append(hook)
            assert c.in_transaction and p._claim_tx_connection is c
            row=observer.execute('SELECT document_source_id,revision_key,content_hash FROM external_sources WHERE source_key=?',(key,)).fetchone()
            if not repeat:assert row is None
            assert image(observer)==before_observer
            assert hook.expected is not None
    prior=sys.getprofile();sys.setprofile(profile)
    try:
        result=call(p,path,embed=embed)
        sys.setprofile(prior)
        assert len(observed)==1 and observed[0].outcome()=='committed'
        assert embedded==(['after-owning-commit'] if embed else [])
        sql='SELECT e.*,s.revision_id,s.file_hash FROM external_sources e JOIN document_sources s ON s.source_id=e.document_source_id WHERE e.source_key=?'
        row=c.execute(sql,(key,)).fetchone()
        committed_observer=observer.execute(sql,(key,)).fetchone()
        assert committed_observer is not None and dict(committed_observer)==dict(row)
        revision=observer.execute("SELECT file_hash,status FROM document_revisions WHERE revision_id=? AND source_id=?",(row['revision_id'],sid)).fetchone()
        assert revision is not None and revision['status']=='active' and revision['file_hash']==row['file_hash']
        assert result['source_key']==key and result['source_id']==sid and result['revision_id']==row['revision_id']
        assert row['content_hash']==row['file_hash'] and row['revision_key']==row['file_hash'][:20] and row['owner_bot_id']==p.bot_id
        assert not c.in_transaction and p._transaction_quarantine is None
    finally:
        sys.setprofile(prior);observer.close()

@pytest.mark.parametrize('command',['COMMIT','ROLLBACK'])
def test_real_sql_completion_denial_keeps_beforeimage_or_exact_unknown_owner(store,command):
    p,c,sid,path,*_=cached(store,'completion-'+command);before=image(c)
    def authorizer(action,a,b,database,trigger):
        if action==sqlite3.SQLITE_TRANSACTION and a==command:return sqlite3.SQLITE_DENY
        if command=='ROLLBACK' and action==sqlite3.SQLITE_INSERT and a=='external_sources':return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK
    c.set_authorizer(authorizer)
    try:
        with pytest.raises(sqlite3.DatabaseError):call(p,path)
        if command=='ROLLBACK':
            assert c.in_transaction and p._claim_tx_connection is c
            assert p._transaction_quarantine is not None
        else:assert image(c)==before and not c.in_transaction and p._transaction_quarantine is None
    finally:
        c.set_authorizer(None)
        if c.in_transaction:c.rollback()
    # The fixture remains responsible for safe quarantine/shutdown disposal.


def test_already_active_transaction_refuses_without_join_or_effect(store):
    p,c,sid,path,*_=cached(store,'already-transaction');before=image(c)
    with p._claim_transaction(c):
        with pytest.raises(RuntimeError,match='connector_transaction_ownership_refused'):call(p,path)
        assert c.in_transaction and p._claim_tx_connection is c
    assert image(c)==before


def test_foreign_connector_owner_cannot_publish_local_metadata(store):
    p,c,sid,path,*_=cached(store,'foreign');call(p,path);key=key_for(p,path)
    with p._claim_transaction(c):c.execute("UPDATE external_sources SET owner_bot_id='foreign-bot' WHERE source_key=?",(key,))
    before=image(c)
    with pytest.raises(PermissionError,match='connector_source_not_owned'):call(p,path)
    assert image(c)==before and not c.in_transaction

@pytest.mark.parametrize('kind',['source_type','adapter_revision','adapter_hash'])
def test_local_hook_rejects_adapter_fabricated_revision_binding(store,kind):
    p,c,sid,path,*_=cached(store,'local-hook-'+kind);params={'source_key':key_for(p,path),'uri':path.resolve().as_uri(),'namespace':'local_file','source_id':sid,'source_type':'local_file','display_uri':'file:///<local-file>','scope_id':'diagnostic','repository_id':'diagnostic','revision_key':'','content_hash':''}
    params[{'source_type':'source_type','adapter_revision':'revision_key','adapter_hash':'content_hash'}[kind]]='caller-value'
    before=image(c)
    with pytest.raises(ValueError,match='connector_local_revision_binding_invalid'):connectors._RecordCommitHook(p,c,**params)
    assert image(c)==before
