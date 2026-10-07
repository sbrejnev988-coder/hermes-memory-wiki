"""F1/F2/F3 only: real native SDK/guard and SQLite FTS, offline fixtures.

Embedding transport timeouts below are explicitly simulated, not provider or
live-gateway measurements. The producer and cache code themselves are real.
"""
from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
import memory_wiki as mw
from test_hybrid_runtime_receipts import fleet, seed, install_transport


@pytest.mark.parametrize("mode", ["fts", "hybrid"])
def test_topic_filtered_real_fts_or_branch_and_acl(fleet, mode):
    _, providers = fleet
    p = providers["default"]
    visible = seed(p, "c_topic_visible", "Synthetic orchid repository preference uses local backups.")
    seed(p, "c_topic_hidden", "Synthetic orchid repository preference uses local backups.", "private", owner="foreign")
    other = seed(p, "c_topic_other", "Synthetic orchid repository preference uses local backups.")
    db = p._connect()
    with db:
        db.execute("UPDATE claims SET topic='other' WHERE id=?", (other,))
    p._upsert_fts(other)
    # The topic UPDATE intentionally marks the real shared index stale.
    # Prepare a healthy v3 fixture before exercising the read-only branch.
    p._ensure_fts_current()
    assert db.execute("SELECT value FROM meta WHERE key='claims_fts_format'").fetchone()[0] == "v3"
    assert {r[1] for r in db.execute("PRAGMA table_info(claims_fts)")} >= {"topic", "claim", "evidence"}
    statements = []
    db.set_trace_callback(statements.append)
    db.execute("PRAGMA query_only=ON")
    root = mw._new_recall_request(p, "synthetic_findings")
    token = mw._RECALL_REQUEST.set(root)
    try:
        # AND has zero hits and full-phrase LIKE has zero hits. OR must still
        # supply a real BM25/RRF contribution without admitting hidden rows.
        rows = p._search("orchid absent", topic="testing", include_stale=False,
                         retrieval_mode=mode, record_retrieval=False, conn=db)
    finally:
        mw._RECALL_REQUEST.reset(token)
        db.set_trace_callback(None)
        db.execute("PRAGMA query_only=OFF")
    assert [r["id"] for r in rows] == [visible]
    assert [r["id"] for r in p._model_safe_claim_rows(rows)] == [visible]
    s = root["searches"][0]
    assert s["lexical"]["status"] == "executed"
    assert s["lexical"]["kind"] == "fts5"
    assert s["lexical"]["reason"] == ""
    assert s["fusion"]["lexical_count"] == 1
    assert s["fusion"]["like_count"] == 0
    assert s["fusion"]["items"][0]["lexical_contribution"] > 0
    joins = [sql for sql in statements if "FROM claims_fts JOIN claims" in sql]
    assert len(joins) == 2 and all("claims.topic='testing'" in sql for sql in joins)
    # Empty topic remains a valid no-filter positive control on the same DB.
    assert {r["id"] for r in p._search("orchid", topic="", retrieval_mode="fts", record_retrieval=False)} == {visible, other}


@pytest.mark.parametrize("tool_name", ["memory_wiki_query", "memory_wiki_recall"])
def test_keyword_canonical_root_matches_actual_positional_and_mixed_calls(fleet, monkeypatch, tool_name):
    _, providers = fleet
    p = providers["default"]
    cid = seed(p, "c_keyword", "Synthetic orchid repository preference uses local backups.")
    roots = []
    actual = mw._new_recall_request
    def observe(provider, entrypoint):
        root = actual(provider, entrypoint)
        roots.append(root)
        return root
    monkeypatch.setattr(mw, "_new_recall_request", observe)
    receipts = []
    for form in ("keyword", "positional", "mixed"):
        args = {"query": "orchid", "topic": "testing", "mode": "auto", "limit": 1}
        if form == "keyword":
            raw = p.handle_tool_call(tool_name=tool_name, args=args, session_id=p.session_id)
        elif form == "positional":
            raw = p.handle_tool_call(tool_name, args, session_id=p.session_id)
        else:
            raw = p.handle_tool_call(tool_name, args=args, session_id=p.session_id)
        result = json.loads(raw)
        assert result["success"] is True
        receipt = result["retrieval_receipt"]
        assert receipt["entrypoint"] == tool_name
        assert receipt["trace_id"] == roots[-1]["trace_id"]
        assert receipt["searches"] and receipt["final"]["emitted_claim_count"] == 1
        assert receipt["searches"][0]["lexical"]["kind"] == "fts5"
        assert receipt["identity"]["provider_home"] == str(p.home)
        assert receipt["identity"]["conn_path_matches"] is True
        field = "claims" if tool_name == "memory_wiki_query" else "items"
        assert cid in {r.get("id") for r in result[field]}
        assert "orchid" not in json.dumps(receipt)
        assert mw._RECALL_REQUEST.get() is None and mw._SEARCH_RECEIPT.get() is None
        receipts.append(receipt)
    assert len(roots) == 3 and len({r["trace_id"] for r in receipts}) == 3


def test_duplicate_keyword_binding_still_raises_and_restores_scopes(fleet):
    _, providers = fleet
    p = providers["default"]
    before = p._connect().total_changes
    with pytest.raises(TypeError, match="multiple values for argument 'tool_name'"):
        p.handle_tool_call("memory_wiki_query", {}, tool_name="memory_wiki_recall")
    with pytest.raises(TypeError, match="multiple values for argument 'args'"):
        p.handle_tool_call("memory_wiki_query", {}, args={"query": "orchid"})
    with pytest.raises(TypeError, match="missing.*args"):
        p.handle_tool_call(tool_name="memory_wiki_query")
    assert p._connect().total_changes == before
    assert mw._RECALL_REQUEST.get() is None and mw._SEARCH_RECEIPT.get() is None
    assert mw._REQUEST_HOME.get() is None


@pytest.mark.parametrize("cache_entries", [0, 16])
def test_actual_embedding_producer_timeout_survives_canonical_receipt(fleet, monkeypatch, cache_entries):
    _, providers = fleet
    p = providers["default"]
    seed(p, "c_embed_timeout", "Synthetic orchid repository preference uses local backups.")
    monkeypatch.setattr(mw, "EMBED_CACHE_MAX_ENTRIES", cache_entries)
    mw._embedding_cache_clear(reset_metrics=True)
    calls = []
    install_transport(monkeypatch, [], calls, embed_failure=TimeoutError("explicit synthetic embedding timeout"))
    result = json.loads(p.handle_tool_call(tool_name="memory_wiki_query", args={"query": "orchid"}))
    s = result["retrieval_receipt"]["searches"][0]
    assert s["embedding"]["status"] == "timeout"
    assert s["embedding"]["reason"] == "TimeoutError"
    assert s["qdrant"]["status"] == "not_run"
    assert s["qdrant"]["reason"] == "embedding_failed"
    assert s["effective_mode"] == "fts_only"
    assert result["claims"] and any(kind == "embedding" for kind, _ in calls)
    assert not any(kind == "qdrant" for kind, _ in calls)
    assert mw._SEARCH_RECEIPT.get() is None


def run_coalesced(home, monkeypatch, invoke, entered, release, *, invalidate=False):
    """Wait for a real shared flight; no timing-dependent poll or Event stub."""
    coalesced = threading.Event()
    waiter_stage = {"embedding": {}}
    def owner():
        # The owner intentionally has no request collector. Its actual producer
        # outcome must still reach the request-scoped coalesced waiter.
        assert mw._SEARCH_RECEIPT.get() is None
        with mw._profile_qdrant_scope(home):
            try:
                return invoke(), None
            except (TimeoutError, ValueError) as exc:
                return None, type(exc).__name__
    def waiter():
        token = mw._SEARCH_RECEIPT.set(waiter_stage)
        try:
            with mw._profile_qdrant_scope(home):
                return invoke()
        finally:
            mw._SEARCH_RECEIPT.reset(token)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(owner)
        try:
            assert entered.wait(5)
            with mw._profile_qdrant_scope(home), mw._EMBED_CACHE_LOCK:
                flight = next(iter(mw._embedding_cache_state()["flights"].values()))
            actual_wait = flight["event"].wait
            def observe_wait(timeout=None):
                coalesced.set()
                return actual_wait(timeout)
            monkeypatch.setattr(flight["event"], "wait", observe_wait)
            second = pool.submit(waiter)
            assert coalesced.wait(5)
            if invalidate:
                mw._embedding_cache_clear()
        finally:
            release.set()
        owner_result, owner_error = first.result(timeout=6)
        waiter_result = second.result(timeout=6)
    return owner_result, owner_error, waiter_result, waiter_stage["embedding"]


def test_coalesced_actual_embedding_timeout_without_owner_collector(fleet, monkeypatch):
    homes, _ = fleet
    monkeypatch.setattr(mw, "EMBED_CACHE_MAX_ENTRIES", 16)
    mw._embedding_cache_clear(reset_metrics=True)
    calls = []
    install_transport(monkeypatch, [], calls, embed_failure=TimeoutError("explicit synthetic embedding timeout"))
    actual = mw._urlopen_no_redirect
    entered = threading.Event(); release = threading.Event()
    def blocked_transport(req, timeout=1):
        assert req.full_url.endswith("/embeddings")
        entered.set()
        assert release.wait(5)
        return actual(req, timeout)
    monkeypatch.setattr(mw, "_urlopen_no_redirect", blocked_transport)
    owner, error, waiter, stage = run_coalesced(homes["default"], monkeypatch,
        lambda: mw._embed_query("synthetic shared embedding timeout"), entered, release)
    assert owner is None and waiter is None and error is None
    assert stage["status"] == "timeout" and stage["reason"] == "TimeoutError"
    assert len(calls) == 2  # one real producer's ordinary two attempts, not two producers


@pytest.mark.parametrize("outcome", ["success", "timeout", "failed"])
def test_coalesced_positive_and_raised_failure_controls(fleet, monkeypatch, outcome):
    homes, _ = fleet
    monkeypatch.setattr(mw, "EMBED_CACHE_MAX_ENTRIES", 16)
    mw._embedding_cache_clear(reset_metrics=True)
    entered = threading.Event(); release = threading.Event()
    calls = []
    def producer(_):
        calls.append(1)
        entered.set()
        assert release.wait(5)
        if outcome == "timeout":
            raise TimeoutError("explicit synthetic producer exception")
        if outcome == "failed":
            raise ValueError("explicit synthetic producer exception")
        return [.01] * mw.QDRANT_VECTOR_SIZE
    owner, error, waiter, stage = run_coalesced(homes["default"], monkeypatch,
        lambda: mw._embedding_cached_call("synthetic shared control", "search_query", producer), entered, release)
    assert calls == [1]
    if outcome == "success":
        assert owner == waiter == [.01] * mw.QDRANT_VECTOR_SIZE and error is None
        assert stage["status"] == "coalesced" and stage["reason"] == ""
    else:
        assert owner is None and waiter is None
        assert error == ("TimeoutError" if outcome == "timeout" else "ValueError")
        assert stage["status"] == outcome and stage["reason"] == error


def test_generation_invalidated_flight_reports_invalidation_not_timeout(fleet, monkeypatch):
    homes, _ = fleet
    monkeypatch.setattr(mw, "EMBED_CACHE_MAX_ENTRIES", 16)
    mw._embedding_cache_clear(reset_metrics=True)
    entered = threading.Event(); release = threading.Event()
    def producer(_):
        entered.set()
        assert release.wait(5)
        mw._stage_receipt("embedding", "timeout", "deadline")
        return None
    owner, error, waiter, stage = run_coalesced(homes["default"], monkeypatch,
        lambda: mw._embedding_cached_call("synthetic invalidated flight", "search_query", producer),
        entered, release, invalidate=True)
    assert owner is None and waiter is None and error is None
    assert stage["status"] == "failed" and stage["reason"] == "generation_invalidated"


@pytest.mark.parametrize("cache_entries", [0, 16])
def test_success_empty_generic_failure_and_deadline_boundary_controls(fleet, monkeypatch, cache_entries):
    homes, _ = fleet
    monkeypatch.setattr(mw, "EMBED_CACHE_MAX_ENTRIES", cache_entries)
    mw._embedding_cache_clear(reset_metrics=True)
    child = {"embedding": {}}
    token = mw._SEARCH_RECEIPT.set(child)
    try:
        with mw._profile_qdrant_scope(homes["default"]):
            def deadline(_):
                mw._stage_receipt("embedding", "timeout", "deadline")
                return None
            assert mw._embedding_cached_call("synthetic deadline", "search_query", deadline) is None
            assert child["embedding"]["status"] == "timeout" and child["embedding"]["reason"] == "deadline"
            # A fresh empty producer must not inherit the preceding timeout.
            assert mw._embedding_cached_call("synthetic empty", "search_query", lambda _: None) is None
            assert child["embedding"]["status"] == "failed" and child["embedding"]["reason"] == "embedding_unavailable"
            assert mw._embedding_cached_call("  ", "search_query", lambda _: pytest.fail("empty input ran producer")) is None
            assert child["embedding"]["status"] == "not_run" and child["embedding"]["reason"] == "empty_query"
            calls = []
            def success(_):
                calls.append(1)
                return [.01] * mw.QDRANT_VECTOR_SIZE
            for expected in ("executed", "cache_hit" if cache_entries else "executed"):
                assert mw._embedding_cached_call("synthetic success", "search_query", success) == [.01] * mw.QDRANT_VECTOR_SIZE
                assert child["embedding"]["status"] == expected
                assert child["embedding"]["reason"] == ("cache_disabled" if not cache_entries else "")
            assert len(calls) == (1 if cache_entries else 2)
    finally:
        mw._SEARCH_RECEIPT.reset(token)
    assert mw._SEARCH_RECEIPT.get() is None
