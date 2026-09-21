"""Content-free operational aggregates are bounded and safe under failures."""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
import time
from pathlib import Path

import pytest


MODULE = Path(__file__).resolve().parents[1] / "online_metrics.py"
SPEC = importlib.util.spec_from_file_location("memory_wiki_online_metrics_test", MODULE)
assert SPEC and SPEC.loader
metrics = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = metrics
SPEC.loader.exec_module(metrics)


def test_rejects_arbitrary_dimensions_and_never_persists_query_text(tmp_path):
    path = tmp_path / "memory.sqlite3"
    secret_query = "private user query marker 87b23"
    with sqlite3.connect(path) as conn:
        metrics.install_schema(conn)
        with pytest.raises(ValueError, match="dimension"):
            metrics.record(conn, secret_query, "hit", 9)
        with pytest.raises(ValueError, match="dimension"):
            metrics.record(conn, "prefetch", secret_query, 9)
        with pytest.raises(ValueError, match="duration"):
            metrics.record(conn, "prefetch", "hit", float("nan"))
        metrics.record(conn, "prefetch", "hit", 9)
        rows = conn.execute("SELECT * FROM memory_online_metrics").fetchall()
    assert len(rows) == 1
    assert secret_query.encode() not in path.read_bytes()


def test_daily_histogram_rollup_and_retention(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMORY_WIKI_ONLINE_METRICS_DAYS", "2")
    path = tmp_path / "memory.sqlite3"
    day = 20000 * 86400
    with sqlite3.connect(path) as conn:
        metrics.install_schema(conn)
        metrics.record(conn, "recall", "empty", 18, timestamp=day)
        metrics.record(conn, "recall", "hit", 54, timestamp=day)
        metrics.record(conn, "recall", "hit", 1200, timestamp=day)
        snap = metrics.snapshot(conn, days=2, timestamp=day)
        recall = snap["operations"]["recall"]
        assert recall["samples"] == 3
        assert recall["outcomes"]["hit"] == 2
        assert recall["outcomes"]["empty"] == 1
        assert recall["latency_p50_upper_ms"] == 100
        assert recall["latency_p95_upper_ms"] == 2000
        assert recall["latency_mean_ms"] == 424.0
        metrics.record(conn, "prefetch", "timeout_fallback", 30, timestamp=day + 2 * 86400)
        assert conn.execute("SELECT count(*) FROM memory_online_metrics").fetchone()[0] == 1


def test_best_effort_write_drops_locked_sample_without_changing_recall(tmp_path):
    path = tmp_path / "memory.sqlite3"
    with sqlite3.connect(path) as conn:
        metrics.install_schema(conn)
    locker = sqlite3.connect(path, timeout=0.1)
    try:
        locker.execute("BEGIN EXCLUSIVE")
        started = time.monotonic()
        assert not metrics.record_path(path, "prefetch", "hit", 8)
        assert time.monotonic() - started < 0.5
    finally:
        locker.rollback()
        locker.close()
    assert metrics.record_path(path, "prefetch", "hit", 8)
    with sqlite3.connect(path) as conn:
        assert metrics.snapshot(conn)["operations"]["prefetch"]["samples"] == 1


def test_missing_table_is_reported_as_empty_window():
    with sqlite3.connect(":memory:") as conn:
        assert metrics.snapshot(conn)["operations"]["recall"]["samples"] == 0


def test_provider_records_prefetch_and_explicit_recall_without_query(tmp_path, monkeypatch):
    plugin = MODULE.parent / "__init__.py"
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_SECURITY_STRICT", "0")
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "0")
    spec = importlib.util.spec_from_file_location(
        "memory_wiki_online_metrics_integration_test", plugin,
        submodule_search_locations=[str(plugin.parent)],
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    provider = module.MemoryWikiProvider()
    provider.initialize("metrics-chat", hermes_home=str(tmp_path), bot_id="metrics-bot", agent_context="test")
    secret_query = "private query marker 65e3ac"
    try:
        monkeypatch.setattr(provider, "_prefetch_impl", lambda _query, **_kwargs: "synthetic context")
        assert provider.prefetch(secret_query) == "synthetic context"
        monkeypatch.setattr(
            module._recall_orchestrator, "recall",
            lambda *_args, **_kwargs: {"evidence_count": 0, "items": []},
        )
        result = json.loads(provider.handle_tool_call("memory_wiki_recall", {"query": secret_query}))
        assert result["success"] is True
        summary = module._online_metrics.snapshot(provider._connect())
        assert summary["operations"]["prefetch"]["outcomes"]["hit"] == 1
        assert summary["operations"]["recall"]["outcomes"]["empty"] == 1
        serialized = repr(provider._connect().execute(
            "SELECT * FROM memory_online_metrics"
        ).fetchall())
        assert secret_query not in serialized
    finally:
        provider.shutdown()
