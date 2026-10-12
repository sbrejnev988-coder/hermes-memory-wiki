"""Audit #8 genuine ordinary component regressions, not host/bootstrap proof.

The entry binds real BaseSPI/registry/trust before collection. Authored claims
live only in the exact synthetic import/provider home. Faults are plugin seams
or the actual Thread constructor/start, never SDK/guard/search substitutes.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import threading

import pytest
import memory_wiki as mw
from agent.memory_provider import MemoryProvider
from tools import registry
import hermes_trust_core as trust

QUERY = "Atlas telescope diagnostic fixture"
CLAIM = "Atlas telescope diagnostic fixture uses the copper observatory."
CID = "c_audit8_authored"
FAULT_TEXT = "AUDIT8_PRIVATE_EXCEPTION_MARKER"
OBSERVATIONS = []


@pytest.fixture(scope="session", autouse=True)
def observations():
    yield
    target = Path(os.environ["AUDIT8_OBSERVATIONS"])
    target.write_text(json.dumps(OBSERVATIONS, indent=2) + "\n", encoding="utf-8")


@pytest.fixture
def provider(monkeypatch):
    home = Path(os.environ["HERMES_HOME"])
    assert home.resolve() == mw._IMPORT_HERMES_HOME.resolve()
    assert mw.MemoryWikiProvider.__bases__ == (MemoryProvider,)
    assert mw.tool_error is registry.tool_error and mw.tool_result is registry.tool_result
    assert mw._sanitize_recalled is trust.sanitize_recalled
    assert mw._INJECTION_GUARD_AVAILABLE
    assert not mw.SEMANTIC_ENABLED
    assert os.environ["MEMORY_WIKI_BACKGROUND_JOBS_ENABLED"] == "0"
    assert os.environ["MEMORY_WIKI_GRAPH_EXTRACT_ENABLED"] == "0"
    p = mw.MemoryWikiProvider()
    p.initialize("audit8-chat", hermes_home=str(home), bot_id="audit8-bot", agent_context="test")
    assert p.home.resolve() == home.resolve()
    try:
        with p._claim_transaction() as conn:
            conn.execute("DELETE FROM claims")
            conn.execute("DELETE FROM audit_log WHERE op='prefetch'")
        stamp = mw.now()
        row = {"id": CID, "claim": CLAIM, "normalized_claim": CLAIM,
               "topic": "atlas", "hash": mw.sha(CID + "\0" + CLAIM),
               "type": "fact", "status": "active", "risk": "low",
               "quality": .95, "confidence": .95, "salience": .95,
               "freshness_at": stamp, "created_at": stamp, "updated_at": stamp,
               "pinned": 1, "source": "fixture:authored-audit8", "source_kind": "curated",
               "memory_class": "fact", "trust_class": "fact", "trust_score": .95,
               "memory_revision": 1, "visibility_scope": "global",
               "origin_bot_id": p.bot_id, "origin_session_id": p.session_id,
               "origin_chat_hash": p._chat_hash(), "why_believe": "Authored offline fixture."}
        with p._claim_transaction() as conn:
            columns = {r[1] for r in conn.execute("PRAGMA table_info(claims)")}
            stored = {k: v for k, v in row.items() if k in columns}
            conn.execute("INSERT INTO claims(" + ",".join(stored) + ") VALUES(" +
                         ",".join("?" for _ in stored) + ")", tuple(stored.values()))
        p._upsert_fts(CID)
        assert p._inspect_recall_text(CLAIM, source="fixture", mem_type="data", audit=False)["status"] == "safe"
        yield p
    finally:
        p.shutdown()
        assert p._conn is None and p._background_worker is None
        assert not [t for t in threading.enumerate() if t.name == "memory-wiki-bounded-prefetch"]


def split_output(value):
    body, separator, receipt = value.partition("\nRetrieval receipt: ")
    assert separator, "actual admitted public prefetch must retain its receipt"
    return body, json.loads(receipt)


def diag_for(p, value, path, reason):
    body, receipt = split_output(value)
    diag = dict(p._last_prefetch_diagnostics)
    assert diag["recall_trace_id"] == receipt["trace_id"]
    assert diag["delivery_path"] == receipt["delivery_path"] == path
    assert diag["fallback_reason"] == reason
    assert diag["status"] == "lexical_fallback"
    assert diag["searched"] == diag["relevant"] == diag["safe"] == diag["rendered"] == 1
    assert diag["quarantined"] == 0 and diag["delta_rendered"] == 0
    assert diag["output_chars"] == len(body)
    assert diag["estimated_tokens"] == (len(body) + 3) // 4
    assert diag["rendered_claim_chars"] == len(CLAIM)
    assert receipt["final"]["emitted_claim_count"] == 1
    serialized = json.dumps(diag)
    assert not any(x in serialized for x in [QUERY, CLAIM, FAULT_TEXT, "query_hash"])
    assert all(type(v) in (str, int, float, bool) for v in diag.values())
    OBSERVATIONS.append({"path": path, "diagnostics": diag, "receipt_trace_id": receipt["trace_id"]})
    return diag


def canonical(p):
    value = p.prefetch(QUERY)
    assert CLAIM in value
    body, receipt = split_output(value)
    diag = dict(p._last_prefetch_diagnostics)
    assert receipt["delivery_path"] == "canonical"
    assert diag["recall_trace_id"] == receipt["trace_id"]
    assert "fallback_reason" not in diag and "delivery_path" not in diag
    assert diag["rendered"] == 1 and diag["output_chars"] == len(body)
    return diag


def runtime_fault(monkeypatch, hook=None):
    original = mw._semantic_profile_ready
    calls = []

    def fault():
        if threading.current_thread().name == "memory-wiki-bounded-prefetch":
            staged = mw._AUDIT_PREPARATION.get()
            assert staged is not None and mw._current_delivery() is None
            calls.append(staged)
            if hook:
                hook(staged)
            raise RuntimeError(FAULT_TEXT)
        return original()

    monkeypatch.setattr(mw, "_semantic_profile_ready", fault)
    return calls


def thread_fault(monkeypatch, stage):
    real = threading.Thread

    class FailingThread(real):
        def __init__(self, *args, **kwargs):
            if kwargs.get("name") == "memory-wiki-bounded-prefetch" and stage == "constructor":
                raise RuntimeError(FAULT_TEXT)
            super().__init__(*args, **kwargs)

        def start(self):
            if self.name == "memory-wiki-bounded-prefetch" and stage == "start":
                raise RuntimeError(FAULT_TEXT)
            return super().start()

    monkeypatch.setattr(mw.threading, "Thread", FailingThread)


def test_canonical_current_random_trace(provider):
    first = canonical(provider)
    second = canonical(provider)
    assert first["recall_trace_id"] != second["recall_trace_id"]
    assert "query_hash" not in first


def test_canonical_then_worker_runtime_fallback(provider, monkeypatch):
    old = canonical(provider)
    before = provider._connect().execute("SELECT recall_count FROM claims WHERE id=?", (CID,)).fetchone()[0]
    calls = runtime_fault(monkeypatch)
    current = diag_for(provider, provider.prefetch(QUERY), "runtime_error_fallback", "network_or_runtime_error")
    assert calls and current["recall_trace_id"] != old["recall_trace_id"]
    assert calls[0].outcome == "dropped_worker_error" and calls[0].persisted_count == 0
    assert provider._connect().execute("SELECT recall_count FROM claims WHERE id=?", (CID,)).fetchone()[0] == before
    details = [json.loads(r[0]) for r in provider._connect().execute(
        "SELECT detail FROM audit_log WHERE op='prefetch' AND detail LIKE '{%' ORDER BY rowid")]
    # Audit storage applies the unchanged secret redactor (even to the field
    # name episode_secret_rejected); compare its actual declared projection.
    expected = json.loads(mw.redact_secrets(json.dumps(current, ensure_ascii=False, sort_keys=True)))
    assert details[-1] == expected
    assert details[-1]["recall_trace_id"] == current["recall_trace_id"]


@pytest.mark.parametrize("stage", ["constructor", "start"])
def test_actual_thread_fault_current_fallback(provider, monkeypatch, stage):
    old = canonical(provider)
    thread_fault(monkeypatch, stage)
    current = diag_for(provider, provider.prefetch(QUERY), "thread_start_fallback", "thread_start_failed")
    assert current["recall_trace_id"] != old["recall_trace_id"]


def test_deadline_late_worker_cannot_overwrite(provider, monkeypatch):
    canonical(provider)
    entered, release, attempted = threading.Event(), threading.Event(), threading.Event()
    workers = []
    prepared = []
    original = mw._semantic_profile_ready

    def delayed():
        if threading.current_thread().name == "memory-wiki-bounded-prefetch":
            if not workers:
                workers.append(threading.current_thread())
                staged = mw._AUDIT_PREPARATION.get()
                prepared.append(staged)
                entered.set()
                assert release.wait(12), "owned late worker was not released"
            provider._finish_prefetch_diagnostics({"recall_trace_id": "rt_late", "rendered": 99})
            attempted.set()
            raise RuntimeError(FAULT_TEXT)
        return original()

    monkeypatch.setattr(mw, "_semantic_profile_ready", delayed)
    try:
        current = diag_for(provider, provider.prefetch(QUERY), "deadline_fallback", "deadline")
        assert entered.is_set() and workers[0].is_alive()
        assert prepared[0].outcome == "dropped_deadline"
    finally:
        release.set()
        for worker in workers:
            worker.join(4)
    assert attempted.is_set() and not workers[0].is_alive()
    assert provider._last_prefetch_diagnostics == current
    assert prepared[0].persisted_count == 0
    OBSERVATIONS.append({"late_worker_reaped": True, "diagnostics_retained": True})


def test_live_detached_worker_cannot_publish_before_cancel(provider, monkeypatch):
    old = canonical(provider)
    observed = []

    def attempt(_staged):
        assert not mw._prefetch_cancelled()
        provider._finish_prefetch_diagnostics({"recall_trace_id": "rt_detached", "rendered": 99})
        observed.append(dict(provider._last_prefetch_diagnostics))

    runtime_fault(monkeypatch, attempt)
    current = diag_for(provider, provider.prefetch(QUERY), "runtime_error_fallback", "network_or_runtime_error")
    assert observed and all(x == old for x in observed)
    assert current != old


def test_empty_fallback_replaces_old_canonical(provider, monkeypatch):
    old = canonical(provider)
    with provider._claim_transaction() as conn:
        conn.execute("DELETE FROM claims WHERE id=?", (CID,))
    runtime_fault(monkeypatch)
    assert provider.prefetch(QUERY) == ""
    diag = provider._last_prefetch_diagnostics
    assert diag["status"] == "empty" and diag["delivery_path"] == "runtime_error_fallback"
    assert diag["fallback_reason"] == "network_or_runtime_error"
    assert diag["recall_trace_id"] != old["recall_trace_id"]
    assert diag["searched"] == diag["safe"] == diag["rendered"] == diag["output_chars"] == 0
    OBSERVATIONS.append({"empty_current_diagnostics": dict(diag)})


def test_zero_budget_fallback_clears_old_canonical(provider):
    canonical(provider)
    assert provider._lexical_prefetch_fallback(QUERY, delivery_budget=0) == ""
    assert provider._last_prefetch_diagnostics == {}  # no original read carrier admitted


def test_terminal_withdrawal_never_publishes_fallback(provider, monkeypatch):
    old = canonical(provider)
    runtime_fault(monkeypatch)
    original = provider._audit
    seen = []
    before = provider._connect().execute("SELECT count(*) FROM audit_log WHERE op='prefetch'").fetchone()[0]

    def withdraw(op, status="ok", detail="", *args, **kwargs):
        result = original(op, status, detail, *args, **kwargs)
        if op == "prefetch" and status == "lexical_fallback":
            seen.append(dict(provider._last_prefetch_diagnostics))
            with provider._claim_transaction() as conn:
                conn.execute("UPDATE claims SET status='archived' WHERE id=?", (CID,))
        return result

    monkeypatch.setattr(provider, "_audit", withdraw)
    assert provider.prefetch(QUERY) == ""
    assert seen == [old]
    assert provider._last_prefetch_diagnostics == {}
    assert provider._connect().execute("SELECT count(*) FROM audit_log WHERE op='prefetch'").fetchone()[0] == before


def test_foreign_original_caller_cannot_publish(provider, monkeypatch):
    canonical(provider)
    foreign = provider.home.parent / "foreign-caller"
    foreign.mkdir(exist_ok=True)
    monkeypatch.setenv("HERMES_HOME", str(foreign))
    thread_fault(monkeypatch, "start")
    assert provider.prefetch(QUERY) == ""
    assert provider._last_prefetch_diagnostics == {}
    monkeypatch.setenv("HERMES_HOME", str(provider.home))


@pytest.mark.parametrize("tool", ["memory_wiki_debug_search", "memory_wiki_semantic_status"])
def test_actual_public_diagnostic_readthrough(provider, monkeypatch, tool):
    runtime_fault(monkeypatch)
    current = diag_for(provider, provider.prefetch(QUERY), "runtime_error_fallback", "network_or_runtime_error")
    result = json.loads(provider.handle_tool_call(tool, {"query": QUERY}))
    assert "error" not in result
    assert result["last_prefetch"] == current


def test_detached_direct_finish_has_no_publication_authority(provider):
    old = canonical(provider)
    assert mw._current_delivery() is None
    provider._finish_prefetch_diagnostics({"recall_trace_id": "rt_unowned", "rendered": 99})
    assert provider._last_prefetch_diagnostics == old
