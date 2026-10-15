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


# Review R1/R2/R3 composition controls. The prior 11 cases/assertions are intact.
def connection_accounting(conn):
    statements=('SELECT id,access_count,recall_count,last_recalled FROM claims ORDER BY id',
                'SELECT id,claim_id,used FROM recall_events ORDER BY id',
                'SELECT consumer_id,last_seen_revision FROM memory_consumers ORDER BY consumer_id')
    return tuple(tuple(tuple(r) for r in conn.execute(sql).fetchall()) for sql in statements)

@pytest.mark.parametrize('withdrawal',['lifecycle','owned_handle','erasure','policy','config','rollback_unknown'])
def test_native_authorizer_non_sql_authority_withdrawal_never_commits(recalled,withdrawal):
    p=recalled;c=p._conn;peer=sqlite3.connect(str(p.db_path),timeout=0)
    before=connection_accounting(peer);seen=[]
    old=(p._lifecycle_state,p._owned_conn,p._privacy_erasure)
    old_policy=os.environ.get('HERMES_SECURITY_STRICT');env_bytes=(p.home/'.env').read_bytes()
    def authorizer(action,a,b,database,trigger):
        if action==sqlite3.SQLITE_TRANSACTION and a=='COMMIT':
            seen.append(True)
            if withdrawal=='lifecycle':p._lifecycle_state='stopping'
            elif withdrawal=='owned_handle':p._owned_conn=None
            elif withdrawal=='erasure':p._privacy_erasure=None
            elif withdrawal=='policy':os.environ['HERMES_SECURITY_STRICT']='true'
            elif withdrawal=='config':(p.home/'.env').write_bytes(env_bytes+b'\n# owned-config-withdrawal\n')
            elif withdrawal=='rollback_unknown':p._owned_conn=None
        if withdrawal=='rollback_unknown' and action==sqlite3.SQLITE_TRANSACTION and a=='ROLLBACK':
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK
    c.set_authorizer(authorizer);value=None;error=None
    try:
        try:value=p.prefetch(QUERY)
        except RuntimeError as caught:error=caught
        a=join_attempt(p)
        assert seen
        assert value=='' or error is not None
        assert connection_accounting(peer)==before
        if withdrawal=='rollback_unknown':
            assert error is p._transaction_primary and error is a.error
            assert p._transaction_quarantine is c and p._claim_tx_connection is c
            assert c._prefetch_terminal is not None and c.in_transaction
            assert c._prefetch_terminal._prefetch_attempt is a
            assert p.prefetch(QUERY)=='' and p._prefetch_attempt is a
            with pytest.raises(RuntimeError):p._connect()
        else:assert error is None and not c.in_transaction and p._transaction_quarantine is None
    finally:
        c.set_authorizer(None);peer.close()
        p._lifecycle_state,p._owned_conn,p._privacy_erasure=old
        if old_policy is None:os.environ.pop('HERMES_SECURITY_STRICT',None)
        else:os.environ['HERMES_SECURITY_STRICT']=old_policy
        (p.home/'.env').write_bytes(env_bytes)


class OwnedCallerCancellation(BaseException):
    pass

@pytest.mark.parametrize('rollback_unknown',[False,True])
def test_caller_unwind_cancels_exact_prefetch_terminal_before_accounting(recalled,rollback_unknown):
    from agent.memory_provider import spawn_context_thread
    p=recalled;c=p._conn;peer=sqlite3.connect(str(p.db_path),timeout=0)
    before=connection_accounting(peer);entered,release=threading.Event(),threading.Event()
    primary=OwnedCallerCancellation('owned-caller-unwind');caught=[];witness=[]
    def authorizer(action,a,b,database,trigger):
        return sqlite3.SQLITE_DENY if rollback_unknown and action==sqlite3.SQLITE_TRANSACTION and a=='ROLLBACK' else sqlite3.SQLITE_OK
    if rollback_unknown:c.set_authorizer(authorizer)
    def profile(frame,event,arg):
        if event!='call':return
        current=threading._active.get(threading.get_ident())
        if current is None:return
        delivery=frame.f_locals.get('_delivery')
        if (current.name=='memory-wiki-prefetch-owner' and frame.f_code.co_name=='finish'
                and delivery is not None and delivery.phase=='verify' and not witness):
            witness.append({'phase':delivery.phase,'after_changes':c.total_changes,'owned_changes':delivery.delta})
            entered.set();assert release.wait(8)
        if (current.name=='owned-prefetch-caller-unwind' and frame.f_code.co_name=='wait'
                and p._prefetch_attempt is not None and frame.f_locals.get('self') is p._prefetch_attempt.done):
            assert entered.wait(3),'owned-verify-seam-not-reached'
            raise primary
    def caller():
        try:p.prefetch(QUERY)
        except BaseException as error:caught.append(error)
    previous=threading.getprofile();threading.setprofile(profile)
    caller_thread=spawn_context_thread(caller,name='owned-prefetch-caller-unwind',daemon=False)
    caller_thread.start()
    try:
        caller_thread.join(4)
        assert not caller_thread.is_alive() and caught==[primary]
        a=p._prefetch_attempt
        assert entered.is_set() and witness and a.worker.is_alive() and p._prefetch_admission.locked()
        cancel_when_caller_left=a.cancel.is_set()
        assert p.prefetch(QUERY)=='' and p._prefetch_attempt is a
    finally:
        release.set();threading.setprofile(previous);caller_thread.join(3);a=join_attempt(p)
    try:
        assert cancel_when_caller_left,'waiting caller BaseException did not withdraw original worker attempt'
        assert connection_accounting(peer)==before
        if rollback_unknown:
            assert p._transaction_quarantine is c and p._transaction_primary is a.error
            assert c._prefetch_terminal is not None and c._prefetch_terminal._prefetch_attempt is a
            assert p._claim_tx_connection is c and c.in_transaction
            assert c._prefetch_terminal.phase=='verify'
            assert p.prefetch(QUERY)=='' and p._prefetch_attempt is a
            with pytest.raises(RuntimeError):p._connect()
        else:
            assert p._transaction_quarantine is None and not c.in_transaction
            assert c._prefetch_terminal is None
            assert TEXT in p.prefetch(QUERY);join_attempt(p)
    finally:
        c.set_authorizer(None);peer.close()


def test_healthy_empty_primary_publishes_new_diagnostic_without_ack(recalled):
    p=recalled
    assert TEXT in p.prefetch(QUERY);join_attempt(p)
    old=dict(p._last_prefetch_diagnostics)
    # The authored row is pinned, so a different query alone is not an empty
    # oracle. Make the owned fixture genuinely ineligible, preserving its row.
    with p._claim_transaction() as conn:
        conn.execute("UPDATE claims SET status='archived' WHERE id='c_prefetch_owned'")
    before_ack=tuple(tuple(r) for r in p._conn.execute('SELECT consumer_id,last_seen_revision FROM memory_consumers ORDER BY consumer_id'))
    value=p.prefetch('zqxwvn unrecalled botanical zephyr');join_attempt(p)
    assert value==''
    current=p._last_prefetch_diagnostics
    assert current.get('status')=='empty' and current.get('rendered')==0
    assert current.get('recall_trace_id') and current['recall_trace_id']!=old['recall_trace_id']
    assert tuple(tuple(r) for r in p._conn.execute('SELECT consumer_id,last_seen_revision FROM memory_consumers ORDER BY consumer_id'))==before_ack


def test_benign_native_user_authorizer_reader_supported_terminal_explicitly_refused(recalled):
    p=recalled;before=accounting(p);actions=[]
    def authorizer(action,a,b,database,trigger):
        actions.append((action,a));return sqlite3.SQLITE_OK
    p._conn.set_authorizer(authorizer)
    try:
        assert p.prefetch(QUERY)=='';join_attempt(p)
        assert p._conn._graph_user_authorizer is authorizer
        assert any(action==sqlite3.SQLITE_TRANSACTION and a=='COMMIT' for action,a in actions)
        assert accounting(p)==before and not p._conn.in_transaction
        # Refusal is only the new critical prefetch lifetime, not a disabled
        # user guard or blanket no-memory replacement of other public readers.
        result=json.loads(p.handle_tool_call('memory_wiki_query',{'query':QUERY,'limit':5}))
        assert any(row.get('claim')==TEXT for row in result.get('claims',[]))
    finally:p._conn.set_authorizer(None)


@pytest.mark.parametrize('boundary',['deadline','prepared_error','original_config_withdrawal'])
def test_prepared_primary_to_serial_fallback_preserves_original_admission(recalled,monkeypatch,boundary):
    p=recalled;before=connection_accounting(p._conn);before_diag=dict(p._last_prefetch_diagnostics)
    env_path=p.home/'.env';env_bytes=env_path.read_bytes();witness=[];fallback=[]
    # Same default total; only the supported reserve1.0 is chosen for this
    # elapsed subdeadline positive. No clock/SDK/callable replacement.
    if boundary=='deadline':monkeypatch.setattr(wiki,'PREFETCH_FALLBACK_RESERVE_SECONDS',1.0)
    def profile(frame,event,arg):
        current=threading._active.get(threading.get_ident())
        if current is None or current.name!='memory-wiki-prefetch-owner':return

        if event!='return' or frame.f_code.co_name!='_prefetch_impl' or witness:return
        delivery=frame.f_locals.get('_delivery')
        if not isinstance(delivery,dict) or type(arg) is not str or TEXT not in arg:return
        assert delivery.get('fence') is not None and len(delivery['rows'])==1
        witness.append((threading.get_ident(),id(p._conn),id(delivery['fence'])))
        if boundary=='deadline':
            wait=wiki._prefetch_time_remaining()+.025
            assert 0<wait<5.5
            threading.Event().wait(wait)
        else:
            if boundary=='original_config_withdrawal':env_path.write_bytes(env_bytes+b'\n# owned-primary-authority-withdrawal\n')
            raise TimeoutError('owned-prepared-primary-refusal')
    def trace(frame,event,arg):
        current=threading._active.get(threading.get_ident())
        if (current is not None and current.name=='memory-wiki-prefetch-owner'
                and event=='call' and frame.f_code.co_name=='_lexical_prefetch_fallback'):
            fallback.append((threading.get_ident(),id(p._conn),frame.f_locals.get('reason')))
        return None
    old_trace=threading.gettrace();threading.settrace(trace)
    old_profile=threading.getprofile();threading.setprofile(profile)
    try:
        started=time.monotonic();value=p.prefetch(QUERY);elapsed=time.monotonic()-started;join_attempt(p)
        print(json.dumps({'boundary':boundary,'elapsed':elapsed,'prepared':bool(witness),'fallback':fallback,'value_chars':len(value),'attempt_error':type(p._prefetch_attempt.error).__name__,'cancel':p._prefetch_attempt.cancel.is_set()},ensure_ascii=False))
        assert witness and fallback
        assert witness[0][:2]==fallback[0][:2]
        assert fallback[0][2]==('deadline' if boundary=='deadline' else 'network_or_runtime_error')
        assert elapsed<5.5
        if boundary=='original_config_withdrawal':
            assert value=='' and connection_accounting(p._conn)==before
            assert p._last_prefetch_diagnostics==before_diag
        else:
            assert TEXT in value
            receipt=json.loads(value.partition('\nRetrieval receipt: ')[2])
            assert receipt['delivery_path']==('deadline_fallback' if boundary=='deadline' else 'runtime_error_fallback')
            assert receipt['final']['emitted_claim_count']==1
            # Legacy lexical fallback prepares disclosure/diagnostics, not
            # primary recall-count/event or revision ACK. Do not transfer the
            # rejected primary's pending accounting to this narrower output.
            after=connection_accounting(p._conn)
            assert after[:2]==before[:2]
            prior_consumers=dict(before[2])
            assert all(seen==prior_consumers.get(consumer,0) for consumer,seen in after[2])
        assert not p._conn.in_transaction and p._transaction_quarantine is None
    finally:
        threading.setprofile(old_profile);threading.settrace(old_trace);env_path.write_bytes(env_bytes)


def test_healthy_primary_keeps_canonical_path_with_earlier_cutoff(recalled):
    p=recalled;value=p.prefetch(QUERY);join_attempt(p)
    assert TEXT in value
    receipt=json.loads(value.partition('\nRetrieval receipt: ')[2])
    assert receipt['delivery_path']=='canonical'
    assert receipt['final']['emitted_claim_count']==1
    assert not p._conn.in_transaction and p._transaction_quarantine is None


@pytest.mark.parametrize('token_name',['_PREFETCH_ATTEMPT','_REQUEST_HOME'])
@pytest.mark.parametrize('base_exception',[False,True])
def test_prefetch_worker_context_setup_failure_releases_finished_owner(recalled,token_name,base_exception):
    p=recalled;before=accounting(p);caller_home=wiki._REQUEST_HOME.get()
    target=getattr(wiki,token_name)
    class OwnedContextSetupAbort(BaseException):pass
    error=(OwnedContextSetupAbort if base_exception else RuntimeError)('owned-context-setup-refusal')
    fired=[];returned=[];prior=threading.getprofile();prior_trace=threading.gettrace()
    def refuse(frame,event,arg):
        if (not fired and event=='c_call' and frame.f_code is wiki._PrefetchAttempt.run.__code__
                and getattr(arg,'__self__',None) is target and getattr(arg,'__name__','')=='set'
                and threading.current_thread().name=='memory-wiki-prefetch-owner'):
            fired.append({'thread':threading.get_ident(),'token':token_name})
            raise error
    def observe_return(frame,event,arg):
        # CPython disables a profile callback that raises. A separate passive
        # trace witnesses cleanup in the worker, not just the caller context.
        if frame.f_code is wiki._PrefetchAttempt.run.__code__ and event=='return':
            returned.append((wiki._PREFETCH_ATTEMPT.get(),wiki._REQUEST_HOME.get()))
        return observe_return
    threading.setprofile(refuse);threading.settrace(observe_return)
    try:
        with pytest.raises(type(error),match='owned-context-setup-refusal') as caught:
            p.prefetch(QUERY)
    finally:threading.setprofile(prior);threading.settrace(prior_trace)
    assert caught.value is error and len(fired)==1
    attempt=join_attempt(p)
    assert attempt.error is error and attempt.cancel.is_set() and attempt.value==''
    assert returned==[(None,caller_home)]
    assert wiki._REQUEST_HOME.get()==caller_home and wiki._PREFETCH_ATTEMPT.get() is None
    assert accounting(p)==before and not p._conn.in_transaction and p._transaction_quarantine is None
    # A known finished, side-effect-free worker must not permanently consume
    # the only slot. UNKNOWN native-start/rollback ownership is NOT released.
    value=p.prefetch(QUERY);recovered=join_attempt(p)
    assert recovered is not attempt and TEXT in value
    assert json.loads(value.partition('\nRetrieval receipt: ')[2])['delivery_path']=='canonical'
