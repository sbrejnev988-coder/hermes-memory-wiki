"""Two linked counterexamples; real native provider/guard/SQLite/JobStore only."""
from __future__ import annotations
import contextlib
import json
import time
import unittest
from test_observation_finite_work import (
    wiki, jobs, observations, provider as base_provider, capture, enqueue, row, worker, wait,
    Overrides, FIXTURE, raises,
)

DETAILS={}

@contextlib.contextmanager
def provider(*a, **kw):
    with base_provider(*a, **kw) as p:
        yield p
        connection=p._conn
    if connection is not None:
        import sqlite3
        with raises(sqlite3.ProgrammingError):connection.execute('SELECT 1')
        DETAILS['native_provider_closes_verified']=DETAILS.get('native_provider_closes_verified',0)+1

class Repair01Tests(unittest.TestCase):
    def setUp(self):
        self.overrides=Overrides()
        self.addCleanup(self.overrides.close)

    def test_support_budget_and_fresh_admission(self):
        m=self.overrides
        m.setenv('MEMORY_WIKI_OBSERVATION_BACKGROUND_SECONDS','.05')
        m.setenv('MEMORY_WIKI_OBSERVATION_BACKGROUND_BATCH','64')
        m.setenv('MEMORY_WIKI_OBSERVATION_RETRY_BASE_SECONDS','1')
        m.setenv('MEMORY_WIKI_BACKGROUND_POLL_SECONDS','1')
        native=wiki.MemoryWikiProvider._inspect_recall_text
        reports=[]; calls=[]; action={'mode':'','ids':[], 'fired':False}
        consolidate=observations.consolidate_events
        def record(*a,**kw):
            result=consolidate(*a,**kw); reports.append(result); return result
        def delayed(self,text,**kw):
            result=native(self,text,**kw)
            if kw.get('source')=='observation:event_evidence':
                event=kw['item_id']; calls.append(event)
                time.sleep(.03)  # Real elapsed time; production budget/clock unchanged.
                if action['mode']=='guard' and event==action['trigger']:
                    return {'status':'blocked','content':''}  # Explicit test-only admission denial.
                if action['mode'] in {'source','policy','lease'} and event==action['trigger'] and not action['fired']:
                    action['fired']=True
                    if action['mode']=='source':
                        self._connect().execute('DELETE FROM memory_events WHERE event_id=?',(action['ids'][0],))
                    elif action['mode']=='policy':
                        import os
                        os.environ['MEMORY_WIKI_OBSERVATIONS_ENABLED']='0'
                    else:
                        self._connect().execute("UPDATE memory_jobs SET lease_owner='synthetic-revoked' WHERE job_id=?",(action['job'],))
            return result
        m.setattr(wiki.MemoryWikiProvider,'_inspect_recall_text',delayed)
        m.setattr(observations,'consolidate_events',record)
        home=FIXTURE/'support'
        subcases=[]
        for mode in ['positive','guard','source','policy','lease','privacy']:
            action.update(mode='',ids=[],fired=False)
            with self.subTest(mode=mode):
                bot='synthetic-repair01-'+mode
                with provider('support-'+mode,bot=bot,home=home) as p:
                    ids=capture(p,2,text='Synthetic fixture: the '+mode+' exhibit contains a copper telescope.')
                    ident=enqueue(p,ids[-1]); payload=row(p,ident)['payload_json']
                    start=len(reports)
                    assert jobs.run_once(p,wiki)
                    first=reports[-1]
                    assert first['events_linked']==2 and first['budget_exhausted']
                    assert first['versions_created']==0 and first['support_events_deferred']==1
                    old=p._connect().execute('SELECT observation_id FROM memory_observation_events WHERE event_id=?',(ids[0],)).fetchone()[0]
                    assert row(p,ident)['status']=='pending' and row(p,ident)['attempts']==0
                    assert p._connect().execute('SELECT COUNT(*) FROM memory_observation_versions WHERE observation_id=?',(old,)).fetchone()[0]==0
                    if mode=='privacy':
                        with p._connect() as c:c.execute('DELETE FROM memory_events WHERE event_id=?',(ids[0],))
                        assert not c.execute('SELECT 1 FROM memory_observations WHERE observation_id=?',(old,)).fetchone()
                # Actual close/reopen, same durable sources/decisions/job; no re-enqueue.
                with provider('support-'+mode,bot=bot,home=home) as p:
                    assert row(p,ident)['payload_json']==payload and row(p,ident)['generation']==1
                    wait(lambda:int(time.time())>=row(p,ident)['available_at'],seconds=4)
                    before=len(calls)
                    ordered=sorted(ids,key=lambda i: tuple(p._connect().execute('SELECT occurred_at,observed_at,created_at,event_id FROM memory_events WHERE event_id=?',(i,)).fetchone()) if i!=ids[0] or mode!='privacy' else ())
                    action.update(mode=mode,ids=ids,job=ident,trigger=ordered[-1])
                    assert jobs.run_once(p,wiki)
                    c=p._connect()
                    if mode=='positive':
                        assert row(p,ident)['status']=='done'
                        assert calls[before:]==sorted(ids,key=lambda i: tuple(c.execute('SELECT occurred_at,observed_at,created_at,event_id FROM memory_events WHERE event_id=?',(i,)).fetchone()))
                        version=c.execute('SELECT support_count FROM memory_observation_versions WHERE observation_id=?',(old,)).fetchone()
                        assert version and version[0]==2
                        assert c.execute('SELECT COUNT(*) FROM memory_observation_event_retries WHERE event_id IN (?,?)',ids).fetchone()[0]==0
                        assert jobs.JobStore(p.db_path,jobs.profile_key(p),jobs.owner_key(p)).health()['jobs_today']==2
                    elif mode=='privacy':
                        # A clean rebuild may reuse its surviving-source-derived
                        # observation ID. Prove erasure by evidence, not UUID luck.
                        version=c.execute('SELECT v.support_count FROM memory_observation_versions v JOIN memory_observation_version_events e ON e.version_id=v.version_id WHERE e.event_id=?',(ids[1],)).fetchone()
                        assert version and version[0]==1
                        assert not c.execute('SELECT 1 FROM memory_observation_version_events WHERE event_id=?',(ids[0],)).fetchone()
                        assert not c.execute('SELECT 1 FROM memory_events WHERE event_id=?',(ids[0],)).fetchone()
                    else:
                        assert c.execute('SELECT COUNT(*) FROM memory_observation_versions WHERE observation_id=?',(old,)).fetchone()[0]==0
                        if mode=='guard':
                            assert c.execute('SELECT outcome FROM memory_observation_event_decisions WHERE event_id=?',(action['trigger'],)).fetchone()[0]=='rejected'
                            assert not c.execute('SELECT 1 FROM memory_observations WHERE observation_id=?',(old,)).fetchone()
                        else:
                            assert row(p,ident)['status']=='pending'
                        if mode=='source':
                            assert action['fired'] and not c.execute('SELECT 1 FROM memory_events WHERE event_id=?',(ids[0],)).fetchone()
                        if mode=='lease':
                            assert action['fired'] and row(p,ident)['last_error_code']=='timeout'
                            assert c.execute('SELECT 1 FROM memory_observation_event_retries WHERE event_id IN (?,?)',ids).fetchone()
                        assert len(calls)-before==2, 'revocation must follow the first fresh support admission'
                    if mode=='policy':
                        m.setenv('MEMORY_WIKI_OBSERVATIONS_ENABLED','1')
                        action['mode']=''
                        with worker(p):wait(lambda:row(p,ident)['status']=='done',seconds=6)
                        assert c.execute('SELECT support_count FROM memory_observation_versions WHERE observation_id=?',(old,)).fetchone()[0]==2
                    assert c.execute('SELECT COUNT(*) FROM memory_jobs WHERE owner_key=?',(jobs.owner_key(p),)).fetchone()[0]==1
                    subcases.append({'mode':mode,'passes':len(reports)-start,'status':row(p,ident)['status'],
                                     'version_for_original':bool(c.execute('SELECT 1 FROM memory_observation_versions WHERE observation_id=?',(old,)).fetchone()),
                                     'guard_calls_in_retry':len(calls)-before,'generation':row(p,ident)['generation']})
        DETAILS['L1']={'budget_seconds':.05,'callback_delay_seconds':.03,'supports':2,
                       'subcases':subcases,'approval_cache':False,'unchanged_reopen_positive':True}

    def test_missing_pointer_partition_before_limit(self):
        m=self.overrides
        m.setenv('MEMORY_WIKI_OBSERVATION_BACKGROUND_SECONDS','5')
        m.setenv('MEMORY_WIKI_OBSERVATION_BACKGROUND_BATCH','64')
        with provider('replacement',bot='synthetic-repair01-L2') as p:
            p.project_scope='synthetic-project-A'
            own=capture(p,3)
            ident=enqueue(p,own[-1]); original=row(p,ident)
            p.project_scope='synthetic-project-B'
            foreign=capture(p,129,text='Synthetic fixture: project B has a silver microscope.')
            foreign.append(wiki._memory_events.capture_event(p,wiki,'Synthetic project B visibility fixture.',
                role='user',event_type='dialogue_turn',session_id=p.session_id,scope='project',
                turn_id='synthetic-project-scope',provenance={'source':'authored:G2-repair01'}))
            assert foreign[-1]
            c=p._connect()
            peers={i:tuple(c.execute('SELECT * FROM memory_events WHERE event_id=?',(i,)).fetchone()) for i in foreign}
            with c:c.execute('DELETE FROM memory_events WHERE event_id=?',(own[-1],))
            # The current provider project is B; only retained metadata/digest may select A.
            source=jobs._event_source(p,row(p,ident),json.loads(original['payload_json']))
            assert source and source['event_id'] in own[:-1] and source['project_id']=='synthetic-project-A'
            assert jobs.partition_key(source)==original['partition_key']
            for project in ['',0,None]:
                value={'owner_bot_id':'bot','owner_chat_hash':'chat','owner_session_hash':'session','visibility_scope':'chat','project_id':project}
                actual=c.execute('SELECT memory_wiki_job_partition(?,?,?,?,?)',tuple(value.values())).fetchone()[0]
                assert actual==jobs.partition_key(value)
            wrong=dict(original,profile_key='0'*64)
            assert jobs._event_source(p,wrong,json.loads(original['payload_json'])) is None
            assert jobs.run_once(p,wiki)
            assert row(p,ident)['status']=='done'
            assert row(p,ident)['payload_json']==original['payload_json'] and row(p,ident)['generation']==1
            assert c.execute('SELECT COUNT(*) FROM memory_observation_event_decisions WHERE event_id IN (?,?)',own[:-1]).fetchone()[0]==2
            assert c.execute('SELECT support_count FROM memory_observation_versions').fetchone()[0]==2
            assert all(tuple(c.execute('SELECT * FROM memory_events WHERE event_id=?',(i,)).fetchone())==peers[i] for i in foreign)
            assert not any(c.execute('SELECT 1 FROM memory_observation_event_decisions WHERE event_id=?',(i,)).fetchone() for i in foreign)
            assert not c.execute('SELECT 1 FROM memory_events WHERE event_id=?',(own[-1],)).fetchone()
            p.project_scope='synthetic-empty-project'
            erased=capture(p,1,text='Synthetic fixture: intentionally erased only pointer.')[0]
            missing=enqueue(p,erased)
            extraction=jobs.enqueue_event(p,'extract_session_events',erased)
            assert extraction
            with c:c.execute('DELETE FROM memory_events WHERE event_id=?',(erased,))
            before=row(p,missing)['payload_json']
            assert jobs.run_once(p,wiki)
            assert jobs.run_once(p,wiki)
            assert row(p,missing)['status']=='pending' and row(p,missing)['attempts']==0
            assert row(p,extraction)['status']=='pending' and row(p,extraction)['attempts']==0
            assert row(p,missing)['payload_json']==before
            assert not c.execute('SELECT 1 FROM memory_events WHERE event_id=?',(erased,)).fetchone()
            DETAILS['L2']={'newer_foreign_rows':len(foreign),'retained_A_processed':2,
                'foreign_rows_unchanged':True,'original_pointer_recreated':False,
                'partition_digest_equal':True,'legacy_str_semantics_verified':['empty','0','None'],
                'missing_source_outcome':row(p,missing)['status'],'profile_mismatch_refused':True,
                'unproven_extraction_pointer_outcome':row(p,extraction)['status']}
