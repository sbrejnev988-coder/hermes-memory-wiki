#!/usr/bin/env python3
"""Regression: a journaled empty Code Shrinker inbox poll replays as a safe no-op."""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path


PLUGIN = Path(__file__).resolve().parents[1] / "__init__.py"


def load_provider(module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, PLUGIN, submodule_search_locations=[str(PLUGIN.parent)])
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_empty_code_graph_inbox_poll_is_replayable_noop() -> None:
    keys = ("HERMES_HOME", "HERMES_SECURITY_STRICT", "MEMORY_WIKI_SEMANTIC")
    previous = {key: os.environ.get(key) for key in keys}
    try:
        with tempfile.TemporaryDirectory(prefix="mw-empty-code-inbox-") as tmp:
            os.environ.update({"HERMES_HOME": tmp, "HERMES_SECURITY_STRICT": "0", "MEMORY_WIKI_SEMANTIC": "0"})
            module = load_provider("memory_wiki_empty_code_inbox_test")
            provider = module.MemoryWikiProvider(); provider.initialize("empty-code-inbox", hermes_home=tmp, agent_context="test")
            try:
                checkpoint = provider._journal_checkpoint("before-empty-code-inbox")
                live = json.loads(provider.handle_tool_call("memory_wiki_code_graph_ingest_inbox", {"limit": 1}))
                assert live["success"] is True and live["processed"] == 0 and live["failed"] == 0, live
                after = [
                    event for event in provider._iter_journal_events()
                    if event.get("op") == "memory_wiki_code_graph_ingest_inbox"
                    and event.get("phase") == "after"
                ]
                assert after and after[-1]["result"]["recovery"]["kind"] == "empty_inbox_poll", after
                plan = provider._rebuild_from_journal(apply=False, checkpoint=checkpoint["path"])
                assert plan["unrecoverable_events"] == 0 and plan["incomplete_events"] == 0, plan
                rebuilt = provider._rebuild_from_journal(apply=True, checkpoint=checkpoint["path"])
                assert rebuilt["replayed"] >= 1, rebuilt
            finally:
                if provider._conn is not None:
                    provider._conn.close(); provider._conn = None
    finally:
        for key, value in previous.items():
            if value is None: os.environ.pop(key, None)
            else: os.environ[key] = value


def test_crashed_empty_poll_before_is_ignored_but_later_poll_replays() -> None:
    """A pure empty-poll before record cannot block recovery after an after I/O crash."""
    keys = ("HERMES_HOME", "HERMES_SECURITY_STRICT", "MEMORY_WIKI_SEMANTIC")
    previous = {key: os.environ.get(key) for key in keys}
    try:
        with tempfile.TemporaryDirectory(prefix="mw-empty-code-inbox-crash-") as tmp:
            os.environ.update({"HERMES_HOME": tmp, "HERMES_SECURITY_STRICT": "0", "MEMORY_WIKI_SEMANTIC": "0"})
            module = load_provider("memory_wiki_empty_code_inbox_crash_test")
            provider = module.MemoryWikiProvider(); provider.initialize("empty-code-inbox-crash", hermes_home=tmp, agent_context="test")
            try:
                checkpoint = provider._journal_checkpoint("before-empty-code-inbox-crash")
                original_append = provider._append_journal_event

                def fail_after(op, payload, **kwargs):
                    if kwargs.get("phase") == "after":
                        raise OSError("injected empty-poll after failure")
                    return original_append(op, payload, **kwargs)

                provider._append_journal_event = fail_after
                failed = json.loads(provider.handle_tool_call("memory_wiki_code_graph_ingest_inbox", {"limit": 1}))
                assert failed["success"] is False, failed
                first_plan = provider._rebuild_from_journal(apply=False, checkpoint=checkpoint["path"])
                assert first_plan["incomplete_events"] == 0, first_plan
                assert first_plan["ignored_events"] == 1, first_plan

                provider._append_journal_event = original_append
                live = json.loads(provider.handle_tool_call("memory_wiki_code_graph_ingest_inbox", {"limit": 1}))
                assert live["success"] is True and live["processed"] == 0, live
                plan = provider._rebuild_from_journal(apply=False, checkpoint=checkpoint["path"])
                assert plan["incomplete_events"] == 0, plan
                assert plan["events_to_replay"] == 1, plan
                rebuilt = provider._rebuild_from_journal(apply=True, checkpoint=checkpoint["path"])
                assert rebuilt["replayed"] == 1, rebuilt
            finally:
                if provider._conn is not None:
                    provider._conn.close(); provider._conn = None
    finally:
        for key, value in previous.items():
            if value is None: os.environ.pop(key, None)
            else: os.environ[key] = value


def test_unavailable_code_shrinker_inbox_is_not_reported_as_empty() -> None:
    """An unreadable inbox must fail closed without an empty-poll journal pair."""
    keys = ("HERMES_HOME", "HERMES_SECURITY_STRICT", "MEMORY_WIKI_SEMANTIC")
    previous = {key: os.environ.get(key) for key in keys}
    try:
        with tempfile.TemporaryDirectory(prefix="mw-empty-code-inbox-unavailable-") as tmp:
            os.environ.update({"HERMES_HOME": tmp, "HERMES_SECURITY_STRICT": "0", "MEMORY_WIKI_SEMANTIC": "0"})
            module = load_provider("memory_wiki_empty_code_inbox_unavailable_test")
            provider = module.MemoryWikiProvider(); provider.initialize("empty-code-inbox-unavailable", hermes_home=tmp, agent_context="test")
            try:
                blocked_home = Path(tmp) / "not-a-home-directory"
                blocked_home.write_text("not a directory", encoding="utf-8")
                provider.home = blocked_home
                result = json.loads(provider.handle_tool_call("memory_wiki_code_graph_ingest_inbox", {"limit": 1}))
                assert result["success"] is False, result
                assert result["error"] == "code_shrinker_inbox_unavailable", result
                assert not [
                    event for event in provider._iter_journal_events()
                    if event.get("op") == "memory_wiki_code_graph_ingest_inbox"
                ]
            finally:
                if provider._conn is not None:
                    provider._conn.close(); provider._conn = None
    finally:
        for key, value in previous.items():
            if value is None: os.environ.pop(key, None)
            else: os.environ[key] = value


if __name__ == "__main__":
    test_empty_code_graph_inbox_poll_is_replayable_noop()
    print("PASS test_empty_code_graph_inbox_poll_is_replayable_noop")
