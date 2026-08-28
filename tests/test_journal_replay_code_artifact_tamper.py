#!/usr/bin/env python3
"""Recovery regression: tampered immutable Code Shrinker artifacts block DB replacement."""
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


def test_tampered_code_graph_recovery_artifact_blocks_rebuild_without_swapping_live_db() -> None:
    keys = ("HERMES_HOME", "HERMES_SECURITY_STRICT", "MEMORY_WIKI_SEMANTIC")
    previous = {key: os.environ.get(key) for key in keys}
    try:
        with tempfile.TemporaryDirectory(prefix="mw-code-artifact-tamper-") as tmp:
            home = Path(tmp)
            os.environ.update({"HERMES_HOME": tmp, "HERMES_SECURITY_STRICT": "0", "MEMORY_WIKI_SEMANTIC": "0"})
            module = load_provider("memory_wiki_code_artifact_tamper_test")
            provider = module.MemoryWikiProvider()
            provider.initialize("code-artifact-tamper", hermes_home=tmp, agent_context="test")
            try:
                checkpoint = provider._journal_checkpoint("before-code-artifact")
                inbox = home / "context-coordination" / "inbox" / "code-shrinker"; inbox.mkdir(parents=True, exist_ok=True)
                event = {
                    "event_version": 2, "type": "code_graph_snapshot", "graph_schema_version": 1,
                    "producer": "code-shrinker", "repository_id": "repo-tamper", "event_id": "tamper-event",
                    "snapshot_mode": "full", "snapshot_hash": "tamper-snapshot",
                    "lines": [{"file_path": "src/a.py", "line_no": 1, "line_id": "line:repo-tamper:src/a.py:1", "line_text": "def alive(): return 1"}],
                }
                (inbox / "event.json").write_text(json.dumps(event), encoding="utf-8")
                live = json.loads(provider.handle_tool_call("memory_wiki_code_graph_ingest_inbox", {"limit": 1}))
                assert live["success"] is True and live["processed"] == 1, live
                artifact = next((home / "memory-wiki" / "recovery-artifacts" / "code-graph-inbox").glob("*.json"))
                artifact.write_bytes(b"{}")
                try:
                    provider._rebuild_from_journal(apply=True, checkpoint=checkpoint["path"])
                except RuntimeError as exc:
                    assert "journal replay failed" in str(exc)
                else:
                    raise AssertionError("tampered Code Shrinker artifact was accepted")
                row = provider._connect().execute(
                    "SELECT line_text FROM code_graph_lines WHERE repository_id=?", ("repo-tamper",)
                ).fetchone()
                assert row is not None and "alive" in str(row[0])
            finally:
                if provider._conn is not None:
                    provider._conn.close(); provider._conn = None
    finally:
        for key, value in previous.items():
            if value is None: os.environ.pop(key, None)
            else: os.environ[key] = value


if __name__ == "__main__":
    test_tampered_code_graph_recovery_artifact_blocks_rebuild_without_swapping_live_db()
    print("PASS test_tampered_code_graph_recovery_artifact_blocks_rebuild_without_swapping_live_db")
