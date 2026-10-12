"""Authored offline ordering fixtures, NOT captured provider-quality traces.

Exercise the real plugin, SQLite/FTS and recall guards with a deliberately primed
rank cache. No fake successful HTTP/model response and no provider request.
The ordinary direct-component runner supplies the genuine public base SPI.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time

import pytest
import memory_wiki as mw
from hermes_constants import set_hermes_home_override, reset_hermes_home_override


@pytest.fixture
def order_case(monkeypatch, request):
    from agent.memory_provider import MemoryProvider

    assert mw.MemoryWikiProvider.__bases__ == (MemoryProvider,)
    assert mw._INJECTION_GUARD_AVAILABLE
    monkeypatch.setattr(mw, "SEMANTIC_ENABLED", False)
    monkeypatch.setenv("MEMORY_WIKI_BACKGROUND_JOBS_ENABLED", "0")
    monkeypatch.setenv("MEMORY_WIKI_DOCUMENT_CACHE_ENABLED", "0")
    monkeypatch.setenv("MEMORY_WIKI_DOCUMENT_ROOTS", "")
    monkeypatch.setenv("HERMES_SECURITY_STRICT", "1")
    monkeypatch.setattr(mw, "RRF_K", 10)
    monkeypatch.setattr(mw, "DIVERSITY_MAX_PER_TOPIC", 100)
    monkeypatch.setattr(mw, "_rerank_api_key", lambda: "offline-fixture-not-a-provider")
    owned_root = os.environ.get("MEMORY_WIKI_RERANK_TEST_ROOT")
    if owned_root:
        home = (Path(owned_root) / "diagnostics" / "controls" /
                hashlib.sha256(request.node.nodeid.encode()).hexdigest()[:16])
    else:
        import tempfile
        home = Path(tempfile.mkdtemp(prefix="rerank-order-", dir=os.environ["TMPDIR"]))
    home.mkdir(parents=True, exist_ok=True)
    home_token = set_hermes_home_override(home)
    scope = {
        "__home": str(home.resolve()),
        "MEMORY_WIKI_RERANK_ENABLED": "1",
        "MEMORY_WIKI_RERANK_URL": "https://openrouter.ai/api/v1/rerank",
        "MEMORY_WIKI_RERANK_MODEL": "voyageai/rerank-3",
        "MEMORY_WIKI_RERANK_TOP_K": "48",
        "MEMORY_WIKI_RERANK_MIN_CANDIDATES": "10",
        "MEMORY_WIKI_RERANK_WEIGHT_SEMANTIC": "0.75",
        "MEMORY_WIKI_RERANK_RULES_ENABLED": "0",
        "MEMORY_WIKI_RERANK_CACHE_TTL": "1800",
    }
    scope_token = mw._QDRANT_PROFILE_SCOPE.set(scope)
    provider = mw.MemoryWikiProvider()
    provider.initialize("offline-order", hermes_home=str(home), bot_id="order-owner", project_id="order-project")
    conn = provider._connect()
    attempts = []

    def deny_transport(*_args, **_kwargs):
        attempts.append("denied-before-HTTP")
        raise TimeoutError("authored offline transport refusal")

    monkeypatch.setattr(mw, "_urlopen_no_redirect", deny_transport)
    try:
        yield provider, scope, attempts
    finally:
        provider.shutdown()
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            conn.execute("SELECT 1")
        mw._QDRANT_PROFILE_SCOPE.reset(scope_token)
        reset_hermes_home_override(home_token)


def _rows(count=48):
    return [
        {"id": f"order-{i:02d}", "claim": f"Authored durable retrieval ordering fixture number {i} describes a harmless local backup policy.",
         "topic": "ordering", "status": "active", "risk": "low", "trust_class": "fact", "updated_at": 1,
         "score": float(count - i), "score_parts": {"rrf": 0.0123}}
        for i in range(1, count + 1)
    ]


def _ranks(rows, winner_index=14):
    ordered = [rows[winner_index], *rows[:winner_index], *rows[winner_index + 1:]]
    return [(str(row["id"]), 1.0 - rank / 100.0, rank) for rank, row in enumerate(ordered, 1)]


def _prime(query, rows, ranks, mode="semantic"):
    """Insert declared numerical rank inputs, not a pretend provider response.

    Use the actual candidate-set cache identity, including serialized documents,
    route, mode, generation and update stamps. A miss is a denied transport, so
    asserting cache_hits verifies this key recipe against the actual consumer.
    """
    settings = mw._rerank_settings()
    assert settings["RERANK_ENABLED"] and settings["RERANK_ENDPOINT_VALID"]
    state = mw._rerank_scope_state(settings)
    documents = [mw._serialize_rerank_document(row, settings=settings) for row in rows]
    canonical = sorted((str(row["id"]), document) for row, document in zip(rows, documents))
    fingerprint = mw.sha("\n---candidate---\n".join(f"id={cid}\n{document}" for cid, document in canonical))
    seed = "\n".join((
        f"generation={state['generation']}", f"settings={settings['signature']}",
        f"model={settings['RERANK_MODEL']}", f"url={settings['RERANK_URL']}",
        f"api_style={settings['RERANK_API_STYLE']}", f"mode={mode}",
        f"query={mw._build_rerank_query(query.strip(), mode, settings=settings)}", f"documents={fingerprint}",
        "rows=" + ",".join(sorted(f"{row.get('id','')}:{row.get('updated_at',0)}" for row in rows)),
    ))
    key = mw.sha(seed)
    state["cache"][key] = (time.monotonic() + 1800, ranks)
    return state, key


def test_frozen_rank_one_must_not_be_demoted_to_three_by_inner_rrf(order_case):
    provider, _scope, attempts = order_case
    rows = _rows()
    ranks = _ranks(rows)
    query = "Which authored durable retrieval ordering fixture is most relevant?"
    state, _key = _prime(query, rows, ranks)
    before_hits = state["stats"]["cache_hits"]
    result = provider._rerank_rows(query, rows, "semantic")
    assert attempts == []
    assert state["stats"]["cache_hits"] == before_hits + 1
    # Frozen K=10, w=.75, original rank15/model rank1: old blend gives rank3.
    assert [row["id"] for row in result].index(rows[14]["id"]) + 1 == 1
    assert [row["rerank_rank"] for row in result] == list(range(1, 49))


def _seed(provider, count=20):
    stamp = mw.now()
    for i in range(count):
        cid = f"claim-order-{i:02d}"
        text = f"Authored retrieval ordering fixture number {i} records a durable harmless local backup policy."
        with provider._connect() as conn:
            conn.execute("""INSERT INTO claims(id,claim,normalized_claim,topic,status,confidence,salience,
                source,evidence,created_at,updated_at,freshness_at,hash,quality,risk,quarantined_at,
                scope,visibility_scope,origin_bot_id,origin_session_id,origin_chat_hash,project_id)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (cid, text, text, "ordering", "active", .8, .9 - i / 100.0,
                 f"fixture-{i}", "", stamp, stamp, stamp, cid, .9, "low", 0,
                 "global", "global", provider.bot_id, provider.session_id,
                 provider._chat_hash(provider.session_id), provider.project_scope))
        provider._upsert_fts(cid)


def test_frozen_outer_rrf_must_preserve_successful_primary_query_order(order_case, monkeypatch):
    provider, _scope, attempts = order_case
    _seed(provider)
    primary = "Which authored retrieval ordering fixture records the relevant backup policy?"
    secondary = "authored retrieval ordering fixture local backup"
    local = provider._search(primary, limit=24, apply_rerank=False, record_retrieval=False)
    assert len(local) == 20
    winner = local[0]["id"]
    _prime(primary, local, _ranks(local, winner_index=0), mw._detect_query_mode(primary))
    # The variant is also a genuine search/cache consumer. Its ranks disagree;
    # ranks from different queries must not be compared as raw score magnitudes.
    variant_local = provider._search(secondary, limit=24, apply_rerank=False, record_retrieval=False)
    variant_order = [local[2]["id"], *[r["id"] for r in variant_local if r["id"] not in {local[2]["id"], winner}], winner]
    variant_ranks = [(cid, 1.0 - rank / 100.0, rank) for rank, cid in enumerate(variant_order, 1)]
    _prime(secondary, variant_local, variant_ranks, mw._detect_query_mode(secondary))
    result = mw._recall_orchestrator.recall(
        provider, primary, mode="auto", limit=8, max_chars=8000,
        query_expander=lambda *_a, **_k: [primary, secondary, secondary, secondary],
    )
    assert attempts == []
    assert result["items"]
    assert result["items"][0]["id"] == winner
    assert len({item["citation"] for item in result["items"]}) == len(result["items"])
    assert all(item["trust"]["level"] != "verified" for item in result["items"])
    assert all(not any(key.startswith("_") for key in item) for item in result["items"])


def test_actual_candidate_set_cache_repeats_change_diagnostics_not_order(order_case):
    provider, _scope, attempts = order_case
    rows = _rows()
    query = "Which authored durable retrieval ordering fixture is most relevant?"
    state, key = _prime(query, rows, _ranks(rows))
    before = dict(state["stats"])
    forward = provider._rerank_rows(query, rows, "semantic")
    reverse = provider._rerank_rows(query, list(reversed(rows)), "semantic")
    assert attempts == []
    assert state["stats"]["cache_hits"] == before["cache_hits"] + 2
    assert state["stats"]["requests"] == before["requests"]
    assert state["stats"]["successes"] == before["successes"]
    assert state["stats"]["cost_usd"] == before["cost_usd"]
    assert [r["id"] for r in forward] == [r["id"] for r in reverse]
    assert forward[0]["rerank_fusion_score"] != reverse[0]["rerank_fusion_score"]
    assert len(state["cache"]) == 1 and key in state["cache"]
    assert forward[0]["_rerank_order"] == reverse[0]["_rerank_order"]


def test_actual_guarded_partial_topk_does_not_promote_rejected_or_late_rows(order_case):
    provider, _scope, attempts = order_case
    rows = _rows(60)
    rows[0]["status"] = "retired"
    rows[1]["risk"] = "secret"
    rows[2]["trust_class"] = "tool_log"
    rows[3].update(visibility_scope="chat", origin_bot_id="foreign-owner", origin_chat_hash="foreign-chat")
    safe_prefix = rows[4:48]
    query = "Which authored durable retrieval ordering fixture is most relevant?"
    ranks = _ranks(safe_prefix, winner_index=14)[:10]
    _prime(query, safe_prefix, ranks)
    result = provider._rerank_rows(query, rows, "semantic")
    assert attempts == []
    assert result[:4] == rows[:4] and result[48:] == rows[48:]
    assert all("rerank_rank" not in r for r in result[:4] + result[48:])
    ranked = [r for r in result if "rerank_rank" in r]
    assert [r["id"] for r in ranked] == [cid for cid, _score, _rank in ranks]
    assert [r["rerank_rank"] for r in ranked] == list(range(1, 11))
    omitted = [r for r in result[4:48] if "rerank_rank" not in r]
    assert [r["id"] for r in omitted] == [r["id"] for r in safe_prefix if r["id"] not in {cid for cid, _s, _r in ranks}]
    assert all("_rerank_order" not in r for r in omitted)


def test_actual_skip_deadline_and_circuit_controls_keep_original_local_order(order_case, monkeypatch):
    provider, scope, attempts = order_case
    rows = _rows()
    query = "Which authored durable retrieval ordering fixture is most relevant?"
    assert provider._rerank_rows(query, rows[:9], "semantic") == rows[:9]
    with monkeypatch.context() as patch:
        patch.setitem(scope, "MEMORY_WIKI_RERANK_ENABLED", "0")
        assert provider._rerank_rows(query, rows, "semantic") == rows
    exact_rows = [dict(row) for row in rows]
    exact_rows[0]["score_parts"] = {"exact": .35, "bm25": .9}
    assert provider._rerank_rows("A sufficiently long exact technical fixture query", exact_rows, "technical") == exact_rows
    with monkeypatch.context() as patch:
        patch.setattr(mw, "_prefetch_budget_expired", lambda *_args: True)
        assert provider._rerank_rows(query, rows, "semantic") == rows
    with monkeypatch.context() as patch:
        patch.setattr(mw, "_prefetch_network_timeout", lambda *_args: 0.0)
        assert provider._rerank_rows(query, rows, "semantic") == rows
    state = mw._rerank_scope_state()
    state["circuit_until"] = time.monotonic() + 60
    assert provider._rerank_rows(query, rows, "semantic") == rows
    state["circuit_until"] = 0.0
    assert attempts == []


def test_actual_timeout_is_one_denied_attempt_with_local_fallback(order_case):
    provider, _scope, attempts = order_case
    rows = _rows()
    state = mw._rerank_scope_state()
    before = dict(state["stats"])
    assert provider._rerank_rows("Uncached authored durable retrieval ordering question", rows, "semantic") == rows
    assert attempts == ["denied-before-HTTP"]
    assert state["stats"]["requests"] == before["requests"] + 1
    assert state["stats"]["failures"] == before["failures"] + 1
    assert state["stats"]["successes"] == before["successes"]


def test_actual_corrupt_cached_ranks_fall_back_without_retry_or_model_success(order_case):
    provider, _scope, attempts = order_case
    rows = _rows()
    query = "Which authored durable retrieval ordering fixture is most relevant?"
    ranks = _ranks(rows)
    for invalid in [ranks[:-40], [("foreign:order-15", .9, 1), *ranks[1:]],
                    [(ranks[0][0], float("nan"), 1), *ranks[1:]],
                    [ranks[0], ranks[0], *ranks[2:]], [(ranks[0][0], .9, True), *ranks[1:]]]:
        state, key = _prime(query, rows, invalid)
        before = dict(state["stats"])
        assert provider._rerank_rows(query, rows, "semantic") == rows
        assert key not in state["cache"]
        assert state["stats"]["requests"] == before["requests"]
        assert state["stats"]["successes"] == before["successes"]
        assert state["stats"]["last_error"] == "invalid_rerank_cache"
    for envelope in [(), {}, (float("nan"), ranks), ("expired", ranks), (time.monotonic(),), True]:
        state, key = _prime(query, rows, ranks)
        state["cache"][key] = envelope
        assert provider._rerank_rows(query, rows, "semantic") == rows
        assert key not in state["cache"]
    assert attempts == []


def test_actual_cached_search_late_retirement_does_not_survive_disclosure(order_case, monkeypatch):
    provider, _scope, attempts = order_case
    _seed(provider)
    query = "Which authored retrieval ordering fixture records the relevant backup policy?"
    local = provider._search(query, limit=24, apply_rerank=False, record_retrieval=False)
    winner = local[14]["id"]
    _prime(query, local, _ranks(local), mw._detect_query_mode(query))
    actual_guard = provider._inspect_recall_text
    revoked = []

    def guard_then_retire(text, **kwargs):
        decision = actual_guard(text, **kwargs)
        if kwargs.get("source") == "rerank_document" and not revoked:
            with provider._connect() as conn:
                conn.execute("UPDATE claims SET status='retired' WHERE id=?", (winner,))
            revoked.append(winner)
        return decision

    monkeypatch.setattr(provider, "_inspect_recall_text", guard_then_retire)
    assert provider._search(query, limit=24, record_retrieval=False) == []
    assert revoked == [winner] and attempts == []
    assert provider._connect().execute("SELECT status FROM claims WHERE id=?", (winner,)).fetchone()[0] == "retired"


def test_actual_profile_namespace_and_candidate_change_cannot_reuse_ranks(order_case):
    provider, scope, attempts = order_case
    rows = _rows()
    query = "Which authored durable retrieval ordering fixture is most relevant?"
    state, key = _prime(query, rows, _ranks(rows))
    assert provider._rerank_rows(query, rows, "semantic")[0]["id"] == rows[14]["id"]
    foreign_scope = {**scope, "__home": str(provider.home / "other-owner")}
    token = mw._QDRANT_PROFILE_SCOPE.set(foreign_scope)
    try:
        foreign_state = mw._rerank_scope_state()
        assert foreign_state is not state and key not in foreign_state["cache"]
    finally:
        mw._QDRANT_PROFILE_SCOPE.reset(token)
    changed = [dict(row) for row in rows]
    changed[0]["claim"] += " Changed authored content."
    assert provider._rerank_rows(query, changed, "semantic") == changed
    assert attempts == ["denied-before-HTTP"]
    assert key in state["cache"]
    assert provider._rerank_rows(query, rows, "semantic")[0]["id"] == rows[14]["id"]
    assert attempts == ["denied-before-HTTP"]


def test_actual_fast_and_disabled_recall_keep_original_rrf_fallback(order_case, monkeypatch):
    provider, scope, attempts = order_case
    _seed(provider)
    query = "Which authored retrieval ordering fixture records the relevant backup policy?"
    with monkeypatch.context() as patch:
        patch.setitem(scope, "MEMORY_WIKI_RERANK_ENABLED", "0")
        for mode, retrieval_mode in [("fast", "fts"), ("auto", "hybrid")]:
            local = provider._search(query, limit=24, retrieval_mode=retrieval_mode, apply_rerank=False, record_retrieval=False)
            result = mw._recall_orchestrator.recall(
                provider, query, mode=mode, limit=8, max_chars=8000,
                query_expander=lambda *_a, **_k: [query],
            )
            assert [r["id"] for r in result["items"]] == [r["id"] for r in local[:8]]
            assert result["intent_plan"]["retrieval_mode"] == retrieval_mode
            assert all(item["rrf_score"] == round(1.0 / (60 + rank), 8) for rank, item in enumerate(result["items"], 1))
    assert attempts == []
