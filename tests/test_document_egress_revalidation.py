"""Original document fence at source adapter handoff; authored SQLite/HTTP inputs.

Runs genuine provider/registry/trust classes. Not real model/network or atomic OS
revocation. The reused complete helper is shipped alongside this file.
"""
import importlib.util
import json
import sqlite3
import sys
import threading
import pytest
from pathlib import Path
from contextlib import contextmanager

spec=importlib.util.spec_from_file_location('document_egress_owned_fixture',Path(__file__).parent/'ci_owned/document_egress_fixture.py')
fmod=importlib.util.module_from_spec(spec);sys.modules[spec.name]=fmod;spec.loader.exec_module(fmod)
ri_r03_case=fmod.ri_r03_case
Fixture=fmod.Fixture
MARKER='CANARY_KITE_OWN'
SOURCE_ID='sc2-source'

def seed(f):
    f.semantic_enabled=False
    f.m._embedding_cache_state()  # genuine existing monotonic owner state before admission
    for i in range(3):
        cid='sc2-claim-'+str(i)
        f.claim(cid,text=fmod.QUERY+' '+fmod.SAFE)
        f.document(SOURCE_ID,cid,text=MARKER+' '+fmod.QUERY+' '+fmod.SAFE)
    f.connectors([(SOURCE_ID,'bot-own','active')]);f.ready()

def public(f):
    return json.loads(f.p.handle_tool_call('memory_wiki_document_query',{'query':fmod.QUERY,'source_id':SOURCE_ID,'limit':12}))

def changed(f,action):
    if action=='session':
        before=f.p.session_id;f.p.on_session_switch('different-session',reset=False)
        assert before!=f.p.session_id
        return
    if action=='generation':
        f.m._embedding_cache_clear()
        return
    writer=sqlite3.connect(str(f.path))
    try:
        if action=='owner':writer.execute("UPDATE external_sources SET owner_bot_id='foreign-owner' WHERE document_source_id=?",(SOURCE_ID,))
        else:
            writer.execute("UPDATE external_sources SET status='disabled' WHERE document_source_id=?",(SOURCE_ID,))
            if action=='ABA':writer.execute("UPDATE external_sources SET status='active' WHERE document_source_id=?",(SOURCE_ID,))
        writer.commit()
    finally:writer.close()
    row=f.conn.execute('SELECT owner_bot_id,status FROM external_sources WHERE document_source_id=?',(SOURCE_ID,)).fetchone()
    assert tuple(row)==(('foreign-owner','active') if action=='owner' else ('bot-own','active' if action=='ABA' else 'disabled'))

@contextmanager
def schedule(f,seam,action):
    rank_code=fmod.unwrapped(type(f.p)._rerank_rows).__code__
    if seam=='before_rank':
        target=next(c for c in f.doc.query_documents.__code__.co_consts if hasattr(c,'co_name') and c.co_name=='present_candidate')
    elif seam=='bytes':target=f.io.request_bytes.__code__
    elif seam=='response':target=f.io.response_json.__code__
    elif seam in {'cache','tail'}:target=f.m._stage_receipt.__code__
    else:raise AssertionError('unknown_scheduled_seam')
    before=sys.getprofile();seen=[]
    def inject(frame,event,arg):
        if event=='return' and frame.f_code is target and not seen:
            loc=frame.f_locals
            match=(seam=='before_rank' or
                   seam in {'bytes','response'} and frame.f_back is not None and frame.f_back.f_code is rank_code or
                   seam in {'cache','tail'} and loc.get('stage')=='rerank' and loc.get('status')==('cache_hit' if seam=='cache' else 'executed'))
            if match:
                if seam=='tail':
                    assert len(rank_state(f)['cache'])==1,'tail_not_after_actual_cache_store'
                changed(f,action);seen.append((seam,action));f._emit({'event':'scheduled_original_authority_change','seam':seam,'action':action,'calls':dict(f.calls)})
        if before is not None:before(frame,event,arg)
    sys.setprofile(inject)
    try:yield seen
    finally:sys.setprofile(before)

def assert_withheld(f,payload,seen,*,rank_count):
    f._emit({'event':'pre_assert_egress_observation','mutation_seen':bool(seen),'calls':dict(f.calls),'sent_marker':any(MARKER in text for docs in f.rank_documents for text in docs),'final_results':len(payload.get('results',[])),'withheld':payload.get('disclosure')=='withheld' or payload.get('disclosure_status')=='withheld'})
    assert seen,'scheduled_change_not_reached'
    assert f.calls['rank']==rank_count,'revoked_document_body_reached_rank_transport'
    assert not payload.get('results'),'revoked_document_rows_published'
    assert payload.get('disclosure')=='withheld' or payload.get('disclosure_status')=='withheld'

def test_sc2_healthy(ri_r03_case):
    with Fixture('sc2-healthy') as f:
        seed(f);out=public(f)
        assert f.calls['rank']==1 and any(MARKER in text for docs in f.rank_documents for text in docs)
        assert {r['source_id'] for r in out['results']}=={SOURCE_ID}
        assert f.calls['rerank_body']==1 and not out.get('error')
        assert_request_accounting(f,1)

def test_sc2_disabled_initial(ri_r03_case):
    with Fixture('sc2-initial') as f:
        seed(f);changed(f,'status');out=public(f)
        assert f.calls['rank']==0 and not out.get('results')

def test_sc2_late_status_before_rank(ri_r03_case):
    with Fixture('sc2-early-status') as f:
        seed(f)
        with schedule(f,'before_rank','status') as seen:out=public(f)
        assert_withheld(f,out,seen,rank_count=0);assert f.calls['rerank_body']==0

def test_sc2_late_status_before_http(ri_r03_case):
    with Fixture('sc2-late-status') as f:
        seed(f)
        with schedule(f,'bytes','status') as seen:out=public(f)
        assert_withheld(f,out,seen,rank_count=0);assert f.calls['rerank_body']==1
        assert_request_accounting(f,0)

def test_sc2_late_owner_before_http(ri_r03_case):
    with Fixture('sc2-late-owner') as f:
        seed(f)
        with schedule(f,'bytes','owner') as seen:out=public(f)
        assert_withheld(f,out,seen,rank_count=0)

def test_sc2_sql_ABA_before_http(ri_r03_case):
    with Fixture('sc2-late-ABA') as f:
        seed(f)
        with schedule(f,'bytes','ABA') as seen:out=public(f)
        assert_withheld(f,out,seen,rank_count=0)

def test_sc2_session_before_http(ri_r03_case):
    with Fixture('sc2-late-session') as f:
        seed(f)
        with schedule(f,'bytes','session') as seen:out=public(f)
        assert_withheld(f,out,seen,rank_count=0)

def test_sc2_generation_before_http(ri_r03_case):
    with Fixture('sc2-late-generation') as f:
        seed(f)
        with schedule(f,'bytes','generation') as seen:out=public(f)
        assert_withheld(f,out,seen,rank_count=0)

def test_sc2_cache_healthy(ri_r03_case):
    with Fixture('sc2-cache-healthy',cache_ttl=60) as f:
        seed(f);first=public(f);second=public(f)
        assert first.get('results') and second.get('results')
        assert [r['id'] for r in first['results']]==[r['id'] for r in second['results']]
        assert f.calls['rank']==1 and any(s.get('status')=='cache_hit' for s in f.stages)

def test_sc2_cache_late_revoke(ri_r03_case):
    with Fixture('sc2-cache-revoke',cache_ttl=60) as f:
        seed(f);assert public(f).get('results')
        with schedule(f,'cache','status') as seen:out=public(f)
        assert_withheld(f,out,seen,rank_count=1)

def test_sc2_response_revoke(ri_r03_case):
    with Fixture('sc2-response-revoke',cache_ttl=60) as f:
        seed(f)
        with schedule(f,'response','status') as seen:out=public(f)
        assert_withheld(f,out,seen,rank_count=1)
        cache=f.m._rerank_scope_state(f.m._rerank_settings())['cache']
        assert not cache,'revoked_response_entered_rank_cache'
        assert_request_accounting(f,1)


def rank_state(f):
    return f.m._rerank_scope_state(f.m._rerank_settings())


def assert_request_accounting(f, expected):
    assert f.m._HYBRID_WORK.get() is None,'optional_hybrid_collector_not_absent'
    state=rank_state(f)
    assert state['stats']['requests']==expected==f.calls['rank'],'received_request_not_counted_once'
    assert state['stats']['failures']==state['failure_count']==0,'admission_refusal_poisoned_circuit'


class AuthoredAbort(BaseException):
    pass


def abort_observer_probe():
    return None


@contextmanager
def abort_last_fence(f, *, replace=False):
    # Throw only at the genuine original fence after actual store/receipt. The
    # independent CALL-only trace survives CPython disabling the raising profile.
    stage_code=f.m._stage_receipt.__code__
    fence_code=f.m._DisclosureFence.finish.__code__
    thread_id=threading.get_ident()
    previous_profile=sys.getprofile();previous_trace=sys.gettrace()
    assert previous_trace is None,'existing_trace_not_replaced'
    proof={'primary':AuthoredAbort('authored-final-fence-abort'),'armed':False,
           'injected':False,'observer_calls':0,'observer_errors':[], 'replacement':None}
    probe_code=abort_observer_probe.__code__
    def observe(frame,event,arg):
        try:
            if event=='call' and frame.f_code is probe_code:
                proof['observer_calls']+=1
        except BaseException as exc:
            proof['observer_errors'].append(type(exc).__name__)
        return None
    def inject(frame,event,arg):
        if threading.get_ident()==thread_id:
            loc=frame.f_locals
            if event=='return' and frame.f_code is stage_code and loc.get('stage')=='rerank' and loc.get('status')=='executed':
                assert len(rank_state(f)['cache'])==1,'abort_seam_not_after_cache_store'
                proof['armed']=True
            if event=='call' and frame.f_code is fence_code and proof['armed'] and not proof['injected'] and loc.get('self').provider is f.p:
                state=rank_state(f)
                with f.m._RERANK_LOCK:
                    assert len(state['cache'])==1
                    if replace:
                        key=next(iter(state['cache']));old=state['cache'][key]
                        replacement=(old[0],list(old[1]))
                        assert replacement is not old
                        state['cache'][key]=replacement
                        proof['replacement']=replacement
                proof['injected']=True
                f._emit({'event':'authored_final_fence_abort','after_real_store':True,'newer_replacement':replace})
                raise proof['primary']
        if previous_profile is not None:previous_profile(frame,event,arg)
    sys.settrace(observe);sys.setprofile(inject)
    try:
        yield proof
    finally:
        sys.setprofile(previous_profile);sys.settrace(previous_trace)


def test_sc2_tail_false_discards_cache(ri_r03_case):
    with Fixture('sc2-tail-false',cache_ttl=60) as f:
        seed(f)
        with schedule(f,'tail','status') as seen:out=public(f)
        assert_withheld(f,out,seen,rank_count=1)
        assert not rank_state(f)['cache'],'withheld_tail_retained_own_cache_entry'
        assert_request_accounting(f,1)


def test_sc2_tail_baseexception_discards_cache(ri_r03_case):
    with Fixture('sc2-tail-abort',cache_ttl=60) as f:
        seed(f)
        with abort_last_fence(f) as proof:
            with pytest.raises(AuthoredAbort) as caught:public(f)
            assert caught.value is proof['primary'],'original_primary_identity_lost'
            abort_observer_probe()
            assert proof['injected'] and proof['observer_calls']==1 and not proof['observer_errors']
            assert not rank_state(f)['cache'],'aborted_tail_retained_own_cache_entry'
            assert_request_accounting(f,1)


def test_sc2_tail_baseexception_preserves_replacement(ri_r03_case):
    with Fixture('sc2-tail-newer',cache_ttl=60) as f:
        seed(f)
        with abort_last_fence(f,replace=True) as proof:
            with pytest.raises(AuthoredAbort) as caught:public(f)
            assert caught.value is proof['primary'],'original_primary_identity_lost'
            abort_observer_probe()
            assert proof['injected'] and proof['observer_calls']==1 and not proof['observer_errors']
            values=list(rank_state(f)['cache'].values())
            assert len(values)==1 and values[0] is proof['replacement'],'newer_cache_entry_wrongly_removed'
            assert_request_accounting(f,1)
