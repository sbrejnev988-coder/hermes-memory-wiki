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


if __name__ == "__main__":
    test_empty_code_graph_inbox_poll_is_replayable_noop()
    print("PASS test_empty_code_graph_inbox_poll_is_replayable_noop")
