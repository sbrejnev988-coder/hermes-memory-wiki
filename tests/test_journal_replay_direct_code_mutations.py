#!/usr/bin/env python3
"""Recovery regression: direct patch outcomes and revision invalidations have safe replay refs."""
from __future__ import annotations

import hashlib
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


def test_rebuild_replays_direct_patch_outcome_and_revision_invalidation_without_journaling_rollback_text() -> None:
    keys = ("HERMES_HOME", "HERMES_SECURITY_STRICT", "MEMORY_WIKI_SEMANTIC")
    previous = {key: os.environ.get(key) for key in keys}
    try:
        with tempfile.TemporaryDirectory(prefix="mw-direct-code-recovery-") as tmp:
            os.environ.update({"HERMES_HOME": tmp, "HERMES_SECURITY_STRICT": "0", "MEMORY_WIKI_SEMANTIC": "0"})
            module = load_provider("memory_wiki_direct_code_recovery_test")
            provider = module.MemoryWikiProvider()
            provider.initialize("direct-code-recovery", hermes_home=tmp, agent_context="test")
            provider._make_secret_index_from_raw = lambda *_args, **_kwargs: ""
            try:
                old_hash = hashlib.sha256(b"old").hexdigest()
                new_hash = hashlib.sha256(b"new").hexdigest()
                old_claim = provider._code_claim_add({
                    "claim": "Verified prior revision for direct recovery test.",
                    "repository_id": "repo-direct-recovery",
                    "file_path": "src/recovery.py",
                    "symbol_id": "restore",
                    "content_hash": old_hash,
                })["id"]
                checkpoint = provider._journal_checkpoint("before-direct-code-mutations")
                rollback_marker = "DIRECT_PATCH_ROLLBACK_SENTINEL_11aa"
                patch = json.loads(provider.handle_tool_call("memory_wiki_patch_outcome_add", {
                    "patch_id": "direct-patch-1", "outcome": "applied", "repository_id": "repo-direct-recovery",
                    "commit_sha": "c" * 40, "old_content_hash": old_hash, "new_content_hash": new_hash,
                    "changed_files": ["src/recovery.py"], "changed_symbols": ["restore"],
                    "validation_report": {"status": "passed"}, "rollback_steps": rollback_marker,
                    "source_event_id": "direct-patch-recovery-event",
                }))
                invalidated = json.loads(provider.handle_tool_call("memory_wiki_invalidate_revision", {
                    "repository_id": "repo-direct-recovery", "file_path": "src/recovery.py",
                    "new_commit_sha": "c" * 40, "new_content_hash": new_hash,
                }))
                assert patch["success"] is True and invalidated["success"] is True
                journal = provider.journal_path.read_text(encoding="utf-8")
                assert rollback_marker not in journal
                plan = provider._rebuild_from_journal(apply=False, checkpoint=checkpoint["path"])
                assert plan["unrecoverable_events"] == 0, plan
                rebuilt = provider._rebuild_from_journal(apply=True, checkpoint=checkpoint["path"])
                assert rebuilt["replayed"] >= 2, rebuilt
                row = provider._connect().execute(
                    "SELECT rollback_steps FROM patch_outcomes WHERE repository_id=? AND patch_id=?",
                    ("repo-direct-recovery", "direct-patch-1"),
                ).fetchone()
                assert row is not None and str(row[0]) == rollback_marker
                status = provider._connect().execute("SELECT status FROM claims WHERE id=?", (old_claim,)).fetchone()
                assert status is not None and str(status[0]) == "archived"
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
    test_rebuild_replays_direct_patch_outcome_and_revision_invalidation_without_journaling_rollback_text()
    print("PASS test_rebuild_replays_direct_patch_outcome_and_revision_invalidation_without_journaling_rollback_text")
