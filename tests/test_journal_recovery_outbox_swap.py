#!/usr/bin/env python3
"""Recovery regression: semantic outbox workers never start against the temporary rebuild database."""
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


def test_recovery_wakes_semantic_outbox_only_after_database_swap() -> None:
    keys = ("HERMES_HOME", "HERMES_SECURITY_STRICT", "MEMORY_WIKI_SEMANTIC")
    previous = {key: os.environ.get(key) for key in keys}
    try:
        with tempfile.TemporaryDirectory(prefix="mw-recovery-outbox-") as tmp:
            os.environ.update({"HERMES_HOME": tmp, "HERMES_SECURITY_STRICT": "0", "MEMORY_WIKI_SEMANTIC": "0"})
            module = load_provider("memory_wiki_recovery_outbox_test")
            provider = module.MemoryWikiProvider(); provider.initialize("outbox-recovery", hermes_home=tmp, agent_context="test")
            provider._make_secret_index_from_raw = lambda *_args, **_kwargs: ""
            calls = []
            module.SEMANTIC_ENABLED = True
            module._start_outbox_worker = lambda path: calls.append(("start", path))
            module._wake_outbox_worker = lambda path: calls.append(("wake", path))
            try:
                checkpoint = provider._journal_checkpoint("before-outbox-recovery")
                live = json.loads(provider.handle_tool_call("memory_wiki_code_claim_add", {
                    "claim": "Verified semantic recovery outbox behavior.", "repository_id": "repo-outbox",
                    "file_path": "src/outbox.py", "content_hash": "d" * 64,
                }))
                assert live["success"] is True, live
                calls.clear()
                provider._rebuild_from_journal(apply=True, checkpoint=checkpoint["path"])
                assert [kind for kind, _path in calls] == ["start", "wake"], calls
                assert all("rebuilt" not in path for _kind, path in calls), calls
            finally:
                if provider._conn is not None:
                    provider._conn.close(); provider._conn = None
    finally:
        for key, value in previous.items():
            if value is None: os.environ.pop(key, None)
            else: os.environ[key] = value


if __name__ == "__main__":
    test_recovery_wakes_semantic_outbox_only_after_database_swap()
    print("PASS test_recovery_wakes_semantic_outbox_only_after_database_swap")
