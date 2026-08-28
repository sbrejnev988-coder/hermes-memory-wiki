#!/usr/bin/env python3
"""Recovery regression: semantic reindex intent is rerun only after a successful DB swap."""
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


def test_rebuild_defers_semantic_reindex_until_after_database_swap() -> None:
    keys = ("HERMES_HOME", "HERMES_SECURITY_STRICT", "MEMORY_WIKI_SEMANTIC")
    previous = {key: os.environ.get(key) for key in keys}
    try:
        with tempfile.TemporaryDirectory(prefix="mw-reindex-recovery-") as tmp:
            os.environ.update({"HERMES_HOME": tmp, "HERMES_SECURITY_STRICT": "0", "MEMORY_WIKI_SEMANTIC": "0"})
            module = load_provider("memory_wiki_reindex_recovery_test")
            provider = module.MemoryWikiProvider()
            provider.initialize("reindex-recovery", hermes_home=tmp, agent_context="test")
            calls = []
            provider._reindex = lambda limit=0, force=False: calls.append((str(provider.db_path), limit, force)) or {
                "ok": True, "status": "completed", "limit": limit, "force": force,
            }
            try:
                checkpoint = provider._journal_checkpoint("before-reindex")
                live = json.loads(provider.handle_tool_call("memory_wiki_reindex", {"limit": 13, "force": True}))
                assert live["success"] is True, live
                plan = provider._rebuild_from_journal(apply=False, checkpoint=checkpoint["path"])
                assert plan["unrecoverable_events"] == 0, plan
                rebuilt = provider._rebuild_from_journal(apply=True, checkpoint=checkpoint["path"])
                assert rebuilt["replayed"] >= 1, rebuilt
                assert len(calls) == 2, calls
                assert calls[1][1:] == (13, True)
                assert "rebuilt" not in calls[1][0]
                assert rebuilt["derived_reindex"][0]["ok"] is True
            finally:
                if provider._conn is not None:
                    provider._conn.close(); provider._conn = None
    finally:
        for key, value in previous.items():
            if value is None: os.environ.pop(key, None)
            else: os.environ[key] = value


if __name__ == "__main__":
    test_rebuild_defers_semantic_reindex_until_after_database_swap()
    print("PASS test_rebuild_defers_semantic_reindex_until_after_database_swap")
