#!/usr/bin/env python3
"""Regression: post-checkpoint code claims are replayed with their metadata."""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path


PLUGIN = Path(__file__).resolve().parents[1] / "__init__.py"


def load_provider(module_name: str):
    spec = importlib.util.spec_from_file_location(
        module_name, PLUGIN, submodule_search_locations=[str(PLUGIN.parent)]
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_rebuild_replays_post_checkpoint_code_claim_metadata() -> None:
    previous = {
        key: os.environ.get(key)
        for key in ("HERMES_HOME", "HERMES_SECURITY_STRICT", "MEMORY_WIKI_SEMANTIC")
    }
    try:
        with tempfile.TemporaryDirectory(prefix="mw-replay-code-claim-") as tmp:
            os.environ["HERMES_HOME"] = tmp
            os.environ["HERMES_SECURITY_STRICT"] = "0"
            os.environ["MEMORY_WIKI_SEMANTIC"] = "0"
            module = load_provider("memory_wiki_replay_code_claim_test")
            provider = module.MemoryWikiProvider()
            provider.initialize("replay-code-claim-test", hermes_home=tmp, agent_context="test")
            try:
                checkpoint = provider._journal_checkpoint("before-code-claim")
                result = json.loads(
                    provider.handle_tool_call(
                        "memory_wiki_code_claim_add",
                        {
                            "claim": "Verified code recovery invariant: the parser preserves a code-linked recovery sentinel after journal replay.",
                            "repository_id": "repo-replay-test",
                            "file_path": "src/parser.py",
                            "symbol_id": "parse",
                            "content_hash": "a" * 64,
                            "source_event_id": "code-replay-regression",
                        },
                    )
                )
                assert result["success"] is True
                assert "id" in result, result
                claim_id = result["id"]

                rebuilt = provider._rebuild_from_journal(apply=True, checkpoint=checkpoint["path"])
                assert rebuilt["replayed"] >= 1
                row = provider._connect().execute(
                    "SELECT repository_id,file_path,symbol_id FROM code_claim_metadata WHERE claim_id=?",
                    (claim_id,),
                ).fetchone()
                assert row is not None
                assert tuple(row) == ("repo-replay-test", "src/parser.py", "parse")
            finally:
                if provider._conn is not None:
                    provider._conn.close()
                    provider._conn = None
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


if __name__ == "__main__":
    test_rebuild_replays_post_checkpoint_code_claim_metadata()
    print("PASS test_rebuild_replays_post_checkpoint_code_claim_metadata")
