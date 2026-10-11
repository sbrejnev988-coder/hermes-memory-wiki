"""H1/H2 genuine provider/SQLite component regressions.

Retained-cache fixtures are authored SQL metadata, NOT parser executions. No
SDK/parser/LLM callable is replaced. The actual parser-worker E2E is a separate,
unadmitted native case; these tests cannot confer that admission.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import threading

import pytest
import memory_wiki as wiki
from memory_wiki import document_knowledge_graph as graph
from memory_wiki import source_connectors as connectors

# Reuse the shipped flat helper layout and original fixture without changing
# its assertions or parser/cache labels.
_spec = importlib.util.spec_from_file_location(
    "_document_authority_recovery_peer", Path(__file__).with_name("test_recovery_atomic_contract.py"))
_peer = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_peer)
owned = _peer.owned


@pytest.fixture
def store(owned, monkeypatch):
    # Explicit test-owned non-secret options, not dependence on outer defaults.
    for key in ("MEMORY_WIKI_DOCUMENT_ALLOW_SCOPE_MIGRATION", "MEMORY_WIKI_DOCUMENT_ALLOW_CROSS_SCOPE",
                "MEMORY_WIKI_DOCUMENT_EMBED_ON_INGEST", "MEMORY_WIKI_DOCUMENT_AUTO_EMBED",
                "MEMORY_WIKI_DOCUMENT_OCR"):
        monkeypatch.setenv(key, "0")
    provider, helpers = owned
    yield provider, helpers


def cached(store, label="authority", *, physical=True):
    provider, helpers = store
    sid, identities, identity, reference = _peer.authored_cached_source(
        provider, helpers, label, count=1, remember_physical=physical)
    conn = provider._connect()
    path = Path(conn.execute("SELECT source_path FROM document_sources WHERE source_id=?", (sid,)).fetchone()[0])
    return provider, conn, sid, path, identity, reference


def record_hook(provider, conn, sid, path):
    row = conn.execute("SELECT file_hash FROM document_sources WHERE source_id=?", (sid,)).fetchone()
    uri = "urn:document-authority:owned-record"
    key = connectors._source_key(provider, uri, "diagnostic", "diagnostic", "record")
    return connectors._RecordCommitHook(provider, conn, source_key=key, uri=uri,
        namespace="record", source_id=sid, source_type="record", display_uri=uri,
        scope_id="diagnostic", repository_id="diagnostic", revision_key="authored-record-v1",
        content_hash=row[0])


def external(provider, conn, sid, path):
    hook = record_hook(provider, conn, sid, path)
    with provider._claim_transaction(conn):
        connectors._put_source_in_transaction(provider, conn, **hook.fields)
    return hook.key


def image(conn):
    tables = ("document_sources", "document_revisions", "document_units", "document_chunks",
              "document_edges", "document_events", "document_units_fts", "document_chunks_fts",
              "document_graph_meta", "external_sources")
    return {table: sorted((tuple(row) for row in conn.execute("SELECT * FROM " + table)), key=repr)
            for table in tables}


@contextmanager
def at_ingest_owner(provider, sid, action):
    """A real competing SQLite write at the pre-BEGIN seam; not a mock call."""
    target = graph._ingest_transaction.__wrapped__.__code__
    observed = []
    def profile(frame, event, arg):
        if event == "call" and frame.f_code is target and frame.f_locals["source_id"] == sid and not observed:
            observed.append("pre_BEGIN")
            assert not provider._conn.in_transaction
            action()
    previous = sys.getprofile()
    try:
        sys.setprofile(profile)
        yield observed
    finally:
        sys.setprofile(previous)
    assert observed == ["pre_BEGIN"]


def test_H1_private_commit_uses_actual_owner_and_exact_readback(store):
    provider, conn, sid, path, _, _ = cached(store)
    hook = record_hook(provider, conn, sid, path)
    observer = sqlite3.connect(str(provider.db_path), timeout=0)
    try:
        with graph._ingest_transaction(provider, conn, hook, source_id=sid):
            assert provider._connect() is conn
            assert provider._claim_tx_connection is conn and provider._claim_tx_thread == threading.get_ident()
            conn.execute("UPDATE document_sources SET display_name='committed-record' WHERE source_id=?", (sid,))
            hook.apply(provider, conn)
            assert observer.execute("SELECT 1 FROM external_sources WHERE source_key=?", (hook.key,)).fetchone() is None
        assert observer.execute("SELECT revision_key,content_hash FROM external_sources WHERE source_key=?", (hook.key,)).fetchone() == (hook.fields["revision_key"], hook.fields["content_hash"])
        assert hook.started and hook.commit_attempted and hook.commit_returned and not hook.rollback_completed
        assert hook.outcome() == "committed" and hook.expected is not None
        assert not conn.in_transaction and provider._claim_tx_connection is None
        assert provider._transaction_quarantine is None and provider._lifecycle_state == "ready"
    finally:
        observer.close()


def test_H2_normal_cached_ingest_rechecks_late_foreign_connector_before_write(store):
    provider, conn, sid, path, _, _ = cached(store, physical=False)
    key = external(provider, conn, sid, path)
    rival = sqlite3.connect(str(provider.db_path), timeout=0)
    before = image(conn)
    def takeover():
        with rival:
            rival.execute("UPDATE external_sources SET owner_bot_id='foreign-bot' WHERE source_key=?", (key,))
    try:
        with at_ingest_owner(provider, sid, takeover):
            with pytest.raises(PermissionError, match="connector_source_not_owned"):
                graph.ingest_document(provider, {"path": str(path), "embed": False})
        after = image(conn)
        assert {k: v for k, v in after.items() if k != "external_sources"} == {k: v for k, v in before.items() if k != "external_sources"}
        assert conn.execute("SELECT owner_bot_id FROM external_sources WHERE source_key=?", (key,)).fetchone()[0] == "foreign-bot"
        assert not conn.in_transaction and provider._transaction_quarantine is None
    finally:
        rival.close()


def test_H1_real_rollback_keeps_primary_and_both_sql_images(store):
    provider, conn, sid, path, _, _ = cached(store)
    hook = record_hook(provider, conn, sid, path)
    before = image(conn)
    primary = ValueError("document-owned-primary")
    with pytest.raises(ValueError) as caught:
        with graph._ingest_transaction(provider, conn, hook, source_id=sid):
            conn.execute("UPDATE document_sources SET display_name='rolled-back' WHERE source_id=?", (sid,))
            hook.apply(provider, conn)
            raise primary
    assert caught.value is primary and image(conn) == before
    assert hook.started and hook.rollback_completed and not hook.commit_attempted
    assert hook.outcome() == "rolled_back" and provider._transaction_quarantine is None


def test_H1_commit_denial_is_proven_rollback_not_false_committed(store):
    provider, conn, sid, path, _, _ = cached(store)
    hook = record_hook(provider, conn, sid, path)
    before = image(conn)
    def authorizer(action, a, b, database, trigger):
        return sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_TRANSACTION and a == "COMMIT" else sqlite3.SQLITE_OK
    conn.set_authorizer(authorizer)
    try:
        with pytest.raises(sqlite3.DatabaseError):
            with graph._ingest_transaction(provider, conn, hook, source_id=sid):
                conn.execute("UPDATE document_sources SET display_name='not-committed' WHERE source_id=?", (sid,))
                hook.apply(provider, conn)
    finally:
        conn.set_authorizer(None)
    assert image(conn) == before and hook.commit_attempted and not hook.commit_returned
    assert hook.rollback_completed and hook.outcome() == "rolled_back"
    assert not conn.in_transaction and provider._transaction_quarantine is None


def test_H1_rollback_denial_retains_exact_owner_primary_and_unknown(store):
    provider, conn, sid, path, _, _ = cached(store)
    hook = record_hook(provider, conn, sid, path)
    primary = ValueError("retained-document-primary")
    def authorizer(action, a, b, database, trigger):
        return sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_TRANSACTION and a == "ROLLBACK" else sqlite3.SQLITE_OK
    conn.set_authorizer(authorizer)
    try:
        with pytest.raises(ValueError) as caught:
            with graph._ingest_transaction(provider, conn, hook, source_id=sid):
                conn.execute("UPDATE document_sources SET display_name='pending' WHERE source_id=?", (sid,))
                hook.apply(provider, conn)
                raise primary
        assert caught.value is primary
        assert provider._conn is provider._owned_conn is provider._claim_tx_connection is provider._transaction_quarantine is conn
        assert provider._transaction_primary is primary and conn.in_transaction
        assert hook.outcome() == "unknown" and not hook.rollback_completed and not hook.commit_returned
        assert any("UNKNOWN" in note for note in getattr(primary, "__notes__", ()))
        with pytest.raises(RuntimeError, match="provider_lifecycle_not_ready"):
            provider._connect()
        assert not provider._release_connection_for_retry(primary)
    finally:
        conn.set_authorizer(None)  # Fixture-owned teardown, NOT production completion proof.


def test_H1_unapplied_hook_rolls_back_without_any_connector_commit(store):
    provider, conn, sid, path, _, _ = cached(store)
    hook = record_hook(provider, conn, sid, path)
    before = image(conn)
    with pytest.raises(RuntimeError, match="not_applied"):
        with graph._ingest_transaction(provider, conn, hook, source_id=sid):
            conn.execute("UPDATE document_sources SET display_name='unapplied' WHERE source_id=?", (sid,))
    assert image(conn) == before and hook.rollback_completed and hook.outcome() == "rolled_back"


def test_H1_hook_cannot_adopt_or_commit_caller_transaction(store):
    provider, conn, sid, path, _, _ = cached(store)
    hook = record_hook(provider, conn, sid, path)
    before = image(conn)
    with provider._claim_transaction(conn):
        conn.execute("UPDATE document_sources SET display_name='caller-only' WHERE source_id=?", (sid,))
        with pytest.raises(RuntimeError, match="ownership_refused"):
            with graph._ingest_transaction(provider, conn, hook, source_id=sid):
                pytest.fail("private hook entered caller transaction")
        assert conn.in_transaction and provider._claim_tx_connection is conn
        assert not hook.started and not hook.commit_attempted and not hook.rollback_completed
    assert provider._transaction_quarantine is None
    assert conn.execute("SELECT display_name FROM document_sources WHERE source_id=?", (sid,)).fetchone()[0] == "caller-only"
    assert image(conn) != before


def test_H1_foreign_connection_and_untyped_hook_are_not_capabilities(store):
    provider, conn, sid, path, _, _ = cached(store)
    before = image(conn)
    with pytest.raises(TypeError, match="private_commit_hook_invalid"):
        with graph._ingest_transaction(provider, conn, object(), source_id=sid):
            pytest.fail("untyped hook entered")
    foreign = sqlite3.connect(str(provider.db_path))
    foreign.row_factory = sqlite3.Row
    try:
        with pytest.raises(RuntimeError, match="connection_changed"):
            record_hook(provider, foreign, sid, path)
    finally:
        foreign.close()
    assert image(conn) == before and provider._transaction_quarantine is None


@pytest.mark.parametrize("field", ["scope", "source", "actor"])
def test_H2_ordinary_ingest_holds_original_authority_across_pre_BEGIN_seam(store, field):
    provider, conn, sid, path, _, _ = cached(store, physical=False)
    rival = sqlite3.connect(str(provider.db_path), timeout=0)
    before = image(conn)
    def drift():
        if field == "actor":
            provider.bot_id = "changed-request-actor"
        else:
            with rival:
                if field == "scope":
                    rival.execute("UPDATE document_sources SET scope_id='foreign',repository_id='foreign' WHERE source_id=?", (sid,))
                else:
                    rival.execute("UPDATE document_sources SET updated_at=updated_at+1 WHERE source_id=?", (sid,))
    try:
        with at_ingest_owner(provider, sid, drift):
            with pytest.raises((PermissionError, RuntimeError)):
                graph.ingest_document(provider, {"path": str(path), "embed": False})
        after = image(conn)
        assert {k: v for k, v in after.items() if k != "document_sources"} == {k: v for k, v in before.items() if k != "document_sources"}
        assert not conn.in_transaction and provider._transaction_quarantine is None
    finally:
        rival.close()


def test_H2_foreign_scope_during_parse_cannot_be_reanchored(store):
    provider, conn, sid, path, _, _ = cached(store, physical=False)
    target = graph._cached_extraction_payload.__code__
    reached = []
    rival = sqlite3.connect(str(provider.db_path), timeout=0)
    def profile(frame, event, arg):
        if event == "return" and frame.f_code is target and not reached:
            reached.append("cache-return")
            with rival:
                rival.execute("UPDATE document_sources SET updated_at=updated_at+1 WHERE source_id=?", (sid,))
    previous = sys.getprofile()
    try:
        sys.setprofile(profile)
        with pytest.raises(RuntimeError, match="source_changed"):
            graph.ingest_document(provider, {"path": str(path), "embed": False})
    finally:
        sys.setprofile(previous)
        rival.close()
    assert reached == ["cache-return"] and not conn.in_transaction
    assert graph._file_identity_history(conn, sid)


def test_H2_normal_commit_admission_excludes_real_competing_writer(store):
    provider, conn, sid, path, _, _ = cached(store)
    rival = sqlite3.connect(str(provider.db_path), timeout=0)
    target = graph._assert_connector_owner.__code__
    observed = []
    def profile(frame, event, arg):
        if event == "call" and frame.f_code is target and frame.f_locals["source_id"] == sid and conn.in_transaction:
            assert provider._claim_tx_connection is conn and provider._claim_tx_thread == threading.get_ident()
            with pytest.raises(sqlite3.OperationalError):
                rival.execute("BEGIN IMMEDIATE")
            observed.append("locked")
    previous = sys.getprofile()
    try:
        sys.setprofile(profile)
        result = graph.ingest_document(provider, {"path": str(path), "embed": False})
    finally:
        sys.setprofile(previous)
        rival.close()
    assert result["status"] == "unchanged" and len(observed) >= 2
    assert not conn.in_transaction and provider._transaction_quarantine is None


def test_H2_trigger_authority_mutation_is_rolled_back_before_commit(store):
    provider, conn, sid, path, _, _ = cached(store)
    key = external(provider, conn, sid, path)
    with provider._claim_transaction(conn):
        conn.execute("CREATE TRIGGER authority_takeover AFTER UPDATE OF display_name ON document_sources "
                     "BEGIN UPDATE external_sources SET owner_bot_id='foreign-trigger'; END")
    before = image(conn)
    with pytest.raises(PermissionError, match="connector_source_not_owned"):
        with graph._ingest_transaction(provider, conn, None, source_id=sid):
            conn.execute("UPDATE document_sources SET display_name='triggered' WHERE source_id=?", (sid,))
    assert image(conn) == before and not conn.in_transaction
    assert conn.execute("SELECT owner_bot_id FROM external_sources WHERE source_key=?", (key,)).fetchone()[0] == provider.bot_id


@pytest.mark.parametrize("outer", ["commit", "rollback"])
def test_H2_ordinary_join_keeps_exact_caller_lifetime(store, outer):
    provider, conn, sid, path, _, _ = cached(store, physical=False)
    before = image(conn)
    observer = sqlite3.connect(str(provider.db_path), timeout=0)
    primary = ValueError("ordinary-ingest-caller")
    def run():
        with provider._claim_transaction(conn):
            result = graph.ingest_document(provider, {"path": str(path), "embed": False})
            assert result["status"] == "unchanged"
            assert conn.in_transaction and provider._claim_tx_connection is conn
            assert observer.execute("SELECT COUNT(*) FROM document_graph_meta WHERE key LIKE 'file_identity_owner:%'").fetchone()[0] < conn.execute("SELECT COUNT(*) FROM document_graph_meta WHERE key LIKE 'file_identity_owner:%'").fetchone()[0]
            if outer == "rollback":
                raise primary
    try:
        if outer == "rollback":
            with pytest.raises(ValueError) as caught:
                run()
            assert caught.value is primary and image(conn) == before
        else:
            run()
            assert image(conn) != before
    finally:
        observer.close()
    assert not conn.in_transaction and provider._claim_tx_connection is None and provider._transaction_quarantine is None


def test_H2_document_journal_reference_readback_and_erasure_fence_survive(store):
    provider, conn, sid, path, _, _ = cached(store)
    start = len(provider.journal_path.read_text(encoding="utf-8").splitlines())
    result = json.loads(provider.handle_tool_call("memory_wiki_document_ingest", {"path": str(path), "embed": False}))
    assert result["status"] == "unchanged"
    events = [json.loads(line) for line in provider.journal_path.read_text(encoding="utf-8").splitlines()[start:]]
    assert [row["phase"] for row in events] == ["before", "after"]
    ref = events[-1]["result"]["recovery"]["references"][0]
    assert ref["file_hash"] == conn.execute("SELECT file_hash FROM document_sources WHERE source_id=?", (sid,)).fetchone()[0]
    assert ref["file_identities"] == [list(item) for item in sorted(graph._file_identity_history(conn, sid))]
    assert graph._MAX_FILE_IDENTITY_HISTORY_CHARS == 12000
    deleted = json.loads(provider.handle_tool_call("memory_wiki_document_delete", {"source_id": sid}))
    assert deleted["status"] == "deleted"
    assert conn.execute("SELECT COUNT(*) FROM document_units_fts WHERE source_id=?", (sid,)).fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM document_chunks_fts WHERE source_id=?", (sid,)).fetchone()[0] == 0
    assert not conn.in_transaction and provider._transaction_quarantine is None


def test_H1_actual_cached_ingest_composes_with_private_record_hook(store):
    provider, conn, sid, path, _, _ = cached(store, physical=False)
    hook = record_hook(provider, conn, sid, path)
    result = graph.ingest_document(provider, {"path": str(path), "embed": False}, _commit_hook=hook)
    assert result["status"] == "unchanged" and result["source_id"] == sid
    assert result["file_identity_updated"] and hook.outcome() == "committed"
    assert hook.commit_attempted and hook.commit_returned and not hook.rollback_completed
    assert hook._tuple() == hook.expected and not conn.in_transaction
    assert provider._claim_tx_connection is None and provider._transaction_quarantine is None


def test_H1_postcommit_callback_failure_keeps_committed_tuple_and_unknown_owner(store):
    provider, conn, sid, path, _, _ = cached(store)
    hook = record_hook(provider, conn, sid, path)
    primary = ValueError("owned-postcommit-callback")
    target = wiki.MemoryWikiProvider._claim_journal_committed.__wrapped__.__code__
    observed = []
    def profile(frame, event, arg):
        if event == "call" and frame.f_code is target and hook.commit_returned:
            observed.append("after-native-commit")
            raise primary
    previous = sys.getprofile()
    try:
        sys.setprofile(profile)
        with pytest.raises(ValueError) as caught:
            with graph._ingest_transaction(provider, conn, hook, source_id=sid):
                hook.apply(provider, conn)
    finally:
        sys.setprofile(previous)
    assert observed == ["after-native-commit"] and caught.value is primary
    assert hook.commit_returned and not hook.rollback_completed and not conn.in_transaction
    assert provider._transaction_quarantine is provider._claim_tx_connection is provider._conn is conn
    assert provider._transaction_primary is primary and hook.outcome() == "unknown"
    observer = sqlite3.connect(str(provider.db_path), timeout=0)
    try:
        assert observer.execute("SELECT revision_key,content_hash FROM external_sources WHERE source_key=?", (hook.key,)).fetchone() == (hook.fields["revision_key"], hook.fields["content_hash"])
    finally:
        observer.close()


def test_H1_completed_private_hook_cannot_be_reused_as_writer_permission(store):
    provider, conn, sid, path, _, _ = cached(store)
    hook = record_hook(provider, conn, sid, path)
    with graph._ingest_transaction(provider, conn, hook, source_id=sid):
        hook.apply(provider, conn)
    before = image(conn)
    with pytest.raises(RuntimeError, match="hook_reused"):
        with graph._ingest_transaction(provider, conn, hook, source_id=sid):
            pytest.fail("used receipt admitted another record stage")
    assert image(conn) == before and provider._transaction_quarantine is None


def test_H2_cached_materialization_rebuild_saves_real_source_index_and_event(store, monkeypatch):
    provider, conn, sid, path, _, reference = cached(store)
    # Model a retained prior materialization in real SQL; the owner-local policy
    # snapshot intentionally ignores ambient env changes during this fixture.
    # The same typed authored cache is reused, with no fabricated worker reply.
    old_revision = "authored-prior-materialization"
    with provider._claim_transaction(conn):
        conn.execute("UPDATE document_revisions SET revision_id=? WHERE source_id=?", (old_revision, sid))
        for table in ("document_sources", "document_units", "document_chunks"):
            conn.execute("UPDATE " + table + " SET revision_id=? WHERE source_id=?", (old_revision, sid))
    result = graph.ingest_document(provider, {"path": str(path), "embed": False})
    assert result["status"] == "indexed" and result["revision_id"] != old_revision
    assert result["revision_id"] == reference["revision_id"]
    source = conn.execute("SELECT revision_id,file_hash FROM document_sources WHERE source_id=?", (sid,)).fetchone()
    assert tuple(source) == (result["revision_id"], result["file_hash"])
    assert conn.execute("SELECT COUNT(*) FROM document_units_fts WHERE source_id=?", (sid,)).fetchone()[0] == 1
    event = json.loads(conn.execute("SELECT result_json FROM document_events WHERE source_id=? AND event_type='ingest'", (sid,)).fetchone()[0])
    assert event["revision_id"] == result["revision_id"] and event["status"] == "indexed"
    assert conn.execute("PRAGMA quick_check").fetchone()[0] == "ok" and not conn.execute("PRAGMA foreign_key_check").fetchall()
    assert not conn.in_transaction and provider._transaction_quarantine is None


def test_H2_real_host_erasure_remains_retired_after_ordinary_cached_ingest(store):
    provider, helpers = store
    provider, conn, sid, path, _, _ = cached(store)
    phrase = helpers.SAFE_TEXT
    added = provider.on_memory_write("add", "document-intelligence", phrase, {})
    assert len(added["claim_ids"]) == 1 and added["claim_ids"][0].startswith("c_")
    cid = added["claim_ids"][0]
    with provider._claim_transaction(conn):
        conn.execute("UPDATE document_chunks SET embedding_claim_id=? WHERE source_id=?", (cid, sid))
    with observe_host_erasure(provider, helpers, cid) as observation:
        removed = provider.on_memory_write("remove", "document-intelligence", phrase, {})
    assert removed["claim_ids"] == [cid]
    ledger_before = provider._privacy_erasure.log_path.read_bytes()
    assert phrase.encode() not in ledger_before and cid.encode() not in ledger_before
    result = graph.ingest_document(provider, {"path": str(path), "embed": False})
    assert result["status"] == "unchanged"
    assert conn.execute("SELECT status FROM claims WHERE id=?", (cid,)).fetchone()[0] == "retired"
    assert conn.execute("SELECT embedding_claim_id FROM document_chunks WHERE source_id=?", (sid,)).fetchone()[0] == cid
    assert provider._privacy_erasure.log_path.read_bytes() == ledger_before
    assert not conn.in_transaction and provider._transaction_quarantine is None
    assert provider._lifecycle_state == "ready"
    assert observation["first_setter"] is None and not observation["connect_exceptions"]
    assert observation["ledger_owner_matches_authoritative_before"]
    assert observation["external_readback"] == {"claim_status": "retired", "applied_seq": "1", "claim_fts_count": 0}
    assert not removed["transaction_pending"] and removed["privacy_intent_durable"]


def test_H2_journal_preparation_cannot_change_authority_before_native_commit(store):
    provider, conn, sid, path, _, _ = cached(store, physical=False)
    key = external(provider, conn, sid, path)
    before = image(conn)
    target = wiki.MemoryWikiProvider._claim_journal_pending_commit.__wrapped__.__code__
    observed = []
    def profile(frame, event, arg):
        if event == "call" and frame.f_code is target and not observed:
            assert conn.in_transaction and provider._claim_tx_connection is conn
            observed.append("pending-journal")
            conn.execute("UPDATE external_sources SET owner_bot_id='foreign-callback' WHERE source_key=?", (key,))
    previous = sys.getprofile()
    try:
        sys.setprofile(profile)
        with pytest.raises(PermissionError, match="connector_source_not_owned"):
            graph.ingest_document(provider, {"path": str(path), "embed": False})
    finally:
        sys.setprofile(previous)
    assert observed == ["pending-journal"] and image(conn) == before
    assert not conn.in_transaction and provider._transaction_quarantine is None


@contextmanager
def observe_host_erasure(provider, helpers, cid):
    """Passive primitive-only causal trace; never changes production callbacks.

    Exact own fixture only. Actual SQL/native idle readback is separate from a
    printed exception and a durable ledger sequence. No text or ID is reported.
    """
    conn = provider._conn
    ledger = provider._privacy_erasure
    principal = wiki._memory_events._principal(provider, provider.session_id)
    expected_owner = {
        "bot": ledger.digest("owner-bot", provider.bot_id),
        "chat": ledger.digest("owner-chat", provider._chat_hash(provider.session_id)),
        "project": ledger.digest("owner-project", provider.project_scope or ""),
        "raw_session": ledger.digest("owner-raw-session", provider.session_id),
        "trusted_bot": bool(provider._bot_scope_trusted),
        "session": ledger.digest("owner-session", principal["session_hash"]),
    }
    facts = {"first_setter": None, "connect_exceptions": [], "native_boundaries": [],
             "call_error_type": None, "historical_failure_first_setter": None}
    codes = {wiki.MemoryWikiProvider._quarantine_claim_connection.__wrapped__.__code__: "quarantine",
             wiki.MemoryWikiProvider._connect.__wrapped__.__code__: "connect"}
    def snapshot():
        row = conn.execute("SELECT status FROM claims WHERE id=?", (cid,)).fetchone()
        seq = conn.execute("SELECT value FROM meta WHERE key='privacy_erasure_applied_seq'").fetchone()
        return {"lifecycle": provider._lifecycle_state, "native_active": conn.in_transaction,
                "registered_owner": provider._claim_tx_connection is conn,
                "same_thread": provider._claim_tx_thread == threading.get_ident(),
                "quarantine_exact": provider._transaction_quarantine is conn,
                "primary_retained": provider._transaction_primary is not None,
                "claim_status": row[0] if row else None, "applied_seq": seq[0] if seq else None}
    def trace(frame, event, arg):
        role = codes.get(frame.f_code)
        if role is None:
            return None
        if role == "quarantine" and event == "call" and facts["first_setter"] is None:
            stack, caller = [], frame.f_back
            for _ in range(14):
                if caller is None:
                    break
                stack.append({"function": caller.f_code.co_name, "line": caller.f_lineno})
                caller = caller.f_back
            facts["first_setter"] = {"code": frame.f_locals["code"],
                                     "before": snapshot(), "stack": stack}
        if role == "connect" and event == "exception" and len(facts["connect_exceptions"]) < 12:
            kind, error, _ = arg
            label = str(error) if kind is RuntimeError else None
            if label not in {"provider_transaction_owner_pending", "provider_lifecycle_not_ready"}:
                label = None
            facts["connect_exceptions"].append({"type": kind.__name__, "known_code": label})
        return trace
    def profile(frame, event, arg):
        if event in {"c_call", "c_return", "c_exception"} and getattr(arg, "__self__", None) is conn:
            name = getattr(arg, "__name__", "")
            if name in {"commit", "rollback", "__exit__"} and len(facts["native_boundaries"]) < 16:
                facts["native_boundaries"].append({"method": name, "event": event, "state": snapshot()})
    prior_trace, prior_profile = sys.gettrace(), sys.getprofile()
    assert prior_trace is None and prior_profile is None
    facts["before"] = snapshot()
    try:
        sys.settrace(trace)
        sys.setprofile(profile)
        yield facts
    except BaseException as error:
        facts["call_error_type"] = type(error).__name__
        raise
    finally:
        sys.setprofile(prior_profile)
        sys.settrace(prior_trace)
        facts["after"] = snapshot()
        observer = sqlite3.connect(str(provider.db_path), timeout=0)
        try:
            facts["external_readback"] = {
                "claim_status": observer.execute("SELECT status FROM claims WHERE id=?", (cid,)).fetchone()[0],
                "applied_seq": observer.execute("SELECT value FROM meta WHERE key='privacy_erasure_applied_seq'").fetchone()[0],
                "claim_fts_count": observer.execute("SELECT COUNT(*) FROM claims_fts WHERE id=?", (cid,)).fetchone()[0],
            }
        finally:
            observer.close()
        entries = ledger.load()
        facts["ledger_entries"] = len(entries)
        facts["ledger_owner_matches_authoritative_before"] = bool(entries and entries[-1]["owner"] == expected_owner)
        (helpers.OUT / "host-erasure-observation.json").write_text(
            json.dumps(facts, indent=2) + "\n", encoding="utf-8")


@pytest.fixture
def privacy_store(store, monkeypatch):
    """Explicit genuine new actor with enabled own event/episode policy.

    No model/extractor/callback is mocked; the inherited fixture's new root is
    archived only after the exact test-owned connections have been closed.
    """
    _, helpers = store
    for key, value in {"MEMORY_WIKI_EVENT_LEDGER_ENABLED": "1",
                       "MEMORY_WIKI_EVENT_SCOPE": "chat",
                       "MEMORY_WIKI_EPISODIC_ENABLED": "1",
                       "MEMORY_WIKI_EPISODIC_SCOPE": "chat",
                       "MEMORY_WIKI_OBSERVATIONS_ENABLED": "1"}.items():
        monkeypatch.setenv(key, value)
    provider = wiki.MemoryWikiProvider()
    provider.initialize("authored-privacy-chat", hermes_home=str(helpers.OUT / "privacy-home"),
                        agent_context="test", bot_id="synthetic-privacy-bot",
                        project_id="diagnostic", visibility_scope="chat")
    try:
        with wiki._native_profile_scope(provider.home), graph._document_profile_scope(provider.home):
            yield provider, helpers
    finally:
        if provider._transaction_quarantine is None:
            provider.shutdown()
        elif provider._conn is not None:
            # Only fixture teardown after retained UNKNOWN assertions. Never a
            # production close, state reset, safe retry or completion proof.
            provider._conn.set_authorizer(None)
            provider._conn.close()


def privacy_seed(provider, helpers):
    phrase = helpers.SAFE_TEXT
    added = provider.on_memory_write("add", "document-intelligence", phrase, {})
    cid = added["claim_ids"][0]
    eid = added["event_id"]
    episode = wiki._episodic_memory.capture_turn(provider, wiki, "user", phrase)
    assert cid.startswith("c_") and eid.startswith("evt_") and episode.startswith("ep_")
    conn = provider._connect()
    assert conn.execute("SELECT COUNT(*) FROM memory_observation_events WHERE event_id=?", (eid,)).fetchone()[0] == 1
    return conn, phrase, cid, eid, episode


def privacy_image(conn):
    """All synthetic SQL rows, including FTS/outbox/cache, as safe digests."""
    names = sorted(str(row[0]) for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"))
    assert all(name.isidentifier() for name in names)
    images = {}
    for name in names:
        values = sorted(repr(tuple(row)) for row in conn.execute('SELECT * FROM "' + name + '"'))
        images[name] = {"count": len(values), "sha256": hashlib.sha256("\n".join(values).encode()).hexdigest()}
    return images


def privacy_owner(provider):
    ledger = provider._privacy_erasure
    principal = wiki._memory_events._principal(provider, provider.session_id)
    return {"bot": ledger.digest("owner-bot", provider.bot_id),
            "chat": ledger.digest("owner-chat", provider._chat_hash(provider.session_id)),
            "project": ledger.digest("owner-project", provider.project_scope or ""),
            "raw_session": ledger.digest("owner-raw-session", provider.session_id),
            "trusted_bot": bool(provider._bot_scope_trusted),
            "session": ledger.digest("owner-session", principal["session_hash"])}


@contextmanager
def privacy_fault(function, primary, *, event="call"):
    """Bounded fault at the actual callable, never a replacement success."""
    target = getattr(function, "__wrapped__", function).__code__
    reached = []
    def profile(frame, kind, arg):
        if kind == event and frame.f_code is target and not reached:
            reached.append(kind)
            raise primary
    previous = sys.getprofile()
    assert previous is None
    try:
        sys.setprofile(profile)
        yield reached
    finally:
        sys.setprofile(previous)
    assert reached == [event]


def assert_privacy_pending_intent(provider, expected_owner, phrase, cid):
    entries = provider._privacy_erasure.load()
    assert len(entries) == 1 and entries[0]["seq"] == 1
    assert entries[0]["owner"] == expected_owner
    raw = provider._privacy_erasure.log_path.read_bytes()
    assert phrase.encode() not in raw and cid.encode() not in raw


def test_host_erasure_full_owned_privacy_flow_keeps_foreign_partition(privacy_store):
    provider, helpers = privacy_store
    conn, phrase, cid, eid, episode = privacy_seed(provider, helpers)
    expected_owner = privacy_owner(provider)
    foreign = wiki.MemoryWikiProvider()
    foreign.initialize("authored-foreign-chat", hermes_home=str(provider.home),
                       agent_context="test", bot_id="synthetic-foreign-bot", visibility_scope="chat")
    try:
        _, _, foreign_cid, foreign_eid, foreign_ep = privacy_seed(foreign, helpers)
        with provider._claim_transaction(conn):
            conn.execute("UPDATE meta SET value='1' WHERE key='semantic_enabled'")
        removed = provider.on_memory_write("remove", "document-intelligence", phrase, {})
        assert removed["claim_ids"] == [cid] and removed["count"] == removed["matched_count"] == 1
        assert removed["events_deleted"] == removed["observations_deleted"] == removed["episodes_deleted"] == 1
        assert not removed["transaction_pending"] and removed["privacy_intent_durable"]
        assert conn.execute("SELECT status FROM claims WHERE id=?", (cid,)).fetchone()[0] == "retired"
        assert conn.execute("SELECT status FROM claims WHERE id=?", (foreign_cid,)).fetchone()[0] == "active"
        assert conn.execute("SELECT 1 FROM memory_events WHERE event_id=?", (eid,)).fetchone() is None
        assert conn.execute("SELECT 1 FROM episodic_turns WHERE id=?", (episode,)).fetchone() is None
        assert conn.execute("SELECT 1 FROM memory_events WHERE event_id=?", (foreign_eid,)).fetchone()
        assert conn.execute("SELECT 1 FROM episodic_turns WHERE id=?", (foreign_ep,)).fetchone()
        assert not conn.execute("SELECT 1 FROM claims_fts WHERE id=?", (cid,)).fetchone()
        assert conn.execute("SELECT COUNT(*) FROM index_outbox WHERE object_type='claim' AND object_id=? AND operation='delete' AND status='pending'", (cid,)).fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM memory_events WHERE event_type='memory_mutation' AND provenance_json LIKE '%remove%'").fetchone()[0] == 0
        assert_privacy_pending_intent(provider, expected_owner, phrase, cid)
        assert not conn.in_transaction and provider._transaction_quarantine is None and provider._lifecycle_state == "ready"
    finally:
        foreign.shutdown()


@pytest.mark.parametrize("stage", ["before_intent", "after_intent"])
def test_host_erasure_intent_boundary_failure_rolls_back_all_sql_with_primary(privacy_store, stage):
    provider, helpers = privacy_store
    conn, phrase, cid, _, _ = privacy_seed(provider, helpers)
    before = privacy_image(conn)
    expected_owner = privacy_owner(provider)
    primary = ValueError("authored-privacy-intent-boundary")
    with privacy_fault(provider._privacy_erasure.append, primary,
                       event="call" if stage == "before_intent" else "return"):
        with pytest.raises(ValueError) as caught:
            provider.on_memory_write("remove", "document-intelligence", phrase, {})
    assert caught.value is primary and privacy_image(conn) == before
    assert not conn.in_transaction and provider._claim_tx_connection is None
    assert provider._transaction_quarantine is None and provider._lifecycle_state == "ready"
    if stage == "before_intent":
        assert provider._privacy_erasure.load() == []
    else:
        assert_privacy_pending_intent(provider, expected_owner, phrase, cid)
        replayed = provider._privacy_erasure.replay(provider, wiki)
        assert replayed == {"claims": 1, "events": 1, "episodes": 1}
        assert conn.execute("SELECT status FROM claims WHERE id=?", (cid,)).fetchone()[0] == "retired"


def test_host_erasure_commit_denial_keeps_atomic_sql_and_owner_intent_on_real_restart(privacy_store):
    provider, helpers = privacy_store
    conn, phrase, cid, _, _ = privacy_seed(provider, helpers)
    before = privacy_image(conn)
    expected_owner = privacy_owner(provider)
    tx_events = []
    def authorizer(action, a, b, database, trigger):
        if action == sqlite3.SQLITE_TRANSACTION:
            tx_events.append(a)
        return sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_TRANSACTION and a == "COMMIT" else sqlite3.SQLITE_OK
    conn.set_authorizer(authorizer)
    try:
        with pytest.raises(sqlite3.DatabaseError):
            provider.on_memory_write("remove", "document-intelligence", phrase, {})
    finally:
        conn.set_authorizer(None)
    assert tx_events == ["BEGIN", "COMMIT", "ROLLBACK"]
    assert privacy_image(conn) == before and not conn.in_transaction
    assert provider._transaction_quarantine is None and provider._claim_tx_connection is None
    assert_privacy_pending_intent(provider, expected_owner, phrase, cid)
    home, sid, bot, project = provider.home, provider.session_id, provider.bot_id, provider.project_scope
    provider.shutdown()
    restarted = wiki.MemoryWikiProvider()
    try:
        restarted.initialize(sid, hermes_home=str(home), agent_context="test",
                             bot_id=bot, project_id=project, visibility_scope="chat")
        actual = restarted._connect()
        assert actual.execute("SELECT status FROM claims WHERE id=?", (cid,)).fetchone()[0] == "retired"
        assert actual.execute("SELECT COUNT(*) FROM memory_events").fetchone()[0] == 0
        assert actual.execute("SELECT COUNT(*) FROM episodic_turns").fetchone()[0] == 0
        assert actual.execute("SELECT value FROM meta WHERE key='privacy_erasure_applied_seq'").fetchone()[0] == "1"
        assert restarted._lifecycle_state == "ready" and restarted._transaction_quarantine is None
    finally:
        restarted.shutdown()


def test_host_erasure_real_rollback_denial_retains_exact_owner_primary_and_unknown(privacy_store):
    provider, helpers = privacy_store
    conn, phrase, cid, _, _ = privacy_seed(provider, helpers)
    expected_owner = privacy_owner(provider)
    primary = ValueError("authored-privacy-rollback-primary")
    def authorizer(action, a, b, database, trigger):
        return sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_TRANSACTION and a == "ROLLBACK" else sqlite3.SQLITE_OK
    conn.set_authorizer(authorizer)
    try:
        with privacy_fault(provider._privacy_erasure.append, primary, event="return"):
            with pytest.raises(ValueError) as caught:
                provider.on_memory_write("remove", "document-intelligence", phrase, {})
        assert caught.value is primary and provider._transaction_primary is primary
        assert provider._conn is provider._owned_conn is provider._claim_tx_connection is provider._transaction_quarantine is conn
        assert conn.in_transaction and provider._lifecycle_state == "quarantined"
        assert any("UNKNOWN" in note for note in primary.__notes__)
        assert conn.execute("SELECT status FROM claims WHERE id=?", (cid,)).fetchone()[0] == "retired"
        observer = sqlite3.connect(str(provider.db_path), timeout=0)
        try:
            assert observer.execute("SELECT status FROM claims WHERE id=?", (cid,)).fetchone()[0] == "active"
        finally:
            observer.close()
        assert_privacy_pending_intent(provider, expected_owner, phrase, cid)
        with pytest.raises(RuntimeError, match="provider_lifecycle_not_ready"):
            provider._connect()
        assert not provider._release_connection_for_retry(primary)
    finally:
        conn.set_authorizer(None)  # Actual retained UNKNOWN asserted before fixture cleanup.


@pytest.mark.parametrize("boundary", ["owner_postcommit", "render_postcommit"])
def test_host_erasure_postcommit_failure_preserves_committed_sql_primary_and_unknown(privacy_store, boundary):
    provider, helpers = privacy_store
    conn, phrase, cid, eid, episode = privacy_seed(provider, helpers)
    expected_owner = privacy_owner(provider)
    primary = ValueError("authored-privacy-postcommit-primary")
    function = provider._claim_journal_committed if boundary == "owner_postcommit" else provider._render_all
    with privacy_fault(function, primary):
        with pytest.raises(ValueError) as caught:
            provider.on_memory_write("remove", "document-intelligence", phrase, {})
    assert caught.value is primary and provider._transaction_primary is primary
    assert provider._conn is provider._owned_conn is provider._transaction_quarantine is conn
    assert provider._lifecycle_state == "quarantined" and not conn.in_transaction
    if boundary == "owner_postcommit":
        assert provider._claim_tx_connection is conn
    assert any("UNKNOWN" in note for note in primary.__notes__)
    observer = sqlite3.connect(str(provider.db_path), timeout=0)
    try:
        assert observer.execute("SELECT status FROM claims WHERE id=?", (cid,)).fetchone()[0] == "retired"
        assert observer.execute("SELECT value FROM meta WHERE key='privacy_erasure_applied_seq'").fetchone()[0] == "1"
        assert observer.execute("SELECT 1 FROM memory_events WHERE event_id=?", (eid,)).fetchone() is None
        assert observer.execute("SELECT 1 FROM episodic_turns WHERE id=?", (episode,)).fetchone() is None
    finally:
        observer.close()
    assert_privacy_pending_intent(provider, expected_owner, phrase, cid)
    with pytest.raises(RuntimeError, match="provider_lifecycle_not_ready"):
        provider._connect()
    assert not provider._release_connection_for_retry(primary)


@pytest.mark.parametrize("outer", ["commit", "rollback"])
def test_host_erasure_legal_join_keeps_caller_native_commit_and_intent_lifetime(privacy_store, outer):
    provider, helpers = privacy_store
    conn, phrase, cid, _, _ = privacy_seed(provider, helpers)
    expected_owner = privacy_owner(provider)
    before = privacy_image(conn)
    observer = sqlite3.connect(str(provider.db_path), timeout=0)
    primary = ValueError("authored-privacy-outer-primary")
    post_calls = []
    targets = {provider._render_all.__wrapped__.__code__, provider._upsert_fts.__wrapped__.__code__}
    def profile(frame, event, arg):
        if event == "call" and frame.f_code in targets:
            post_calls.append(frame.f_code.co_name)
    def run():
        with provider._claim_transaction(conn):
            prior = sys.getprofile()
            try:
                sys.setprofile(profile)
                result = provider.on_memory_write("remove", "document-intelligence", phrase, {})
            finally:
                sys.setprofile(prior)
            assert not post_calls and result["transaction_pending"] and result["privacy_intent_durable"]
            assert conn.in_transaction and provider._claim_tx_connection is conn
            assert conn.execute("SELECT status FROM claims WHERE id=?", (cid,)).fetchone()[0] == "retired"
            assert observer.execute("SELECT status FROM claims WHERE id=?", (cid,)).fetchone()[0] == "active"
            if outer == "rollback":
                raise primary
    try:
        if outer == "rollback":
            with pytest.raises(ValueError) as caught:
                run()
            assert caught.value is primary and privacy_image(conn) == before
            assert observer.execute("SELECT status FROM claims WHERE id=?", (cid,)).fetchone()[0] == "active"
        else:
            run()
            assert observer.execute("SELECT status FROM claims WHERE id=?", (cid,)).fetchone()[0] == "retired"
    finally:
        observer.close()
    assert_privacy_pending_intent(provider, expected_owner, phrase, cid)
    assert not conn.in_transaction and provider._claim_tx_connection is None and provider._transaction_quarantine is None


def test_host_status_without_privacy_flag_is_retirement_not_hard_erasure(privacy_store):
    provider, helpers = privacy_store
    conn, phrase, cid, eid, episode = privacy_seed(provider, helpers)
    result = provider._set_status_by_text(phrase, "retired", "authored-status-only", erase_memory_events=False)
    assert result["claim_ids"] == [cid] and not result["privacy_intent_durable"] and not result["transaction_pending"]
    assert result["events_deleted"] == result["episodes_deleted"] == 0
    assert conn.execute("SELECT status,claim FROM claims WHERE id=?", (cid,)).fetchone()[0] == "retired"
    assert conn.execute("SELECT 1 FROM memory_events WHERE event_id=?", (eid,)).fetchone()
    assert conn.execute("SELECT 1 FROM episodic_turns WHERE id=?", (episode,)).fetchone()
    assert provider._privacy_erasure.load() == []
    assert not conn.in_transaction and provider._transaction_quarantine is None


def test_host_erasure_unregistered_native_transaction_is_refused_before_effect(privacy_store):
    provider, helpers = privacy_store
    conn, phrase, cid, _, _ = privacy_seed(provider, helpers)
    before = privacy_image(conn)
    conn.execute("BEGIN IMMEDIATE")  # Deliberately NOT a registered provider capability.
    with pytest.raises(RuntimeError, match="provider_transaction_owner_pending"):
        provider.on_memory_write("remove", "document-intelligence", phrase, {})
    assert privacy_image(conn) == before and conn.in_transaction
    assert conn.execute("SELECT status FROM claims WHERE id=?", (cid,)).fetchone()[0] == "active"
    assert provider._privacy_erasure.load() == []
    assert provider._transaction_quarantine is provider._owned_conn is provider._conn is conn
    assert provider._lifecycle_state == "quarantined" and provider._claim_tx_connection is None
    with pytest.raises(RuntimeError, match="provider_lifecycle_not_ready"):
        provider._connect()

