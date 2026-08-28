#!/usr/bin/env python3
"""Journal replay must fail closed when a completed mutation loses its before record."""
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


def test_orphan_after_and_truncated_journal_prefix_block_recovery() -> None:
    keys = ("HERMES_HOME", "HERMES_SECURITY_STRICT", "MEMORY_WIKI_SEMANTIC")
    previous = {key: os.environ.get(key) for key in keys}
    try:
        with tempfile.TemporaryDirectory(prefix="mw-journal-prefix-") as tmp:
            os.environ.update({"HERMES_HOME": tmp, "HERMES_SECURITY_STRICT": "0", "MEMORY_WIKI_SEMANTIC": "0"})
            module = load_provider("memory_wiki_orphan_after_test")
            provider = module.MemoryWikiProvider(); provider.initialize("orphan-after", hermes_home=tmp, agent_context="test")
            try:
                checkpoint = provider._journal_checkpoint("before-orphan-after")
                result = json.loads(provider.handle_tool_call("memory_wiki_add_claim", {
                    "claim": "A durable claim written after the checkpoint.", "topic": "tests",
                }))
                assert result["success"] is True, result
                events = [json.loads(line) for line in provider.journal_path.read_text(encoding="utf-8").splitlines() if line.strip()]
                assert [event["phase"] for event in events] == ["before", "after"], events
                provider.journal_path.write_text(json.dumps(events[1], ensure_ascii=False) + "\n", encoding="utf-8")
                status = provider._journal_status(verify=True)
                assert int(status["hash_errors"]) > 0 or int(status.get("sequence_errors") or 0) > 0, status
                plan = provider._rebuild_from_journal(apply=False, checkpoint=checkpoint["path"])
                assert plan["incomplete_events"] >= 1, plan
                try:
                    provider._rebuild_from_journal(apply=True, checkpoint=checkpoint["path"])
                except RuntimeError:
                    pass
                else:
                    raise AssertionError("orphan after event was accepted for live database replacement")
            finally:
                if provider._conn is not None:
                    provider._conn.close(); provider._conn = None
    finally:
        for key, value in previous.items():
            if value is None: os.environ.pop(key, None)
            else: os.environ[key] = value


if __name__ == "__main__":
    test_orphan_after_and_truncated_journal_prefix_block_recovery()
    print("PASS test_orphan_after_and_truncated_journal_prefix_block_recovery")
