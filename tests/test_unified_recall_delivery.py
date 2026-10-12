"""Public direct-component recall delivery, with genuine SDK/trust and SQLite.

Synthetic authored stores only; no MemoryManager/bootstrap, remote services or
SDK substitutes. UNKNOWN teardown closes only the test-owned native handle and
never resets quarantine or claims that production recovered it.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import threading

import pytest
import memory_wiki as wiki
from agent.memory_provider import MemoryProvider
from tools.registry import tool_error, tool_result
from memory_wiki import recall_orchestrator
from memory_wiki.disclosure_fence import AUDIT_PREPARATION, DELIVERY, TerminalDelivery, current_delivery

QUERY = "Лазурный маяк керамические этикетки"
CLAIM = "Пользователь предпочитает овальные керамические этикетки для проекта Лазурный маяк."


@pytest.fixture
def owned(request, monkeypatch):
    for key, value in {
        "HERMES_SECURITY_STRICT": "0", "MEMORY_WIKI_STRICT_RECALL": "1",
        "MEMORY_WIKI_SEMANTIC": "0", "MEMORY_WIKI_RERANK_ENABLED": "0",
        "MEMORY_WIKI_EPISODIC_ENABLED": "0", "MEMORY_WIKI_EPISODIC_PREFETCH": "0",
        "MEMORY_WIKI_EVENTS_ENABLED": "0", "MEMORY_WIKI_OBSERVATIONS_ENABLED": "0",
        "MEMORY_WIKI_CODE_GRAPH_PREFETCH": "0", "MEMORY_WIKI_DOCUMENT_PREFETCH": "0",
        "MEMORY_WIKI_BACKGROUND_JOBS_ENABLED": "0",
        "MEMORY_WIKI_ONLINE_METRICS_ENABLED": "1", "MEMORY_WIKI_LLM_PACK": "0",
        "MEMORY_WIKI_INCLUDE_SESSIONS_IN_PACK": "0",
    }.items():
        monkeypatch.setenv(key, value)
    root = Path(os.environ["RECOVERY_DIAGNOSTIC_OUT"]) / "controls" / hashlib.sha256(
        request.node.nodeid.encode()).hexdigest()[:16]
    root.mkdir(parents=True, exist_ok=False)
    home = Path(os.environ["HERMES_HOME"]).resolve()
    # The real importer home is already credential-free and owned by the gate.
    # A different unconfigured home is deliberately profile_ready=False, so it
    # cannot be used as a healthy disclosure oracle. Keep unique chat partitions
    # in this synthetic store; close each exact fixture handle before the next.
    assert home == wiki._IMPORT_HERMES_HOME and home.parent == root.parents[2]
    with wiki._native_profile_scope(home):
        provider = wiki.MemoryWikiProvider()
        provider.initialize("unified-delivery-" + root.name, hermes_home=str(home),
                            agent_context="test", bot_id="synthetic-delivery-bot",
                            project_id="diagnostic", visibility_scope="chat")
        assert type(provider).__bases__ == (MemoryProvider,)
        assert wiki.tool_error is tool_error and wiki.tool_result is tool_result
        assert wiki._INJECTION_GUARD_AVAILABLE
        assert "agent.memory_manager" not in sys.modules
        saved = json.loads(provider.handle_tool_call("memory_wiki_add_claim", {
            "claim": CLAIM, "topic": "preferences", "evidence": CLAIM,
            "confidence": .8, "salience": .75,
        }))
        assert saved.get("state") == "stored" and saved.get("immediately_recallable") is True
        cid = saved["id"]
        conn = provider._conn
        assert conn is provider._owned_conn and not conn.in_transaction
        assert provider._transaction_quarantine is None and provider._lifecycle_state == "ready"
        try:
            yield provider, conn, cid
        finally:
            # Exact fixture ownership, after all retained-state assertions. This
            # is not a production shutdown/reconnect or UNKNOWN recovery.
            conn.set_authorizer(None)
            conn.close()
            with pytest.raises(sqlite3.ProgrammingError):
                conn.execute("SELECT 1")


def public(provider, *, mode="fast", name="memory_wiki_recall", **args):
    return json.loads(provider.handle_tool_call(name, {
        "query": QUERY, "mode": mode, "limit": 2, "max_chars": 1000, **args,
    }))


def accounting(conn, cid):
    return {
        "claim": tuple(conn.execute(
            "SELECT access_count,recall_count,last_recalled FROM claims WHERE id=?", (cid,)).fetchone()),
        "events": conn.execute("SELECT count(*) FROM recall_events WHERE claim_id=?", (cid,)).fetchone()[0],
        "feedback": conn.execute("SELECT count(*) FROM recall_feedback WHERE claim_id=?", (cid,)).fetchone()[0],
        "metrics": conn.execute("SELECT coalesce(sum(sample_count),0) FROM memory_online_metrics").fetchone()[0],
    }


def primitive(provider, conn):
    return {
        "lifecycle": provider._lifecycle_state,
        "quarantine_exact": provider._transaction_quarantine is conn,
        "primary_type": type(provider._transaction_primary).__name__ if provider._transaction_primary is not None else None,
        "cleanup_codes": list(provider._transaction_cleanup_notes),
        "native_transaction_active": conn.in_transaction,
        "owner_exact": provider._claim_tx_connection is conn,
        "owner_same_thread": provider._claim_tx_thread == threading.get_ident(),
    }


def observe(label, metadata):
    path = os.environ.get("UNIFIED_DELIVERY_DIAGNOSTIC_LOG")
    if path:
        with Path(path).open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"case": label, **metadata}, separators=(",", ":")) + "\n")


@contextmanager
def terminal_seam(provider, action, *, function=TerminalDelivery.commit):
    """Owned diagnostic seam on actual source code; no callable replacement."""
    target = function.__code__
    previous = sys.getprofile()
    observations = []
    def profile(frame, event, arg):
        if previous is not None:
            previous(frame, event, arg)
        if event == "call" and frame.f_code is target and frame.f_locals["self"].provider is provider:
            delivery = frame.f_locals["self"]
            observations.append({"phase": delivery.phase, "fences": len(delivery.fences),
                                 "effects": len(delivery.effects)})
            if len(observations) == 1:
                action(delivery)
    try:
        sys.setprofile(profile)
        yield observations
    finally:
        sys.setprofile(previous)


@pytest.mark.parametrize("entry", ["public", "orchestrator"])
def test_healthy_fast_recall_commits_exact_tracking_once(owned, entry):
    provider, conn, cid = owned
    before = accounting(conn, cid)
    deliveries = []
    def capture(delivery):
        assert delivery.phase == "prepare" and not conn.in_transaction
        for fence in delivery.fences:
            metadata = {"fence_ok": fence.ok, "fence_has_claims": bool(fence.purposes),
                        "epoch_same": hasattr(fence, "epoch") and fence.epoch == fence._epoch()}
            try:
                metadata["authority_same"] = fence.anchor == fence._authority()
            except Exception as exc:
                metadata["authority_error_type"] = type(exc).__name__
                metadata["authority_code"] = exc.args[0] if exc.args[0] in {
                    "disclosure_current_owner_unproven", "disclosure_request_owner_unproven",
                    "disclosure_owner_not_ready", "disclosure_existing_erasure_required",
                    "disclosure_erasure_owner_unproven"} else "unclassified"
            observe("healthy_precommit_" + entry, metadata)
        assert delivery.fences and delivery.effects
        assert current_delivery(provider) is delivery
        deliveries.append(delivery)
    with terminal_seam(provider, capture) as calls:
        payload = (public(provider) if entry == "public" else
                   recall_orchestrator.recall(provider, QUERY, mode="fast", limit=2, max_chars=1000))
    assert not payload.get("error") and payload.get("disclosure_status") != "withheld"
    assert payload["evidence_count"] == 1 and payload["items"][0]["id"] == cid
    assert CLAIM in payload["items"][0]["content"] and payload["chars_used"] <= 1000
    tracking = payload["recall_tracking"]
    assert tracking["status"] == "ok" and len(tracking["events"]) == 1
    event_id = tracking["events"][0]["recall_event_id"]
    assert payload["items"][0]["recall_event_id"] == event_id
    assert tracking["answer_linkage"]["claim_ids"] == [cid]
    assert tracking["answer_linkage"]["recall_event_ids"] == [event_id]
    after = accounting(conn, cid)
    assert after["claim"][0] == before["claim"][0] + 1
    assert after["claim"][1] == before["claim"][1] + 1
    assert after["events"] == before["events"] + 1
    assert after["feedback"] == before["feedback"] + 1
    assert tuple(conn.execute("SELECT claim_id,used,outcome FROM recall_events WHERE id=?", (event_id,)).fetchone()) == (cid, -1, "pending")
    assert tuple(conn.execute("SELECT claim_id,used,helpful,outcome FROM recall_feedback WHERE recall_event_id=?", (event_id,)).fetchone()) == (cid, 0, 0.0, "neutral")
    assert len(calls) == len(deliveries) == 1
    delivery = deliveries[0]
    assert delivery.phase == "committed" and delivery.measurement["commit_returned"] is True
    assert delivery.measurement["native_idle"] is True
    assert provider._conn is conn is provider._owned_conn and not conn.in_transaction
    assert provider._claim_tx_connection is None and provider._claim_tx_thread is None
    assert provider._transaction_quarantine is None and provider._lifecycle_state == "ready"
    assert current_delivery(provider) is None
    if entry == "public":
        assert after["metrics"] == before["metrics"] + 1
        receipt = payload["retrieval_receipt"]
        assert receipt["final"]["emitted_claim_count"] == 1
        assert receipt["searches"] and all(s["requested_mode"] == "fts" for s in receipt["searches"])
    observe("healthy_" + entry, {"terminal_calls": len(calls), "committed": True, **primitive(provider, conn)})


def test_foreign_pending_public_recall_preserves_causal_error_and_retained_owner(owned):
    provider, conn, cid = owned
    before = accounting(conn, cid)
    conn.execute("BEGIN IMMEDIATE")  # Genuine unregistered native stage, not a flag.
    assert provider._claim_tx_connection is None and conn.in_transaction
    failure = None
    try:
        with terminal_seam(provider, lambda delivery: None) as calls:
            payload = public(provider)
    except Exception as exc:
        failure = type(exc).__name__
        observe("foreign_pending_baseline", {"raised_type": failure, "exact_terminal_unknown": exc.args == ("terminal_owner_quarantine_UNKNOWN",), "terminal_calls": calls, **primitive(provider, conn)})
        raise
    assert payload == json.loads(tool_error("provider_transaction_owner_pending; transaction outcome UNKNOWN"))
    assert calls == []  # A failure is not disclosure to admit or to replace.
    assert accounting(conn, cid) == before
    assert provider._transaction_quarantine is conn and provider._transaction_primary is None
    assert provider._conn is conn is provider._owned_conn and conn.in_transaction
    assert "tool_pending_transaction" in provider._transaction_cleanup_notes
    assert provider._lifecycle_state == "quarantined"
    repeated = public(provider)
    assert repeated == json.loads(tool_error("provider_lifecycle_not_ready; transaction outcome UNKNOWN"))
    assert provider._transaction_quarantine is conn and conn.in_transaction
    with pytest.raises(RuntimeError, match="provider_lifecycle_not_ready"):
        provider._connect()
    assert accounting(conn, cid) == before and current_delivery(provider) is None
    observe("foreign_pending_preserved", {"terminal_calls": 0, **primitive(provider, conn)})


def test_validation_failure_is_not_successful_withheld_recall(owned):
    provider, conn, cid = owned
    before = accounting(conn, cid)
    with terminal_seam(provider, lambda delivery: None) as calls:
        payload = public(provider, mode="invalid")
    assert payload == json.loads(tool_error("ValueError"))
    assert calls == []
    assert accounting(conn, cid) == before and not conn.in_transaction
    assert provider._transaction_quarantine is None and current_delivery(provider) is None


@pytest.mark.parametrize("when", ["before_call", "terminal"])
def test_native_rollback_denial_public_error_retains_exact_primary_and_unknown(owned, when):
    provider, conn, cid = owned
    before = accounting(conn, cid)
    primary = RuntimeError("synthetic-private-exception-payload-must-not-cross-tool-boundary")
    denied = []
    def deny_rollback(action, first, second, database, trigger):
        if action == sqlite3.SQLITE_TRANSACTION and first == "ROLLBACK":
            denied.append(first)
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK
    def retain(delivery=None):
        conn.set_authorizer(deny_rollback)
        with pytest.raises(RuntimeError) as caught:
            with provider._claim_transaction(conn):
                raise primary
        assert caught.value is primary
        assert denied == ["ROLLBACK"]
        assert provider._transaction_primary is primary and provider._transaction_quarantine is conn
        assert provider._claim_tx_connection is conn and provider._claim_tx_thread == threading.get_ident()
        assert conn.in_transaction and "rollback_DatabaseError" in provider._transaction_cleanup_notes
        assert any("outcome=UNKNOWN" in n for n in primary.__notes__)
        observe("rollback_denied_" + when, primitive(provider, conn))
    if when == "before_call":
        retain()
        payload = public(provider)
    else:
        with terminal_seam(provider, retain) as calls:
            payload = public(provider)
        assert len(calls) == 1
    assert payload.get("error") and "RuntimeError" in payload["error"] and "UNKNOWN" in payload["error"]
    assert "synthetic-private-exception-payload" not in json.dumps(payload)
    assert not payload.get("items") and "recall_tracking" not in payload and "retrieval_receipt" not in payload
    assert provider._transaction_primary is primary and provider._transaction_quarantine is conn
    assert provider._conn is conn is provider._owned_conn and conn.in_transaction
    assert provider._claim_tx_connection is conn and provider._claim_tx_thread == threading.get_ident()
    assert accounting(conn, cid) == before
    for call in (provider._connect, provider.shutdown, lambda: provider.initialize("must-not-replace")):
        with pytest.raises(RuntimeError):
            call()
    assert provider._release_connection_for_retry(primary) is False
    assert provider._transaction_primary is primary and provider._transaction_quarantine is conn
    repeated = public(provider)
    assert repeated.get("error") and "RuntimeError" in repeated["error"] and "UNKNOWN" in repeated["error"]
    assert current_delivery(provider) is None and accounting(conn, cid) == before


def test_terminal_without_primary_still_refuses_genuine_unknown(owned):
    provider, conn, cid = owned
    before = accounting(conn, cid)
    conn.execute("BEGIN IMMEDIATE")
    with pytest.raises(RuntimeError, match="provider_transaction_owner_pending"):
        provider._connect()
    delivery = TerminalDelivery(provider)
    with pytest.raises(RuntimeError, match="^terminal_owner_quarantine_UNKNOWN$"):
        delivery.commit()
    assert provider._transaction_quarantine is conn and provider._transaction_primary is None
    assert provider._conn is conn is provider._owned_conn and conn.in_transaction
    assert accounting(conn, cid) == before
    observe("genuine_unknown_not_relaxed", primitive(provider, conn))


@pytest.mark.parametrize("name", ["memory_wiki_recall", "memory_wiki_query", "memory_wiki_document_query"])
def test_explicit_failure_envelope_is_preserved_byte_exact_without_terminal_commit(owned, name):
    provider, conn, cid = owned
    args = {"query": QUERY, "__journal_capture_id": "untrusted-control"}
    expected = wiki.MemoryWikiProvider.handle_tool_call.__wrapped__(provider, name, args)
    assert json.loads(expected)["success"] is False
    before = accounting(conn, cid)
    with terminal_seam(provider, lambda delivery: None) as calls:
        delivered = provider.handle_tool_call(name, args)
    assert delivered == expected and calls == []
    assert accounting(conn, cid) == before and not conn.in_transaction
    assert provider._transaction_quarantine is None and current_delivery(provider) is None


@pytest.mark.parametrize("unknown", [False, True])
def test_discarded_real_audit_preparation_never_commits_intents(owned, unknown):
    provider, conn, cid = owned
    before = accounting(conn, cid)
    audits = conn.execute("SELECT count(*) FROM audit_log").fetchone()[0]
    delivery = TerminalDelivery(provider)
    token = DELIVERY.set(delivery)
    try:
        cancel = threading.Event()
        staged = delivery.detach_audits(provider.session_id, cancel)
        errors = []
        def worker():
            audit_token = AUDIT_PREPARATION.set(staged)
            try:
                staged.bind_worker()
                provider._audit("synthetic_delivery", "ok", "authored test audit")
                staged.seal()
            except BaseException as exc:
                errors.append(type(exc).__name__)
            finally:
                AUDIT_PREPARATION.reset(audit_token)
        thread = threading.Thread(target=worker, name="owned-discarded-audit", daemon=False)
        thread.start()
        thread.join(3)
        assert not thread.is_alive() and errors == []
        assert staged.outcome == "prepared" and staged.prepared_count == 1
        delivery.adopt_audits(staged)
        assert staged.outcome == "queued" and len(delivery.effects) == 1
        if unknown:
            conn.execute("BEGIN IMMEDIATE")
            with pytest.raises(RuntimeError, match="provider_transaction_owner_pending"):
                provider._connect()
        delivery.discard_preparation()
        assert staged.outcome == ("unknown" if unknown else "withheld")
        assert staged.persisted_count == (None if unknown else 0)
        assert delivery.phase == ("unknown" if unknown else "withheld")
        assert delivery.reason == "terminal_error_response"
        with pytest.raises(wiki._DeliveryWithheld, match="terminal_preparation_already_finished"):
            delivery.discard_preparation()
        if unknown:
            with pytest.raises(RuntimeError, match="terminal_owner_quarantine_UNKNOWN"):
                delivery.commit()
            assert provider._transaction_quarantine is conn and conn.in_transaction
        else:
            assert delivery.commit() is False and not conn.in_transaction
        assert conn.execute("SELECT count(*) FROM audit_log").fetchone()[0] == audits
        assert accounting(conn, cid) == before
    finally:
        DELIVERY.reset(token)


def test_native_unaccounted_trigger_still_withholds_and_rolls_back(owned):
    provider, conn, cid = owned
    with provider._claim_transaction(conn):
        conn.execute("CREATE TRIGGER owned_delivery_extra_effect AFTER UPDATE OF access_count ON claims BEGIN INSERT OR REPLACE INTO meta(key,value) VALUES('owned_unaccounted','1'); END")
    before = accounting(conn, cid)
    try:
        payload = public(provider)
        assert payload.get("success") is True and payload["disclosure_status"] == "withheld"
        assert not payload.get("items") and not payload.get("error")
        assert payload["recall_tracking"]["events"] == []
        assert payload["retrieval_receipt"]["searches"] == []
        assert accounting(conn, cid) == before
        assert conn.execute("SELECT 1 FROM meta WHERE key='owned_unaccounted'").fetchone() is None
        assert not conn.in_transaction and provider._transaction_quarantine is None
    finally:
        with provider._claim_transaction(conn):
            conn.execute("DROP TRIGGER owned_delivery_extra_effect")
    assert public(provider).get("items")


def test_primary_baseexception_at_effect_seam_propagates_with_known_rollback(owned):
    provider, conn, cid = owned
    before = accounting(conn, cid)
    primary = KeyboardInterrupt("owned-terminal-cancellation")
    def cancel(delivery):
        assert delivery.phase == "owned" and conn.in_transaction
        assert delivery.owns_snapshot(delivery.fences[0])
        raise primary
    with pytest.raises(KeyboardInterrupt) as caught:
        with terminal_seam(provider, cancel, function=TerminalDelivery._apply):
            public(provider)
    assert caught.value is primary
    assert not conn.in_transaction and provider._transaction_quarantine is None
    assert provider._claim_tx_connection is None and provider._claim_tx_thread is None
    assert accounting(conn, cid) == before and current_delivery(provider) is None
    assert public(provider).get("items")


@pytest.mark.parametrize("entry", ["public", "orchestrator"])
def test_foreign_original_caller_home_cannot_be_adopted_for_direct_recall(owned, entry):
    provider, conn, cid = owned
    before = accounting(conn, cid)
    foreign_home = Path(os.environ["TMPDIR"]) / "foreign-original-caller"
    with wiki._native_profile_scope(foreign_home):
        payload = (public(provider) if entry == "public" else
                   recall_orchestrator.recall(provider, QUERY, mode="fast", limit=2, max_chars=1000))
    assert not payload.get("items") and payload.get("disclosure_status") == "withheld"
    assert accounting(conn, cid) == before and not conn.in_transaction
    assert provider._transaction_quarantine is None and current_delivery(provider) is None


def test_public_fast_recall_after_real_stale_fts_rebuild_remains_healthy(owned):
    provider, conn, cid = owned
    with provider._claim_transaction(conn):
        conn.execute("DELETE FROM claims_fts")
        conn.execute("UPDATE meta SET value='stale' WHERE key='claims_fts_format'")
    before = accounting(conn, cid)
    payload = public(provider)
    assert not payload.get("error") and payload.get("items")
    assert payload["items"][0]["id"] == cid and payload.get("disclosure_status") != "withheld"
    assert conn.execute("SELECT value FROM meta WHERE key='claims_fts_format'").fetchone()[0] == "v3"
    assert accounting(conn, cid)["events"] == before["events"] + 1
    assert not conn.in_transaction and provider._transaction_quarantine is None
