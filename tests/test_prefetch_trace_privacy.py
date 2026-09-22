"""Prefetch diagnostics use unlinkable trace IDs, never a query fingerprint."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


PLUGIN = Path(__file__).resolve().parents[1] / "__init__.py"


def _module(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_SECURITY_STRICT", "0")
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "0")
    name = "memory_wiki_prefetch_trace_privacy_test"
    spec = importlib.util.spec_from_file_location(
        name, PLUGIN, submodule_search_locations=[str(PLUGIN.parent)],
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_identical_prefetch_queries_leave_distinct_unlinkable_audit_ids(tmp_path, monkeypatch):
    module = _module(tmp_path, monkeypatch)
    provider = module.MemoryWikiProvider()
    provider.initialize("trace-chat", hermes_home=str(tmp_path), bot_id="trace-bot", agent_context="test")
    query = "where is the synthetic project plan"
    try:
        provider._prefetch_impl(query)
        first = dict(provider._last_prefetch_diagnostics)
        provider._prefetch_impl(query)
        second = dict(provider._last_prefetch_diagnostics)
        assert first["recall_trace_id"].startswith("rt_")
        assert second["recall_trace_id"].startswith("rt_")
        assert first["recall_trace_id"] != second["recall_trace_id"]
        assert "query_hash" not in first and "query_hash" not in second
        details = [
            str(row[0]) for row in provider._connect().execute(
                "SELECT detail FROM audit_log WHERE op='prefetch' ORDER BY created_at"
            )
        ]
        assert len(details) >= 2
        assert all(query not in detail and "query_hash" not in detail for detail in details)
        ids = {json.loads(detail)["recall_trace_id"] for detail in details if detail.startswith("{")}
        assert first["recall_trace_id"] in ids
        assert second["recall_trace_id"] in ids
    finally:
        provider.shutdown()
