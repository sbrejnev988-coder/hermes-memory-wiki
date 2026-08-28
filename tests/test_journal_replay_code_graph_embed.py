#!/usr/bin/env python3
"""Recovery regression: code graph embedding batches are recomputed from durable graph state."""
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


def test_rebuild_recomputes_code_graph_embedding_batch_from_reference() -> None:
    keys = ("HERMES_HOME", "HERMES_SECURITY_STRICT", "MEMORY_WIKI_SEMANTIC")
    previous = {key: os.environ.get(key) for key in keys}
    try:
        with tempfile.TemporaryDirectory(prefix="mw-code-embed-replay-") as tmp:
            os.environ.update({"HERMES_HOME": tmp, "HERMES_SECURITY_STRICT": "0", "MEMORY_WIKI_SEMANTIC": "0"})
            module = load_provider("memory_wiki_code_embed_replay_test")
            provider = module.MemoryWikiProvider()
            provider.initialize("code-embed-replay", hermes_home=tmp, agent_context="test")
            calls = []
            module._embed_pending_chunks = lambda prov, args: calls.append((str(prov.db_path), dict(args))) or {
                "repository_id": args["repository_id"], "pending_before": 1, "pending_after": 0,
            }
            try:
                checkpoint = provider._journal_checkpoint("before-code-embed")
                live = json.loads(provider.handle_tool_call("memory_wiki_code_graph_embed_pending", {
                    "repository_id": "repo-embed-recovery", "limit": 17,
                }))
                assert live["success"] is True, live
                plan = provider._rebuild_from_journal(apply=False, checkpoint=checkpoint["path"])
                assert plan["unrecoverable_events"] == 0, plan
                provider._rebuild_from_journal(apply=True, checkpoint=checkpoint["path"])
                assert len(calls) == 2, calls
                assert calls[1][1] == {"repository_id": "repo-embed-recovery", "limit": 17}
                assert "rebuilt" in calls[1][0]
            finally:
                if provider._conn is not None:
                    provider._conn.close(); provider._conn = None
    finally:
        for key, value in previous.items():
            if value is None: os.environ.pop(key, None)
            else: os.environ[key] = value


if __name__ == "__main__":
    test_rebuild_recomputes_code_graph_embedding_batch_from_reference()
    print("PASS test_rebuild_recomputes_code_graph_embedding_batch_from_reference")
