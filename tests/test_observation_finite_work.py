"""G2: authored synthetic events through real provider/migration/queue workers.

No extraction/model boundary is exercised, and no candidate/review approval is
forged. Injection wrappers delegate the actual plugin guard except for explicit
one-shot dependency refusals. SDK and public trust-core classes are untouched.
"""
from __future__ import annotations
import contextlib
import json
import os
import sqlite3
import threading
import time
from pathlib import Path

import unittest
from unittest.mock import patch
import memory_wiki as wiki
from agent.memory_provider import MemoryProvider
from agent import secret_scope
import hermes_constants

jobs = wiki._background_jobs
observations = wiki._memory_observations
# The native cold lane supplies a synthetic TMPDIR; never use a profile store.
FIXTURE = Path(os.environ.get('WIKI_G2_FIXTURE') or
               (Path(os.environ['TMPDIR']) / ('wiki-g2-' + str(os.getpid()))))
DETAILS = {}


class Overrides:
    """Owned test-only environment/plugin injection; never patches the SDK."""
    def __init__(self):
        self.stack=contextlib.ExitStack()
    def setenv(self,name,value):
        self.stack.enter_context(patch.dict(os.environ,{name:value}))
    def setattr(self,obj,name,value):
        self.stack.enter_context(patch.object(obj,name,value))
    def close(self):
        self.stack.close()


def raises(error):
    return unittest.TestCase().assertRaises(error)


def wait(predicate, seconds=40):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if predicate():
            return
        time.sleep(.02)
    assert predicate(), 'bounded existing worker did not reach expected state'


def row(p, ident):
    return dict(p._connect().execute('SELECT * FROM memory_jobs WHERE job_id=?', (ident,)).fetchone())


def counts(p):
    c = p._connect()
    return {name: c.execute('SELECT COUNT(*) FROM '+name).fetchone()[0] for name in (
        'memory_observation_event_decisions', 'memory_observation_events',
        'memory_observation_event_retries', 'memory_observation_versions', 'claims', 'review_queue',
    )}


@contextlib.contextmanager
def provider(name, *, bot='synthetic-G2-owner', session='synthetic-G2-session', home=None):
    home = home or FIXTURE/name
    home.mkdir(parents=True, exist_ok=True)
    home_token = hermes_constants.set_hermes_home_override(home)
    secret_token = secret_scope.set_secret_scope({}, profile_home=str(home))
    p = None
    previous_flag = os.environ['MEMORY_WIKI_BACKGROUND_JOBS_ENABLED']
    try:
        # Startup cannot launch an eager worker while the test authors input.
        os.environ['MEMORY_WIKI_BACKGROUND_JOBS_ENABLED'] = '0'
        p = wiki.MemoryWikiProvider()
        assert p.__class__.__bases__ == (MemoryProvider,)
        p.initialize(session, hermes_home=str(home), bot_id=bot,
                     project_id='synthetic-G2-project', agent_context='primary')
        p.project_scope = ''
        assert p._background_worker is None
        os.environ['MEMORY_WIKI_BACKGROUND_JOBS_ENABLED'] = '1'
        yield p
    finally:
        os.environ['MEMORY_WIKI_BACKGROUND_JOBS_ENABLED'] = previous_flag
        if p is not None:
            assert p._background_worker is None
            connection = p._conn
            p.shutdown()
            if connection is not None:
                connection.close()
                with raises(sqlite3.ProgrammingError):
                    connection.execute('SELECT 1')
                p._conn = None
        secret_scope.reset_secret_scope(secret_token)
        hermes_constants.reset_hermes_home_override(home_token)


def capture(p, n, text='Synthetic fixture: the orchid exhibit contains a copper telescope.'):
    ids = []
    for i in range(n):
        event = wiki._memory_events.capture_event(
            p, wiki, text, role='user', event_type='dialogue_turn',
            session_id=p.session_id, scope='chat', turn_id='synthetic-turn-'+str(i),
            provenance={'source':'authored:G2-fixture'},
        )
        assert event
        ids.append(event)
    return ids


def enqueue(p, event, *, now=None):
    if now is None:
        ident = jobs.enqueue_event(p, 'consolidate_observations', event)
    else:
        source=p._connect().execute('SELECT * FROM memory_events WHERE event_id=?',(event,)).fetchone()
        ident=jobs.JobStore(p.db_path,jobs.profile_key(p),jobs.owner_key(p)).enqueue(
            'consolidate_observations',{'event_id':event},jobs.partition_key(source),
            owner_chat_hash=source['owner_chat_hash'],owner_session_hash=source['owner_session_hash'],now=now)
    assert ident
    return ident


@contextlib.contextmanager
def worker(p):
    w = jobs.Worker(p, wiki)
    w.start()
    try:
        yield w
    finally:
        assert w.stop(), 'fixture-owned worker failed to stop naturally'
        assert not w.thread.is_alive()


def spy(monkeypatch):
    reports = []
    real = observations.consolidate_events
    def record(*a, **kw):
        value = real(*a, **kw)
        reports.append(value)
        return value
    monkeypatch.setattr(observations, 'consolidate_events', record)
    return reports


def check_finite_backlog_uses_one_existing_job_without_incoming_turn(n, monkeypatch):
    monkeypatch.setenv('MEMORY_WIKI_OBSERVATION_BACKGROUND_BATCH', '64')
    monkeypatch.setenv('MEMORY_WIKI_BACKGROUND_POLL_SECONDS', '1')
    reports = spy(monkeypatch)
    with provider('finite-'+str(n)) as p:
        ids = capture(p, n)
        ident = enqueue(p, ids[-1])
        before = json.loads(row(p, ident)['payload_json'])
        started = time.monotonic()
        with worker(p):
            wait(lambda: row(p, ident)['status'] == 'done', seconds=55)
        c = p._connect()
        assert counts(p)['memory_observation_event_decisions'] == n
        assert counts(p)['memory_observation_events'] == n
        assert counts(p)['memory_observation_event_retries'] == 0
        assert c.execute('SELECT SUM(support_count) FROM memory_observations').fetchone()[0] == n
        assert c.execute('SELECT COUNT(*) FROM memory_jobs').fetchone()[0] == 1
        assert json.loads(row(p, ident)['payload_json']) == before == {'event_id':ids[-1]}
        assert all(r['events_scanned'] <= 64 for r in reports)
        assert all(r['ready_work_remaining'] == 1 and r['next_cursor'] in ids for r in reports[:-1])
        assert reports[-1]['ready_work_remaining'] == 0 and reports[-1]['next_cursor'] == ''
        assert reports[-1]['next_retry_at'] == 0
        assert row(p, ident)['generation'] == 1
        assert counts(p)['claims'] == counts(p)['review_queue'] == 0
        assert row(p, ident)['attempts'] == 1
        DETAILS['finite-'+str(n)] = {'events':n, 'passes':len(reports),
            'processed':counts(p)['memory_observation_event_decisions'],
            'max_batch':max(r['events_scanned'] for r in reports),
            'elapsed':round(time.monotonic()-started,3), 'generation':1,
            'job_status':row(p, ident)['status'], 'incoming_messages_after_enqueue':0}


def check_support_phase_only_runtime_failure_continues_to_version(monkeypatch):
    monkeypatch.setenv('MEMORY_WIKI_BACKGROUND_POLL_SECONDS', '1')
    monkeypatch.setenv('MEMORY_WIKI_OBSERVATION_RETRY_BASE_SECONDS', '2')
    reports = spy(monkeypatch)
    native = wiki.MemoryWikiProvider._inspect_recall_text
    calls = {}
    def fail_support_once(self, text, **kw):
        if kw.get('source') == 'observation:event_evidence':
            event = kw['item_id']
            calls[event] = calls.get(event,0)+1
            if calls[event] == 2:
                raise RuntimeError('synthetic one-shot support guard dependency refusal')
        return native(self,text,**kw)
    monkeypatch.setattr(wiki.MemoryWikiProvider,'_inspect_recall_text',fail_support_once)
    with provider('support-retry') as p:
        event = capture(p,1)[0]
        ident = enqueue(p,event)
        with worker(p):
            wait(lambda: row(p,ident)['status']=='pending' and bool(reports), seconds=10)
            first = reports[0]
            assert first['events_linked']==1 and first['events_deferred']==1
            assert first['support_events_deferred']==1
            assert first['ready_work_remaining']==0 and first['next_retry_at']>0
            assert counts(p)['memory_observation_versions']==0
            pending = row(p,ident)
            assert pending['available_at'] >= first['next_retry_at'] and pending['attempts']==0
            wait(lambda: row(p,ident)['status']=='done', seconds=10)
        assert counts(p)['memory_observation_versions']==1
        assert counts(p)['memory_observation_event_retries']==0
        assert p._connect().execute('SELECT support_count FROM memory_observations').fetchone()[0]==1
        assert counts(p)['memory_observation_events']==1
        DETAILS['support']={'passes':len(reports),'unique_deferred':first['events_deferred'],
                           'ready_on_failure':first['ready_work_remaining'],
                           'pending_before_recovery':pending['status'],'final':row(p,ident)['status']}


def check_bounded_time_daily_budget_and_periodic_fairness(monkeypatch):
    monkeypatch.setenv('MEMORY_WIKI_OBSERVATION_BACKGROUND_SECONDS','.05')
    monkeypatch.setenv('MEMORY_WIKI_OBSERVATION_BACKGROUND_BATCH','64')
    reports = spy(monkeypatch)
    native = wiki.MemoryWikiProvider._inspect_recall_text
    def slow(self,text,**kw):
        result = native(self,text,**kw)
        if kw.get('source') == 'observation:event_evidence':
            time.sleep(.055)  # A native callback cannot be preempted; yield afterwards.
        return result
    with provider('fairness') as p:
        first_events = capture(p,65)
        first = enqueue(p,first_events[-1],now=int(time.time())-2)
        with provider('fairness-peer',session='synthetic-peer',home=p.home) as peer:
            second_events = capture(peer,1)
            second = enqueue(peer,second_events[0])
            monkeypatch.setattr(wiki.MemoryWikiProvider,'_inspect_recall_text',slow)
            started = time.monotonic()
            assert jobs.run_once(p,wiki)
            assert time.monotonic()-started < 2.0
            assert row(p,first)['status']=='pending'
            assert reports[0]['budget_exhausted'] and reports[0]['events_scanned'] < 64
            assert reports[0]['ready_work_remaining']==1
            assert jobs.run_once(p,wiki), 'other due partition must get its turn'
            assert reports[1]['events_linked']==1
            assert p._connect().execute('SELECT COUNT(*) FROM memory_observation_event_decisions WHERE event_id=?',(second_events[0],)).fetchone()[0]==1
            monkeypatch.setattr(wiki.MemoryWikiProvider,'_inspect_recall_text',native)
            monkeypatch.setenv('MEMORY_WIKI_BACKGROUND_DAILY_JOBS','2')
            time.sleep(1.05)
            assert not jobs.run_once(p,wiki)
            pending = [row(p,i) for i in [first,second]]
            assert any(r['last_error_code']=='budget_deferred' for r in pending)
            assert all(r['status']=='pending' for r in pending)
            health = jobs.JobStore(p.db_path,jobs.profile_key(p),jobs.owner_key(p)).health()
            assert health['jobs_today']==2
            DETAILS['budget-fairness']={'passes':len(reports),'max_scanned':max(r['events_scanned'] for r in reports),
                'daily_jobs_used':health['jobs_today'],'budget_pending':True,'other_partition_processed':True}


def check_owner_filtered_limit_future_retry_and_runtime_policy_gate(monkeypatch):
    monkeypatch.setenv('MEMORY_WIKI_OBSERVATION_BACKGROUND_BATCH','1')
    with provider('owner') as p:
        with provider('foreign',bot='synthetic-foreign-owner',home=p.home) as foreign:
            foreign_ids = capture(foreign,3)
        own = capture(p,2)
        # Same bot/session but different project context is also outside this job.
        p.project_scope='synthetic-other-project'
        project_ids = capture(p,2)
        p.project_scope=''
        ident = enqueue(p,own[-1])
        monkeypatch.setenv('MEMORY_WIKI_OBSERVATIONS_ENABLED','0')
        assert jobs.run_once(p,wiki)
        assert row(p,ident)['status']=='pending'
        assert counts(p)['memory_observation_event_decisions']==0
        # Exercise an actual lease at its future availability without wall-clock
        # mutation. SQLite's authoritative source retry clock stays real.
        store=jobs.JobStore(p.db_path,jobs.profile_key(p),jobs.owner_key(p))
        token='a'*32
        leased=store.lease(token,now=row(p,ident)['available_at'])
        assert leased
        monkeypatch.setenv('MEMORY_WIKI_OBSERVATIONS_ENABLED','1')
        due=int(time.time())+120
        with p._connect() as c:
            observations._defer_event(c,own[0],stamp=due-1,reason='synthetic_future_dependency')
        outcome=jobs._run_job(p,wiki,leased,lease_valid=lambda:store.owns(leased,token))
        assert outcome==('defer',due)
        assert p._connect().execute('SELECT event_id FROM memory_observation_event_decisions').fetchone()[0]==own[1]
        assert store.defer(leased,token,until=due,now=int(time.time()))
        assert row(p,ident)['status']=='pending' and row(p,ident)['attempts']==0
        assert store.lease(token,now=due-1) is None
        assert not any(p._connect().execute('SELECT 1 FROM memory_observation_event_decisions WHERE event_id=?',(i,)).fetchone() for i in foreign_ids+project_ids)
        DETAILS['owner-future-gate']={'foreign_events_unchanged':len(foreign_ids)+len(project_ids),
            'eligible_event_processed':True,'ready_zero_but_future_retry_pending':True,'runtime_disabled_not_done':True}


def check_lease_owner_expiry_generation_and_transaction_rollback(monkeypatch):
    with provider('lease') as p:
        events=capture(p,2)
        ident=enqueue(p,events[-1])
        store=jobs.JobStore(p.db_path,jobs.profile_key(p),jobs.owner_key(p))
        token='b'*32
        stamp=row(p,ident)['available_at']
        leased=store.lease(token,now=stamp)
        assert leased
        expiry=leased['lease_expires_at']
        assert not store.finish(leased,token,now=expiry)
        assert not store.defer(leased,token,until=expiry+60,now=expiry)
        wrong=jobs.JobStore(p.db_path,store.profile,'c'*64)
        assert not wrong.finish(leased,token,now=stamp+1)
        assert not wrong.defer(leased,token,until=stamp+100,now=stamp+1)
        recovered=store.lease(token,now=expiry)
        assert recovered and not store.finish(leased,token)
        checks=0
        def lease_lost_after_guard():
            nonlocal checks
            checks+=1
            return store.owns(recovered,token) and checks<4
        with raises(TimeoutError):
            jobs._run_job(p,wiki,recovered,lease_valid=lease_lost_after_guard)
        assert counts(p)['memory_observation_event_decisions']==0
        assert counts(p)['memory_observation_events']==0
        assert counts(p)['memory_observation_versions']==0
        assert enqueue(p,events[0])==ident
        assert store.defer(recovered,token,until=int(time.time())+120)
        state=row(p,ident)
        assert state['available_at']<=int(time.time()) and state['generation']==2
        assert jobs.run_once(p,wiki)
        assert row(p,ident)['status']=='done'
        assert counts(p)['memory_observation_event_decisions']==2
        DETAILS['lease']={'expired_finish_refused':True,'expired_defer_refused':True,
            'foreign_store_refused':True,'lost_lease_rollback':True,'generation_requeued':2,'final':'done'}


def check_graceful_worker_stop_restart_uses_durable_decisions(monkeypatch):
    monkeypatch.setenv('MEMORY_WIKI_OBSERVATION_BACKGROUND_BATCH','32')
    monkeypatch.setenv('MEMORY_WIKI_BACKGROUND_POLL_SECONDS','1')
    completed=threading.Event()
    release=threading.Event()
    native=observations.consolidate_events
    calls=0
    def pause_once(*a,**kw):
        nonlocal calls
        result=native(*a,**kw)
        calls+=1
        if calls==1:
            completed.set()
            assert release.wait(5)
        return result
    monkeypatch.setattr(observations,'consolidate_events',pause_once)
    with provider('restart') as p:
        ids=capture(p,65)
        ident=enqueue(p,ids[-1])
        w=jobs.Worker(p,wiki)
        w.start()
        try:
            assert completed.wait(10)
            w.stop_event.set()
            release.set()
            assert w.stop()
            assert row(p,ident)['status']=='pending'
            assert counts(p)['memory_observation_event_decisions']==32
            first_generation=row(p,ident)['generation']
            # New instance, same SQLite state; no re-enqueue or replay cursor reset.
            with worker(p):
                wait(lambda:row(p,ident)['status']=='done',seconds=10)
        finally:
            release.set()
            assert w.stop()
        assert counts(p)['memory_observation_event_decisions']==65
        assert counts(p)['memory_observation_events']==65
        assert row(p,ident)['generation']==first_generation==1
        assert p._connect().execute('SELECT COUNT(*) FROM memory_jobs').fetchone()[0]==1
        DETAILS['restart']={'durable_completed_before_stop':32,'completed_after_restart':65,
                            'same_generation':1,'jobs':1,'stopped_naturally':True}


class FiniteWorkTests(unittest.TestCase):
    def setUp(self):
        self.overrides=Overrides()
        self.addCleanup(self.overrides.close)

    def test_finite_64(self):
        check_finite_backlog_uses_one_existing_job_without_incoming_turn(64,self.overrides)

    def test_finite_65(self):
        check_finite_backlog_uses_one_existing_job_without_incoming_turn(65,self.overrides)

    def test_finite_1000(self):
        check_finite_backlog_uses_one_existing_job_without_incoming_turn(1000,self.overrides)

    def test_support_retry(self):
        check_support_phase_only_runtime_failure_continues_to_version(self.overrides)

    def test_budget_fairness(self):
        check_bounded_time_daily_budget_and_periodic_fairness(self.overrides)

    def test_owner_future_gate(self):
        check_owner_filtered_limit_future_retry_and_runtime_policy_gate(self.overrides)

    def test_lease_fences(self):
        check_lease_owner_expiry_generation_and_transaction_rollback(self.overrides)

    def test_restart(self):
        check_graceful_worker_stop_restart_uses_durable_decisions(self.overrides)
