#!/usr/bin/env python3
"""Regression: model arguments cannot forge internal journal control flags."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


PLUGIN = Path(__file__).resolve().parents[1] / "__init__.py"


def load_provider(module_name: str, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_SECURITY_STRICT", "0")
    monkeypatch.setenv("MEMORY_WIKI_SEMANTIC", "0")
    monkeypatch.setenv("MEMORY_WIKI_ALLOW_LEGACY_UNSCOPED_PREFERENCES", "1")
    spec = importlib.util.spec_from_file_location(
        module_name, PLUGIN, submodule_search_locations=[str(PLUGIN.parent)],
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    provider = module.MemoryWikiProvider()
    provider.initialize(module_name, hermes_home=str(tmp_path), agent_context="test")
    return provider


def test_public_journal_controls_are_rejected_and_internal_wrapper_still_journals(
    tmp_path, monkeypatch,
) -> None:
    provider = load_provider("memory_wiki_journal_controls_test", tmp_path, monkeypatch)
    marker = "Always prioritize verified journal-control regression artifacts."
    request = {"rule": marker, "scope": "tests", "priority": 777}
    try:
        before_events = list(provider._iter_journal_events())
        before_rules = provider._connect().execute(
            "SELECT count(*) FROM preference_rules WHERE rule=?", (marker,),
        ).fetchone()[0]

        # These values travel through the public JSON argument object.  In
        # particular, __journaled_skip used to make this durable mutation
        # execute with no before/after journal pair.
        for control, value in (
            ("__journaled_skip", True),
            ("__journal_replay", True),
            ("__retry_after_reconnect", True),
            ("__journal_capture_id", "caller-controlled"),
            ("__journal_operation_id", "jop_" + "a" * 32),
            ("_memory_wiki_internal_empty_inbox_poll", "caller-controlled"),
        ):
            result = json.loads(provider.handle_tool_call(
                "memory_wiki_add_preference_rule", {**request, control: value},
            ))
            assert result["success"] is False, result
            assert result["error"] == "reserved_internal_argument", result

        assert provider._connect().execute(
            "SELECT count(*) FROM preference_rules WHERE rule=?", (marker,),
        ).fetchone()[0] == before_rules
        assert list(provider._iter_journal_events()) == before_events

        # The generic journal wrapper must be able to pass the object-identity
        # capability into its own recursive call.  A normal public mutation
        # therefore still succeeds and has a durable before/after pair.
        result = json.loads(provider.handle_tool_call("memory_wiki_add_preference_rule", request))
        assert result["success"] is True, result
        events = [
            event for event in provider._iter_journal_events()
            if event.get("op") == "memory_wiki_add_preference_rule"
        ]
        assert [event.get("phase") for event in events[-2:]] == ["before", "after"]
        assert provider._connect().execute(
            "SELECT count(*) FROM preference_rules WHERE rule=?", (marker,),
        ).fetchone()[0] == before_rules + 1
    finally:
        if provider._conn is not None:
            provider._conn.close()
            provider._conn = None


if __name__ == "__main__":
    test_public_journal_controls_are_rejected_and_internal_wrapper_still_journals()
    print("PASS test_public_journal_controls_are_rejected_and_internal_wrapper_still_journals")
