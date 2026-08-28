#!/usr/bin/env python3
"""Recovery regression: Code Shrinker snapshots replay from verified immutable artifacts."""
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


def test_rebuild_replays_code_graph_inbox_snapshot_from_hashed_artifact() -> None:
    keys = ("HERMES_HOME", "HERMES_SECURITY_STRICT", "MEMORY_WIKI_SEMANTIC")
    previous = {key: os.environ.get(key) for key in keys}
    try:
        with tempfile.TemporaryDirectory(prefix="mw-code-graph-artifact-") as tmp:
            home = Path(tmp)
            os.environ.update({"HERMES_HOME": tmp, "HERMES_SECURITY_STRICT": "0", "MEMORY_WIKI_SEMANTIC": "0"})
            module = load_provider("memory_wiki_code_graph_artifact_replay_test")
            provider = module.MemoryWikiProvider()
            provider.initialize("code-graph-artifact", hermes_home=tmp, agent_context="test")
            try:
                checkpoint = provider._journal_checkpoint("before-code-graph-inbox")
                inbox = home / "context-coordination" / "inbox" / "code-shrinker"
                inbox.mkdir(parents=True, exist_ok=True)
                marker = "CODE_GRAPH_SOURCE_SENTINEL_7ad2"
                event = {
                    "event_version": 2,
                    "type": "code_graph_snapshot",
                    "graph_schema_version": 1,
                    "producer": "code-shrinker",
                    "repository_id": "repo-graph-artifact",
                    "event_id": "graph-artifact-regression-event",
                    "snapshot_mode": "full",
                    "snapshot_hash": "graph-artifact-snapshot-hash",
                    "lines": [{
                        "file_path": "src/recovery.py",
                        "line_no": 1,
                        "line_id": "line:repo-graph-artifact:src/recovery.py:1",
                        "line_text": f"def restore(): return '{marker}'",
                    }],
                }
                (inbox / "graph-event.json").write_text(json.dumps(event), encoding="utf-8")
                live = json.loads(provider.handle_tool_call("memory_wiki_code_graph_ingest_inbox", {"limit": 1}))
                assert live["success"] is True and live["processed"] == 1, live

                journal = provider.journal_path.read_text(encoding="utf-8")
                assert marker not in journal
                assert "code_graph_inbox_artifact/v1" in journal
                plan = provider._rebuild_from_journal(apply=False, checkpoint=checkpoint["path"])
                assert plan["unrecoverable_events"] == 0, plan
                rebuilt = provider._rebuild_from_journal(apply=True, checkpoint=checkpoint["path"])
                assert rebuilt["replayed"] >= 1, rebuilt
                line = provider._connect().execute(
                    "SELECT line_text FROM code_graph_lines WHERE repository_id=? AND file_path=? AND line_no=1",
                    ("repo-graph-artifact", "src/recovery.py"),
                ).fetchone()
                assert line is not None and marker in str(line[0])
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
    test_rebuild_replays_code_graph_inbox_snapshot_from_hashed_artifact()
    print("PASS test_rebuild_replays_code_graph_inbox_snapshot_from_hashed_artifact")
