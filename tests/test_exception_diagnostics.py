"""Exception messages must never become durable memory diagnostics."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


PLUGIN = Path(__file__).resolve().parents[1] / "__init__.py"


def _module(name: str):
    spec = importlib.util.spec_from_file_location(
        name, PLUGIN, submodule_search_locations=[str(PLUGIN.parent)]
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_journal_exception_and_tool_error_omit_secret_text(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "0")
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    module = _module("memory_wiki_exception_journal_test")
    provider = module.MemoryWikiProvider()
    provider.initialize("diagnostics", hermes_home=str(tmp_path), agent_context="test")
    marker = "secret-exception-marker-7eb1"
    try:
        try:
            provider._journal_operation(
                "memory_wiki_add_claim", {"topic": "test"},
                lambda: (_ for _ in ()).throw(RuntimeError(marker)),
            )
        except RuntimeError:
            pass
        else:
            raise AssertionError("expected synthetic error")
        provider._journal_operation(
            "memory_wiki_add_claim", {"topic": "test"},
            lambda: json.dumps({"success": False, "error": marker}),
        )
        journal = provider.journal_path.read_text(encoding="utf-8")
        assert marker not in journal
        assert "RuntimeError: mutation failed" in journal
        assert "tool returned failure" in journal
    finally:
        if provider._conn is not None:
            provider._conn.close()
            provider._conn = None


def test_recall_guard_audit_omits_exception_text(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "0")
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    # Import remains possible in a standalone test environment without the
    # host's trust-core module; strictness is read again at guard invocation.
    monkeypatch.setenv("HERMES_SECURITY_STRICT", "0")
    module = _module("memory_wiki_exception_guard_test")
    provider = module.MemoryWikiProvider()
    provider.initialize("diagnostics", hermes_home=str(tmp_path), agent_context="test")
    marker = "secret-guard-marker-88cb"
    audit = []

    def broken_guard(*_args, **_kwargs):
        raise RuntimeError(marker)

    monkeypatch.setattr(module, "_INJECTION_GUARD_AVAILABLE", True)
    monkeypatch.setattr(module, "_sanitize_recalled", broken_guard, raising=False)
    monkeypatch.setattr(provider, "_audit", lambda *args: audit.append(args))
    monkeypatch.setenv("HERMES_SECURITY_STRICT", "1")
    try:
        outcome = provider._inspect_recall_text(
            "ordinary note", source="test", mem_type="claim", item_id="claim-1"
        )
        assert outcome["status"] == "runtime_failure_quarantined"
        assert marker not in repr(audit)
        assert "RuntimeError" in repr(audit)
    finally:
        if provider._conn is not None:
            provider._conn.close()
            provider._conn = None


def test_public_validation_codes_are_allowlisted():
    module = _module("memory_wiki_public_error_codes_test")
    assert module._public_tool_error(ValueError("source_revision_conflict")) == "source_revision_conflict"
    assert module._public_tool_error(PermissionError("connector_source_not_owned")) == "connector_source_not_owned"
    assert module._public_tool_error(ValueError("github_rate_limited:retry_after_seconds=120")) == "github_rate_limited:retry_after_seconds=120"
    assert module._public_tool_error(ValueError("github_rate_limited:retry_after_seconds=120;token=private")) == "ValueError"
    assert module._public_tool_error(ValueError("private access token in message")) == "ValueError"
    assert module._public_tool_error(RuntimeError("source_revision_conflict")) == "RuntimeError"


def test_search_debug_log_never_contains_raw_query(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "0")
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_SECURITY_STRICT", "0")
    module = _module("memory_wiki_search_log_privacy")
    provider = module.MemoryWikiProvider()
    provider.initialize("diagnostics", hermes_home=str(tmp_path), agent_context="test")
    logs = []
    monkeypatch.setattr(module, "_debug_log", logs.append)
    marker = "private-query-marker-82c7"
    try:
        provider._search(marker, retrieval_mode="fts")
        assert marker not in repr(logs)
        assert any("QUERY mode=" in entry for entry in logs)
    finally:
        provider.shutdown()
