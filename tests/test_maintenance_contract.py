#!/usr/bin/env python3
"""Maintenance schema and recovery-contract regression."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


PLUGIN = Path(__file__).resolve().parents[1] / "__init__.py"
PACKAGED_SCHEMAS = PLUGIN.parent / "mcp-wrapper" / "tool_schemas.json"


def load_provider(module_name: str, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_SECURITY_STRICT", "0")
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "0")
    monkeypatch.setenv("MEMORY_WIKI_JOURNAL_SAFETY_CHECKPOINTS", "1")
    spec = importlib.util.spec_from_file_location(
        module_name, PLUGIN, submodule_search_locations=[str(PLUGIN.parent)]
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    provider = module.MemoryWikiProvider()
    provider.initialize(module_name, hermes_home=str(tmp_path), agent_context="test")
    return provider


def maintenance_schema(schemas):
    return next(schema for schema in schemas if schema.get("name") == "memory_wiki_maintenance")


def test_maintenance_schema_matches_package_and_success_is_checkpointed(tmp_path, monkeypatch) -> None:
    provider = load_provider("memory_wiki_maintenance_contract_test", tmp_path, monkeypatch)
    try:
        runtime_schema = maintenance_schema(provider.get_tool_schemas())
        packaged_schema = maintenance_schema(json.loads(PACKAGED_SCHEMAS.read_text(encoding="utf-8")))
        assert runtime_schema == packaged_schema
        assert runtime_schema["parameters"]["properties"] == {}
        assert runtime_schema["parameters"]["additionalProperties"] is False
        assert "prune" not in runtime_schema["description"].lower()

        result = json.loads(provider.handle_tool_call("memory_wiki_maintenance", {}))
        assert result["success"] is True, result
        assert result["fts"] == "rebuilt"
        assert result["contradictions"] == "scanned"
        assert result["rendered"] is True

        checkpoint = provider._latest_journal_checkpoint()
        assert checkpoint is not None
        payload = json.loads(checkpoint.read_text(encoding="utf-8"))
        maintenance_after = [
            event for event in provider._iter_journal_events()
            if event.get("op") == "memory_wiki_maintenance" and event.get("phase") == "after"
        ]
        assert maintenance_after
        assert payload["journal_seq"] == maintenance_after[-1]["seq"]
        plan = provider._rebuild_from_journal(apply=False)
        assert plan["unrecoverable_events"] == 0, plan
        assert plan["incomplete_events"] == 0, plan
    finally:
        if provider._conn is not None:
            provider._conn.close()
            provider._conn = None


def test_maintenance_rejects_unknown_arguments_before_journaling(tmp_path, monkeypatch) -> None:
    provider = load_provider("memory_wiki_maintenance_args_test", tmp_path, monkeypatch)
    try:
        marker = "UNSUPPORTED_MAINTENANCE_ARGUMENT_MUST_NOT_BE_JOURNALED"
        before = list(provider._iter_journal_events())
        result = json.loads(provider.handle_tool_call("memory_wiki_maintenance", {"note": marker}))

        assert result["success"] is False, result
        assert result["error"] == "invalid_arguments"
        assert list(provider._iter_journal_events()) == before
        if provider.journal_path.exists():
            assert marker not in provider.journal_path.read_text(encoding="utf-8")
    finally:
        if provider._conn is not None:
            provider._conn.close()
            provider._conn = None


def test_maintenance_checkpoint_failure_is_visible_but_recovery_safe(tmp_path, monkeypatch) -> None:
    provider = load_provider("memory_wiki_maintenance_checkpoint_failure_test", tmp_path, monkeypatch)
    try:
        def fail_checkpoint(*_args, **_kwargs):
            raise OSError("simulated checkpoint write failure")

        monkeypatch.setattr(provider, "_journal_checkpoint", fail_checkpoint)
        result = json.loads(provider.handle_tool_call("memory_wiki_maintenance", {}))

        assert result["success"] is True, result
        assert result["journal_checkpoint"]["error"].startswith("OSError:"), result
        assert result["recovery"] == "maintenance_derived_state_recoverable"
        plan = provider._rebuild_from_journal(apply=False)
        assert plan["unrecoverable_events"] == 0, plan
        assert plan["incomplete_events"] == 0, plan
        assert plan["ignored_events"] >= 1, plan
    finally:
        if provider._conn is not None:
            provider._conn.close()
            provider._conn = None
