#!/usr/bin/env python3
"""Recovery regression: Code Shrinker patch events replay from immutable artifacts."""
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


def test_rebuild_replays_code_shrinker_patch_event_from_hashed_artifact() -> None:
    keys = ("HERMES_HOME", "HERMES_SECURITY_STRICT", "MEMORY_WIKI_SEMANTIC")
    previous = {key: os.environ.get(key) for key in keys}
    try:
        with tempfile.TemporaryDirectory(prefix="mw-patch-artifact-") as tmp:
            home = Path(tmp)
            os.environ.update({"HERMES_HOME": tmp, "HERMES_SECURITY_STRICT": "0", "MEMORY_WIKI_SEMANTIC": "0"})
            module = load_provider("memory_wiki_patch_artifact_replay_test")
            provider = module.MemoryWikiProvider()
            provider.initialize("patch-artifact", hermes_home=tmp, agent_context="test")
            provider._make_secret_index_from_raw = lambda *_args, **_kwargs: ""
            try:
                checkpoint = provider._journal_checkpoint("before-patch-inbox")
                inbox = home / "context-coordination" / "inbox" / "code-shrinker"
                inbox.mkdir(parents=True, exist_ok=True)
                rollback_marker = "PATCH_ROLLBACK_SENTINEL_68d1"
                event = {
                    "event_version": 1,
                    "type": "patch_applied",
                    "producer": "code-shrinker",
                    "event_id": "patch-artifact-regression-event",
                    "repository_id": "repo-patch-artifact",
                    "patch_id": "patch-artifact-001",
                    "outcome": "applied",
                    "commit_sha": "a" * 40,
                    "new_content_hash": "b" * 64,
                    "changed_files": ["src/recovery.py"],
                    "changed_symbols": ["restore"],
                    "validation_report": {"status": "passed"},
                    "rollback_steps": rollback_marker,
                }
                (inbox / "patch-event.json").write_text(json.dumps(event), encoding="utf-8")
                live = json.loads(provider.handle_tool_call("memory_wiki_code_graph_ingest_inbox", {"limit": 1}))
                errors = [path.read_text(encoding="utf-8") for path in (home / "context-coordination" / "dead-letter" / "code-shrinker").glob("*.error.json")]
                assert live["success"] is True and live["processed"] == 1, (live, errors)
                journal = provider.journal_path.read_text(encoding="utf-8")
                assert rollback_marker not in journal
                assert "code_graph_inbox_artifact/v1" in journal
                plan = provider._rebuild_from_journal(apply=False, checkpoint=checkpoint["path"])
                assert plan["unrecoverable_events"] == 0, plan
                rebuilt = provider._rebuild_from_journal(apply=True, checkpoint=checkpoint["path"])
                assert rebuilt["replayed"] >= 1, rebuilt
                row = provider._connect().execute(
                    "SELECT outcome,commit_sha,new_content_hash,rollback_steps FROM patch_outcomes WHERE repository_id=? AND patch_id=?",
                    ("repo-patch-artifact", "patch-artifact-001"),
                ).fetchone()
                assert row is not None
                assert tuple(row[:3]) == ("applied", "a" * 40, "b" * 64)
                assert str(row[3]) == rollback_marker
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
    test_rebuild_replays_code_shrinker_patch_event_from_hashed_artifact()
    print("PASS test_rebuild_replays_code_shrinker_patch_event_from_hashed_artifact")
