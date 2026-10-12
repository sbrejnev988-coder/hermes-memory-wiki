"""Actual graph writer/JobStore component regressions, never remote-model mocks.

The job fixture uses a synchronous, explicitly authored graph producer on the
real plugin provider. Dispatch, worker copy, owning transaction, SQLite, and
lease transitions are production code. Core SPI/registry/trust are genuine;
this is not host bootstrap, model extraction, fleet or native B4 qualification.
"""
from contextlib import closing, contextmanager
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import threading


import pytest
import memory_wiki as wiki
from memory_wiki import background_jobs as jobs
from memory_wiki import code_knowledge_graph as code_graph


class SynchronousGraphProvider(wiki.MemoryWikiProvider):
    """Synthetic business input, not an HTTP/model response or writer double."""
    def _auto_graph_enrich_extracted_claims(self, claim_ids):
        if self.fixture_before_effect is not None:
            self.fixture_before_effect(self)
        if self.fixture_body is None:
            self._add_relation(edge(claim_ids[0]))
        else:
            self.fixture_body(self, claim_ids[0])
        return {"errors": 0, "deadline_exhausted": 0}


@pytest.fixture
def store(request, monkeypatch):
    root = Path(os.environ["RECOVERY_DIAGNOSTIC_OUT"]) / "controls" / hashlib.sha256(request.node.nodeid.encode()).hexdigest()[:16]
    home = root / "home"
    home.mkdir(parents=True)
    monkeypatch.setenv("HERMES_HOME", str(home))
    for key in ("MEMORY_WIKI_SEMANTIC", "MEMORY_WIKI_BACKGROUND_JOBS_ENABLED", "MEMORY_WIKI_EXTRACTION_ENABLED", "MW_EXTRACTION_ENABLED", "MEMORY_WIKI_GRAPH_AUTO_EXTRACT_ENABLED", "MEMORY_WIKI_GRAPH_EXTRACT_ENABLED", "MEMORY_WIKI_QDRANT_ENABLED", "MEMORY_WIKI_EPISODIC_ENABLED", "MEMORY_WIKI_EVENT_ENABLED", "MEMORY_WIKI_OBSERVATION_ENABLED"):
        monkeypatch.setenv(key, "0")
    provider = SynchronousGraphProvider()
    provider.fixture_before_effect = None
    provider.fixture_body = None
    provider.initialize("synthetic-graph-session", hermes_home=str(home), agent_context="test", bot_id="synthetic-graph-bot", project_id="diagnostic")
    assert provider.db_path.resolve().is_relative_to(root.resolve())
    assert wiki.MemoryWikiProvider.__bases__ == (wiki.MemoryProvider,)
    assert provider._background_worker is None and provider._lifecycle_state == "ready"
    with wiki._native_profile_scope(home):
        yield provider
    # Test-owned emergency closure is deliberately NOT production recovery.
    if provider._transaction_quarantine is not None:
        worker = getattr(provider, "_graph_effect_quarantined_worker", None)
        handles = {provider._conn, provider._transaction_quarantine}
        if worker is not None:
            handles.add(worker._conn)
        for handle in handles - {None}:
            handle.set_authorizer(None)
            handle.close()
    else:
        provider._shutdown_lifecycle(render=False)
        assert provider._conn is None and provider._owned_conn is None


def seed(provider, label="first", *, scope="chat"):
    cid = "c_" + hashlib.sha256(label.encode()).hexdigest()[:20]
    conn = provider._connect()
    stamp = wiki.now()
    with provider._claim_transaction(conn):
        conn.execute("""INSERT INTO claims(id,hash,claim,normalized_claim,topic,type,scope,visibility_scope,origin_bot_id,origin_session_id,origin_chat_hash,project_id,status,risk,quality,trust_class,confidence,salience,freshness_at,updated_at,created_at,source)
            VALUES(?,?,?,?,?,'fact',?,?,?,?,?,?,'active','low',1,'fact',.9,.9,?,?,?,'extractor:heuristic')""",
            (cid, wiki.sha(cid), "Synthetic Atlas runs on synthetic Borealis.", "Synthetic Atlas runs on synthetic Borealis.", "synthetic-graph", scope, scope, provider.bot_id, provider.session_id, provider._chat_hash(provider.session_id), provider.project_scope if scope == "project" else "", stamp, stamp, stamp))
    return cid


def edge(cid="", label=""):
    return {"subject": "Synthetic Atlas" + label, "predicate": "runs_on", "object": "Synthetic Borealis" + label, "source_claim_id": cid, "confidence": .9}


def counts(provider):
    with closing(sqlite3.connect(str(provider.db_path))) as observer:
        return tuple(observer.execute("SELECT COUNT(*) FROM " + table).fetchone()[0] for table in ("relations", "entities"))


@contextmanager
def before_begin(provider, action):
    function = wiki.MemoryWikiProvider._add_relation
    while hasattr(function, "__wrapped__"):
        function = function.__wrapped__
    target = function.__code__
    seen = []
    def observe(frame, event, arg):
        if event == "line" and frame.f_code is target and "endpoint_before" in frame.f_locals and not seen:
            assert not provider._conn.in_transaction
            seen.append("pre_BEGIN")
            action()
        return observe
    previous = sys.gettrace()
    try:
        sys.settrace(observe)
        yield seen
    finally:
        sys.settrace(previous)
    assert seen == ["pre_BEGIN"]


def retire(provider, cid):
    with closing(sqlite3.connect(str(provider.db_path))) as rival, rival:
        rival.execute("UPDATE claims SET status='retired' WHERE id=?", (cid,))


def lease(provider, cid):
    jid = jobs.enqueue_claim(provider, cid)
    assert jid is not None
    store = jobs.JobStore(provider.db_path, jobs.profile_key(provider), jobs.owner_key(provider))
    worker = "a" * 32
    job = store.lease(worker)
    assert job is not None and store.owns(job, worker)
    return store, worker, job


def dispatch(provider, store, worker, job):
    return jobs._run_job(provider, wiki, job,
        lease_valid=lambda: store.owns(job, worker),
        lease_valid_in_transaction=lambda conn: store.owns(job, worker, connection=conn))


def reassign(provider, store, job):
    with closing(sqlite3.connect(str(provider.db_path))) as rival, rival:
        rival.execute("UPDATE memory_jobs SET lease_expires_at=0 WHERE job_id=?", (job["job_id"],))
    current = store.lease("b" * 32)
    assert current is not None and current["job_id"] == job["job_id"]
    return current


def test_healthy_direct_source(store):
    cid = seed(store)
    result = store._add_relation(edge(cid))
    assert result["source_claim_id"] == cid and counts(store) == (1, 2)
    assert store._claim_tx_connection is None and store._transaction_quarantine is None


def test_source_retirement_between_owner_read_and_begin(store):
    cid = seed(store)
    with before_begin(store, lambda: retire(store, cid)):
        with pytest.raises((PermissionError, ValueError), match="graph|source"):
            store._add_relation(edge(cid))
    assert counts(store) == (0, 0)
    assert store._connect().execute("SELECT status FROM claims WHERE id=?", (cid,)).fetchone()[0] == "retired"


def test_healthy_current_background_lease(store):
    cid = seed(store)
    jobstore, worker, job = lease(store, cid)
    assert dispatch(store, jobstore, worker, job) == ""
    assert counts(store) == (1, 2)
    assert jobstore.finish(job, worker)


def test_reassigned_original_background_lease_before_effect(store):
    cid = seed(store)
    jobstore, worker, job = lease(store, cid)
    new = []
    store.fixture_before_effect = lambda actor: new.append(reassign(store, jobstore, job))
    with pytest.raises(TimeoutError, match="lease"):
        dispatch(store, jobstore, worker, job)
    assert counts(store) == (0, 0)
    assert not jobstore.owns(job, worker) and not jobstore.finish(job, worker)
    assert jobstore.owns(new[0], "b" * 32)


@contextmanager
def late_journal(provider, action):
    function = wiki.MemoryWikiProvider._claim_journal_pending_commit
    while hasattr(function, "__wrapped__"):
        function = function.__wrapped__
    seen = []
    def observe(frame, event, arg):
        actor = frame.f_locals.get("self")
        conn = frame.f_locals.get("conn")
        stage = getattr(actor, "_claim_tx_graph_stage", None)
        if (event == "call" and frame.f_code is function.__code__
                and getattr(actor, "db_path", None) == provider.db_path
                and conn is not None and conn.in_transaction
                and stage is not None and stage[2] and not seen):
            seen.append("late_journal")
            action(actor, conn)
    previous = sys.getprofile()
    try:
        sys.setprofile(observe)
        yield seen
    finally:
        sys.setprofile(previous)
    assert seen == ["late_journal"]


def linked(provider, cid, expected=2):
    conn = provider._connect()
    rows = conn.execute("SELECT * FROM entities WHERE source_claim_id=?", (cid,)).fetchall()
    assert len(rows) == expected
    assert all(provider._graph_row_visible(row, conn=conn) for row in rows)
    relations = conn.execute("SELECT * FROM relations WHERE source_claim_id=?", (cid,)).fetchall()
    assert relations
    ids = {row["id"] for row in rows}
    assert all(row["subject_id"] in ids and row["object_id"] in ids for row in relations)
    assert not conn.execute("PRAGMA foreign_key_check").fetchall()
    assert conn.execute("PRAGMA quick_check").fetchone()[0] == "ok"


def test_source_bound_endpoints_and_public_tool_positive(store):
    cid = seed(store)
    response = json.loads(store.handle_tool_call("memory_wiki_add_relation", edge(cid)))
    assert response["success"] is True and counts(store) == (1, 2)
    linked(store, cid)


def test_explicit_ownerless_graph_remains_legal(store):
    result = store._add_relation({**edge(), "visibility_scope": "chat"})
    assert result["source_claim_id"] == "" and counts(store) == (1, 2)
    conn = store._connect()
    assert all(store._graph_row_visible(row, conn=conn) for row in conn.execute("SELECT * FROM entities"))


@pytest.mark.parametrize("mutation", ["revision", "scope", "temporal", "quarantine", "row_image", "physical_row"])
def test_original_source_full_image_denies_prebegin_changes(store, mutation):
    cid = seed(store)
    def change():
        with closing(sqlite3.connect(str(store.db_path))) as rival, rival:
            if mutation == "physical_row":
                rival.execute("UPDATE claims SET rowid=rowid+100000 WHERE id=?", (cid,))
            else:
                sql = {"revision": "memory_revision=memory_revision+1", "scope": "visibility_scope='bot'", "temporal": "temporal_status='superseded'", "quarantine": "quarantined_at=1", "row_image": "claim='Changed synthetic fact'"}[mutation]
                rival.execute("UPDATE claims SET " + sql + " WHERE id=?", (cid,))
    with before_begin(store, change):
        with pytest.raises(PermissionError, match="graph_original_source_changed|graph_source"):
            store._add_relation(edge(cid))
    assert counts(store) == (0, 0)
    assert not store._connect().in_transaction and store._claim_tx_graph_stage is None


def test_direct_late_journal_source_retirement_rolls_back_entire_batch(store):
    cid = seed(store)
    with late_journal(store, lambda actor, conn: conn.execute("UPDATE claims SET status='retired' WHERE id=?", (cid,))):
        with pytest.raises(PermissionError, match="source"):
            store._add_relation(edge(cid))
    assert counts(store) == (0, 0)
    assert store._connect().execute("SELECT status FROM claims WHERE id=?", (cid,)).fetchone()[0] == "active"


def test_joined_positive_is_unpublished_until_owner_commit(store):
    cid = seed(store)
    conn = store._connect()
    with store._claim_transaction(conn):
        result = store._add_relation(edge(cid))
        assert conn.in_transaction and counts(store) == (0, 0)
        assert store._claim_tx_graph_stage[0] is conn
        assert store._claim_tx_graph_stage[1] == threading.get_ident()
        assert len(store._claim_tx_graph_stage[2]) == 1
        assert result["id"]
    assert counts(store) == (1, 2) and store._claim_tx_graph_stage is None
    linked(store, cid)


@pytest.mark.parametrize("which", ["first", "last", "repeated"])
def test_every_joined_source_admission_survives_after_return(store, which):
    first, last = seed(store, "first"), seed(store, "last")
    conn = store._connect()
    with pytest.raises(PermissionError, match="source"):
        with store._claim_transaction(conn):
            store._add_relation(edge(first, " first"))
            store._add_relation(edge(last, " last"))
            store._add_relation(edge(first, " repeated"))
            assert len(store._claim_tx_graph_stage[2]) == 3
            target = last if which == "last" else first
            conn.execute("UPDATE claims SET status='retired' WHERE id=?", (target,))
    assert counts(store) == (0, 0) and store._claim_tx_graph_stage is None


def test_joined_late_journal_validates_first_not_only_last(store):
    first, last = seed(store, "first"), seed(store, "last")
    with late_journal(store, lambda actor, conn: conn.execute("UPDATE claims SET memory_revision=memory_revision+1 WHERE id=?", (first,))):
        with pytest.raises(PermissionError, match="source"):
            with store._claim_transaction():
                store._add_relation(edge(first, " first"))
                store._add_relation(edge(last, " last"))
    assert counts(store) == (0, 0)


def test_repeated_source_different_original_actors_not_recaptured(store):
    cid = seed(store, scope="global")
    original_session = store.session_id
    try:
        with pytest.raises(PermissionError, match="owner"):
            with store._claim_transaction():
                store._add_relation(edge(cid, " first"))
                store.session_id = "another-synthetic-actor"
                store._add_relation(edge(cid, " second"))
                store.session_id = original_session
    finally:
        store.session_id = original_session
    assert counts(store) == (0, 0)


def test_known_rollback_retires_old_admissions_for_new_stage(store):
    cid = seed(store)
    primary = RuntimeError("synthetic owner abort")
    with pytest.raises(RuntimeError) as caught:
        with store._claim_transaction():
            store._add_relation(edge(cid))
            raise primary
    assert caught.value is primary and counts(store) == (0, 0)
    assert store._claim_tx_graph_stage is None and store._claim_tx_connection is None
    retire(store, cid)
    healthy = seed(store, "healthy-new-stage")
    store._add_relation(edge(healthy))
    linked(store, healthy)


def test_endpoints_do_not_coalesce_or_revive_another_source(store):
    first, last = seed(store, "first"), seed(store, "last")
    a, b = store._add_relation(edge(first)), store._add_relation(edge(last))
    assert a["subject_id"] != b["subject_id"] and a["object_id"] != b["object_id"]
    assert counts(store) == (2, 4)
    linked(store, first)
    linked(store, last)
    retire(store, first)
    conn = store._connect()
    assert not any(store._graph_row_visible(row, conn=conn) for row in conn.execute("SELECT * FROM entities WHERE source_claim_id=?", (first,)))
    store._add_relation(edge(last))
    linked(store, last)
    assert counts(store) == (2, 4)
    assert not any(store._graph_row_visible(row, conn=conn) for row in conn.execute("SELECT * FROM entities WHERE source_claim_id=?", (first,)))


def test_entity_owner_retains_source_admission_and_binding(store):
    cid = seed(store)
    store._add_entity({"name": "Synthetic standalone entity", "source_claim_id": cid})
    conn = store._connect()
    assert conn.execute("SELECT source_claim_id FROM entities").fetchone()[0] == cid
    with late_journal(store, lambda actor, conn: conn.execute("UPDATE claims SET status='retired' WHERE id=?", (cid,))):
        with pytest.raises(PermissionError, match="source"):
            store._add_entity({"name": "Synthetic denied entity", "source_claim_id": cid})
    assert counts(store) == (0, 1)


def test_private_factory_writer_joins_real_owner_not_same_path(store):
    cid = seed(store)
    private, owned = code_graph._open_graph_writer_connection(store)
    assert owned and private is not store._conn
    try:
        with private:
            store._add_relation(edge(cid), conn=private)
            assert store._claim_tx_graph_stage[0] is private
            assert counts(store) == (0, 0)
        assert counts(store) == (1, 2)
    finally:
        code_graph._close_graph_writer_connection(private, owned)
    assert not store._graph_writer_connections
    linked(store, cid)


def test_foreign_same_path_writer_refused_before_effect(store):
    cid = seed(store)
    with closing(sqlite3.connect(str(store.db_path))) as foreign:
        foreign.row_factory = sqlite3.Row
        with pytest.raises(RuntimeError, match="not_owned"):
            store._add_relation(edge(cid), conn=foreign)
    assert counts(store) == (0, 0)


def test_background_initial_source_cannot_be_recaptured_after_dispatch(store):
    cid = seed(store)
    jobstore, worker, job = lease(store, cid)
    store.fixture_before_effect = lambda actor: retire(store, cid)
    with pytest.raises((PermissionError, ValueError), match="graph|source"):
        dispatch(store, jobstore, worker, job)
    assert counts(store) == (0, 0) and jobstore.owns(job, worker)


@pytest.mark.parametrize("joined", [False, True])
def test_background_lease_lost_in_late_journal_rolls_back_endpoints(store, joined):
    cid = seed(store)
    jobstore, worker, job = lease(store, cid)
    if joined:
        def body(actor, source_id):
            with actor._claim_transaction():
                actor._add_relation(edge(source_id, " one"))
                actor._add_relation(edge(source_id, " two"))
        store.fixture_body = body
    with late_journal(store, lambda actor, conn: conn.execute("UPDATE memory_jobs SET lease_expires_at=0 WHERE job_id=?", (job["job_id"],))):
        with pytest.raises(TimeoutError, match="lease"):
            dispatch(store, jobstore, worker, job)
    assert counts(store) == (0, 0)
    assert jobstore.owns(job, worker)  # The expiry mutation itself rolled back.
    assert store._transaction_quarantine is None


def test_background_store_fences_original_token_even_if_callbacks_lie(store):
    cid = seed(store)
    jobstore, worker, job = lease(store, cid)
    current = []
    store.fixture_before_effect = lambda actor: current.append(reassign(store, jobstore, job))
    with pytest.raises(TimeoutError, match="lease"):
        jobs._run_job(store, wiki, job, lease_valid=lambda: True, lease_valid_in_transaction=lambda conn: True)
    assert counts(store) == (0, 0) and jobstore.owns(current[0], "b" * 32)


def test_coalesced_generation_current_lease_remains_legal(store):
    cid = seed(store)
    jobstore, worker, job = lease(store, cid)
    jobs.enqueue_claim(store, cid)
    assert jobstore.owns(job, worker)
    assert dispatch(store, jobstore, worker, job) == ""
    linked(store, cid)
    assert jobstore.finish(job, worker)
    with closing(sqlite3.connect(str(store.db_path))) as observer:
        assert observer.execute("SELECT status,generation FROM memory_jobs WHERE job_id=?", (job["job_id"],)).fetchone() == ("pending", job["generation"] + 1)


def test_background_unknown_rollback_retains_exact_worker_primary_admissions(store):
    cid = seed(store)
    jobstore, worker_id, job = lease(store, cid)
    def poison(actor, conn):
        conn.execute("UPDATE memory_jobs SET lease_expires_at=0 WHERE job_id=?", (job["job_id"],))
        conn.set_authorizer(lambda action, first, second, db, trigger: sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_TRANSACTION and first == "ROLLBACK" else sqlite3.SQLITE_OK)
    with late_journal(store, poison):
        with pytest.raises(TimeoutError, match="lease") as caught:
            dispatch(store, jobstore, worker_id, job)
    worker = store._graph_effect_quarantined_worker
    assert worker._conn is worker._owned_conn is worker._transaction_quarantine
    assert store._transaction_quarantine is worker._conn
    assert worker._claim_tx_connection is worker._conn and worker._conn.in_transaction
    assert worker._claim_tx_graph_stage[0] is worker._conn and len(worker._claim_tx_graph_stage[2]) == 1
    assert store._transaction_primary is worker._transaction_primary is caught.value
    assert any("outcome=UNKNOWN" in note for note in caught.value.__notes__)
    assert counts(store) == (0, 0)  # Durable reader sees no committed effects.
    with pytest.raises(RuntimeError, match="not_ready"):
        worker._connect()
    with pytest.raises(RuntimeError, match="not_ready"):
        store._connect()
    assert not store._release_connection_for_retry(caught.value)


def test_direct_unknown_preserves_all_joined_original_admissions(store):
    first, last = seed(store, "first"), seed(store, "last")
    conn = store._connect()
    def poison(actor, owner):
        owner.execute("UPDATE claims SET status='retired' WHERE id=?", (first,))
        owner.set_authorizer(lambda action, first, second, db, trigger: sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_TRANSACTION and first == "ROLLBACK" else sqlite3.SQLITE_OK)
    with late_journal(store, poison):
        with pytest.raises(PermissionError, match="source") as caught:
            with store._claim_transaction(conn):
                store._add_relation(edge(first, " first"))
                store._add_relation(edge(last, " last"))
    stage = store._claim_tx_graph_stage
    assert stage[0] is conn and stage[1] == threading.get_ident() and len(stage[2]) == 2
    assert store._claim_tx_connection is store._owned_conn is store._transaction_quarantine is conn
    assert store._transaction_primary is caught.value and conn.in_transaction
    assert counts(store) == (0, 0)
    with pytest.raises(RuntimeError, match="not_ready"):
        store._connect()


def test_joined_last_lease_callback_cannot_invalidate_first_source_after_check(store):
    cid = seed(store)
    jobstore, worker, job = lease(store, cid)
    def body(actor, source_id):
        with actor._claim_transaction():
            actor._add_relation(edge(source_id, " one"))
            actor._add_relation(edge(source_id, " repeated"))
    store.fixture_body = body
    calls = []
    def lease_callback(conn):
        calls.append(1)
        if len(calls) == 4:  # Two joins, then BOTH original final obligations.
            conn.execute("UPDATE claims SET memory_revision=memory_revision+1 WHERE id=?", (cid,))
        return jobstore.owns(job, worker, connection=conn)
    with pytest.raises(PermissionError, match="source"):
        jobs._run_job(store, wiki, job, lease_valid=lambda: jobstore.owns(job, worker), lease_valid_in_transaction=lease_callback)
    assert len(calls) == 4 and counts(store) == (0, 0)


def test_original_lease_checked_after_final_source_read_callback(store):
    cid = seed(store)
    jobstore, worker, job = lease(store, cid)
    function = wiki.MemoryWikiProvider._graph_source_eligible
    seen = []
    active = []
    store.fixture_before_effect = lambda actor: active.append(actor)
    def observe(frame, event, arg):
        if event != "return" or frame.f_code is not function.__code__ or not active or seen:
            return
        conn = active[0]._conn
        if (conn is not None and conn.in_transaction
                and conn.execute("SELECT COUNT(*) FROM relations").fetchone()[0]):
            seen.append("after_final_source")
            conn.execute("UPDATE memory_jobs SET lease_expires_at=0 WHERE job_id=?", (job["job_id"],))
    previous = sys.getprofile()
    try:
        sys.setprofile(observe)
        with pytest.raises(TimeoutError, match="lease"):
            dispatch(store, jobstore, worker, job)
    finally:
        sys.setprofile(previous)
        active.clear()
    assert seen == ["after_final_source"] and counts(store) == (0, 0)


def test_existing_relation_rebinds_to_source_vertices_not_ownerless_sibling(store):
    cid = seed(store)
    ownerless = store._add_relation({**edge(), "visibility_scope": "chat"})
    conn = store._connect()
    owner = store._graph_owner(edge(cid))
    digest = wiki.sha("relation\0" + owner["identity"] + "\0" + cid + "\0" + "synthetic atlas" + "\0runs_on\0synthetic borealis")
    old_id = "rel_" + digest[:20]
    with store._claim_transaction(conn):
        conn.execute("""INSERT INTO relations(id,subject,predicate,object,confidence,evidence,created_at,hash,visibility_scope,origin_bot_id,origin_session_id,origin_chat_hash,project_id,source_claim_id,subject_id,object_id)
            SELECT ?,subject,predicate,object,confidence,evidence,created_at,?,visibility_scope,origin_bot_id,origin_session_id,origin_chat_hash,project_id,?,subject_id,object_id FROM relations WHERE id=?""", (old_id, digest, cid, ownerless["id"]))
    result = store._add_relation(edge(cid))
    assert result["id"] == old_id
    assert result["subject_id"] != ownerless["subject_id"] and result["object_id"] != ownerless["object_id"]
    linked(store, cid)
    assert conn.execute("SELECT source_claim_id FROM entities WHERE id=?", (ownerless["subject_id"],)).fetchone()[0] == ""
