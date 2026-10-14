"""Whole prefetch ownership controls on genuine SDK/SQLite, own authored claim.

No fake SDK, source callable replacement, live data or model/network reply.
The short budget cases change only a synthetic import's scalar deadline.
"""
from __future__ import annotations
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import sys
import threading
import time
import pytest
import memory_wiki as wiki
from agent.memory_provider import MemoryProvider

_spec=importlib.util.spec_from_file_location('_prefetch_owned_peer',Path(__file__).with_name('test_recovery_atomic_contract.py'))
_peer=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(_peer)
owned=_peer.owned
TEXT='Atlas telescope diagnostic fixture uses the copper observatory.'
QUERY='Atlas telescope diagnostic fixture'

@pytest.fixture
def recalled(request):
    root=Path(os.environ['RECOVERY_DIAGNOSTIC_OUT'])/'controls'/hashlib.sha256(request.node.nodeid.encode()).hexdigest()[:16]
    home=root/'home';home.mkdir(parents=True,exist_ok=False)
    # A distinct genuine provider home must have its own declared route even
    # with semantic I/O disabled. Do not fake profile_ready or borrow importer
    # credentials. These are synthetic names; the network audit remains DENY.
    (home/'.env').write_text('MEMORY_WIKI_QDRANT_URL=http://127.0.0.1:6333\nMEMORY_WIKI_QDRANT_COLLECTION=owned-prefetch-claims\nMEMORY_WIKI_EPISODIC_QDRANT_COLLECTION=owned-prefetch-episodes\nMEMORY_WIKI_QDRANT_ALIAS=owned-prefetch-claims\n',encoding='utf-8')
    scope=wiki._native_profile_scope(home);scope.__enter__()
    p=wiki.MemoryWikiProvider();assert p.__class__.__bases__==(MemoryProvider,)
    p.initialize('prefetch-owned-'+root.name,hermes_home=str(home),agent_context='test',bot_id='prefetch-owned-bot',project_id='diagnostic')
    assert p._lifecycle_state=='ready'
    stamp=wiki.now();cid='c_prefetch_owned'
    row={'id':cid,'claim':TEXT,'normalized_claim':TEXT,'topic':'atlas','hash':wiki.sha(cid+'\0'+TEXT),'type':'fact','status':'active','risk':'low','quality':.95,'confidence':.95,'salience':.95,'freshness_at':stamp,'created_at':stamp,'updated_at':stamp,'pinned':1,'source':'fixture:authored-prefetch','source_kind':'curated','memory_class':'fact','trust_class':'fact','trust_score':.95,'memory_revision':1,'visibility_scope':'global','origin_bot_id':p.bot_id,'origin_session_id':p.session_id,'origin_chat_hash':p._chat_hash(),'why_believe':'Authored offline fixture.'}
    with p._claim_transaction() as c:
        columns={r[1] for r in c.execute('PRAGMA table_info(claims)')};stored={k:v for k,v in row.items() if k in columns}
        c.execute('INSERT INTO claims('+','.join(stored)+') VALUES('+','.join('?' for _ in stored)+')',tuple(stored.values()))
    p._upsert_fts(cid)
    try:yield p
    finally:
        attempt=p._prefetch_attempt
        if attempt is not None and attempt.worker is not None:
            attempt.cancel.set();attempt.worker.join(3)
            assert not attempt.worker.is_alive()
        if p._conn is not None:
            p._conn.set_authorizer(None);p._conn.set_trace_callback(None);p._conn.set_progress_handler(None,0)
            # Fixture-only safety close does not prove production cleanup of UNKNOWN.
            p._conn.close()
        scope.__exit__(None,None,None)

def accounting(p):
    c=p._conn
    return (tuple(c.execute('SELECT id,access_count,recall_count,last_recalled FROM claims ORDER BY id').fetchall()),tuple(c.execute('SELECT id,claim_id,used FROM recall_events ORDER BY id').fetchall()),tuple(c.execute('SELECT consumer_id,last_seen_revision FROM memory_consumers ORDER BY consumer_id').fetchall()))

def join_attempt(p):
    a=p._prefetch_attempt;a.worker.join(3)
    assert not a.worker.is_alive() and a.done.is_set() and not p._prefetch_admission.locked()
    return a

def gate_call(name,entered,release,*,owned=False,raise_primary=False,wait_seconds=3):
    fired=[]
    def profile(frame,event,arg):
        if event!='call' or frame.f_code.co_name!=name or fired:return
        current=threading._active.get(threading.get_ident())
        if current is None or current.name!='memory-wiki-prefetch-owner':return
        if owned and frame.f_locals.get('_delivery') is None:return
        fired.append(True);entered.set()
        if raise_primary:raise TimeoutError('owned-primary-boundary-refusal')
        assert release.wait(wait_seconds),'owned-release-not-observed'
    return profile,fired

def test_healthy_default_budget_public_recall_is_nonempty(recalled):
    p=recalled
    observations=[]
    def observe(frame,event,arg):
        if event=='return' and frame.f_code.co_name=='_runtime_identity' and type(arg) is dict:
            observations.append({'identity':{k:arg.get(k) for k in ['conn_path_matches','profile_ready','profile_reason','request_home','provider_home','db_path','conn_path']}})
        if event=='return' and frame.f_code.co_name in {'finish','commit','_prefetch_impl','prefetch'}:
            item=frame.f_locals.get('self');observations.append({'fn':frame.f_code.co_name,'file':Path(frame.f_code.co_filename).name,'result':arg if type(arg) in (bool,type(None)) else len(arg) if type(arg) is str else type(arg).__name__,'reason':getattr(item,'reason',None),'phase':getattr(item,'phase',None),'ok':getattr(item,'ok',None)})
    def exceptions(frame,event,arg):
        if event=='exception' and Path(frame.f_code.co_filename).name=='disclosure_fence.py':
            kind,error,_=arg
            observations.append({'exception_fn':frame.f_code.co_name,'kind':kind.__name__,'label':str(error)[:180]})
        return exceptions
    old_trace=threading.gettrace();threading.settrace(exceptions)
    prior=threading.getprofile();threading.setprofile(observe)
    try:value=p.prefetch(QUERY)
    finally:threading.setprofile(prior);threading.settrace(old_trace)
    if not value:print(json.dumps({'owned-diagnostic':observations[-30:],'identities':[r for r in observations if 'identity' in r][:8]},ensure_ascii=False))
    assert TEXT in value and '\nRetrieval receipt: ' in value, {'attempt_error':type(p._prefetch_attempt.error).__name__,'diagnostics':p._last_prefetch_diagnostics,'observations':observations[-30:]}
    r=json.loads(value.partition('\nRetrieval receipt: ')[2])
    assert r['final']['emitted_claim_count']==1
    join_attempt(p)
    assert p._transaction_quarantine is None and not p._conn.in_transaction

def test_entry_preparation_timeout_retains_one_worker_and_discards_late_result(recalled,monkeypatch):
    p=recalled;monkeypatch.setattr(wiki,'PREFETCH_DEADLINE_SECONDS',.12);monkeypatch.setattr(wiki,'PREFETCH_FALLBACK_RESERVE_SECONDS',.03)
    before=accounting(p);entered,release=threading.Event(),threading.Event();profile,fired=gate_call('_new_recall_request',entered,release)
    previous=threading.getprofile();threading.setprofile(profile)
    try:
        start=time.monotonic();assert p.prefetch(QUERY)=='';elapsed=time.monotonic()-start
        assert entered.is_set() and .09<=elapsed<.40
        a=p._prefetch_attempt;assert a.worker.is_alive() and p._prefetch_admission.locked()
        for _ in range(5):assert p.prefetch(QUERY)=='' and p._prefetch_attempt is a
        with pytest.raises(RuntimeError,match='provider_prefetch_worker_pending'):p.shutdown()
    finally:
        release.set();threading.setprofile(previous);join_attempt(p)
    assert accounting(p)==before and p._transaction_quarantine is None
    monkeypatch.setattr(wiki,'PREFETCH_DEADLINE_SECONDS',5.5)
    assert TEXT in p.prefetch(QUERY);join_attempt(p)

def test_real_sql_callback_can_outlive_waiter_without_second_shared_reader(recalled,monkeypatch):
    p=recalled;monkeypatch.setattr(wiki,'PREFETCH_DEADLINE_SECONDS',.12);monkeypatch.setattr(wiki,'PREFETCH_FALLBACK_RESERVE_SECONDS',.03);before=accounting(p)
    entered,release=threading.Event(),threading.Event();fired=[]
    def authorizer(action,a,b,database,trigger):
        if action==sqlite3.SQLITE_READ and a=='claims' and not fired:
            fired.append(True);entered.set();assert release.wait(3)
        return sqlite3.SQLITE_OK
    p._conn.set_authorizer(authorizer)
    try:
        start=time.monotonic();assert p.prefetch(QUERY)=='';assert time.monotonic()-start<.40 and entered.is_set()
        a=p._prefetch_attempt
        assert a.worker.is_alive() and p._prefetch_admission.locked()
        assert p.prefetch(QUERY)=='' and p._prefetch_attempt is a
    finally:
        release.set();join_attempt(p);p._conn.set_authorizer(None)
    assert accounting(p)==before and p._transaction_quarantine is None

def test_genuine_primary_boundary_failure_has_serial_nonempty_lexical_fallback(recalled):
    p=recalled;entered,release=threading.Event(),threading.Event();profile,fired=gate_call('_prefetch_impl',entered,release,raise_primary=True)
    previous=threading.getprofile();threading.setprofile(profile)
    try:value=p.prefetch(QUERY)
    finally:threading.setprofile(previous);join_attempt(p)
    assert fired and TEXT in value
    receipt=json.loads(value.partition('\nRetrieval receipt: ')[2])
    assert receipt['delivery_path']=='runtime_error_fallback' and receipt['final']['emitted_claim_count']==1

def test_fallback_consumes_original_total_deadline(recalled,monkeypatch):
    p=recalled;monkeypatch.setattr(wiki,'PREFETCH_DEADLINE_SECONDS',.12);monkeypatch.setattr(wiki,'PREFETCH_FALLBACK_RESERVE_SECONDS',.03);before=accounting(p)
    entered,release=threading.Event(),threading.Event();flags=[]
    def authorizer(action,a,b,database,trigger):
        if action==sqlite3.SQLITE_READ and a=='claims' and not flags:
            flags.append('fallback-native-read')
            names=[];frame=sys._getframe(1)
            for _ in range(32):
                if frame is None:break
                names.append(frame.f_code.co_name);frame=frame.f_back
            frame=None
            assert '_lexical_prefetch_fallback' in names
            entered.set();assert release.wait(3)
        return sqlite3.SQLITE_OK
    p._conn.set_authorizer(authorizer)
    observer,fired=gate_call('_prefetch_impl',threading.Event(),release,raise_primary=True)
    previous=threading.getprofile();threading.setprofile(observer)
    try:
        start=time.monotonic();assert p.prefetch(QUERY)==''
        assert time.monotonic()-start<.40 and entered.is_set() and fired
    finally:
        release.set();threading.setprofile(previous);join_attempt(p);p._conn.set_authorizer(None)
    assert accounting(p)==before and p._transaction_quarantine is None

def test_terminal_verification_timeout_rolls_back_fixed_accounting(recalled,monkeypatch):
    # Real default budget: short synthetic primary setup can consume .20 s
    # before this actual owned terminal seam. Keep that prior setup refusal;
    # reach the intended boundary instead of weakening the boundary assertion.
    p=recalled;before=accounting(p)
    entered,release=threading.Event(),threading.Event();profile,fired=gate_call('finish',entered,release,owned=True,wait_seconds=8)
    previous=threading.getprofile();threading.setprofile(profile)
    try:
        start=time.monotonic();assert p.prefetch(QUERY)=='';assert 5.3<=time.monotonic()-start<5.95
        assert entered.is_set() and p._prefetch_attempt.worker.is_alive()
    finally:
        release.set();threading.setprofile(previous);join_attempt(p)
    assert accounting(p)==before and not p._conn.in_transaction and p._transaction_quarantine is None

def test_original_actor_not_recaptured_after_entry_wait(recalled):
    p=recalled;old=p.bot_id;entered,release=threading.Event(),threading.Event();profile,fired=gate_call('_new_recall_request',entered,release)
    previous=threading.getprofile();threading.setprofile(profile)
    def withdraw():
        assert entered.wait(2);p.bot_id='foreign-withdrawn-actor';release.set()
    withdrawer=threading.Thread(target=withdraw,daemon=True);withdrawer.start()
    try:assert p.prefetch(QUERY)==''
    finally:
        release.set();threading.setprofile(previous);withdrawer.join(3);join_attempt(p);p.bot_id=old
    assert TEXT in p.prefetch(QUERY);join_attempt(p)

def test_late_native_authorizer_actor_withdrawal_refuses_before_commit(recalled):
    p=recalled;before=accounting(p);old=p.bot_id;seen=[]
    def authorizer(action,a,b,database,trigger):
        if action==sqlite3.SQLITE_TRANSACTION and a=='COMMIT':
            seen.append(True);p.bot_id='late-native-foreign'
        return sqlite3.SQLITE_OK
    p._conn.set_authorizer(authorizer)
    try:
        assert p.prefetch(QUERY)==''
    finally:join_attempt(p);p._conn.set_authorizer(None);p.bot_id=old
    assert seen and accounting(p)==before and not p._conn.in_transaction and p._transaction_quarantine is None

@pytest.mark.parametrize('kind',['trace','progress'])
def test_late_native_callback_lifetime_refused_without_disabling_guard(recalled,kind):
    p=recalled;before=accounting(p)
    if kind=='trace':p._conn.set_trace_callback(lambda statement:None)
    else:p._conn.set_progress_handler(lambda:0,1000)
    try:
        assert p.prefetch(QUERY)==''
    finally:
        join_attempt(p);p._conn.set_trace_callback(None);p._conn.set_progress_handler(None,0)
    assert accounting(p)==before and not p._conn.in_transaction and p._transaction_quarantine is None

def test_real_rollback_unknown_precludes_new_prefetch_worker(recalled):
    p=recalled
    def authorizer(action,a,b,database,trigger):
        return sqlite3.SQLITE_DENY if action==sqlite3.SQLITE_TRANSACTION and a=='ROLLBACK' else sqlite3.SQLITE_OK
    p._conn.set_authorizer(authorizer)
    primary=ValueError('owned-rollback-primary')
    try:
        with pytest.raises(ValueError) as caught:
            with p._claim_transaction() as c:
                c.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('owned-unknown','pending')")
                raise primary
        assert caught.value is primary and p._transaction_quarantine is p._conn
        old=p._prefetch_attempt;assert p.prefetch(QUERY)=='' and p._prefetch_attempt is old
    finally:p._conn.set_authorizer(None)
