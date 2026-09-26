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


def test_legacy_identity_invalidation_registers_replayable_aliases() -> None:
    """A legacy alias must not archive a claim and then fail journaling."""
    keys = ("HERMES_HOME", "HERMES_SECURITY_STRICT", "MEMORY_WIKI_SEMANTIC")
    previous = {key: os.environ.get(key) for key in keys}
    try:
        with tempfile.TemporaryDirectory(prefix="mw-legacy-invalidation-recovery-") as tmp:
            os.environ.update({"HERMES_HOME": tmp, "HERMES_SECURITY_STRICT": "0", "MEMORY_WIKI_SEMANTIC": "0"})
            module = load_provider("memory_wiki_legacy_invalidation_recovery_test")
            provider = module.MemoryWikiProvider()
            provider.initialize("legacy-invalidation-recovery", hermes_home=tmp, agent_context="test")
            provider._make_secret_index_from_raw = lambda *_args, **_kwargs: ""
            try:
                token = "ghp_" + "a" * 36
                raw_repository_id = f"repo-{token}"
                raw_file_path = f"src/{token}.py"
                old_hash = hashlib.sha256(b"legacy old").hexdigest()
                new_hash = hashlib.sha256(b"legacy new").hexdigest()
                claim_id = provider._code_claim_add({
                    "claim": "Verified legacy invalidation recovery behavior for a code revision.",
                    "topic": "code-shrinker",
                    "repository_id": raw_repository_id,
                    "file_path": raw_file_path,
                    "symbol_id": "legacy_symbol",
                    "content_hash": old_hash,
                    "evidence": "verified source and revision metadata",
                    "confidence": 0.95,
                    "salience": 0.9,
                })["id"]

                # Model a legacy v1 alias in an owned private claim. A project
                # claim can be read but is not mutable through model-facing tools.
                with provider._connect() as conn:
                    conn.execute("DELETE FROM code_graph_identity_provenance")
                    conn.execute(
                        "UPDATE claims SET visibility_scope='private',origin_bot_id=?,"
                        "origin_session_id=? WHERE id=?",
                        (provider.bot_id, provider.session_id, claim_id),
                    )

                assert provider._require_model_mutable_claim(claim_id)
                result = json.loads(provider.handle_tool_call("memory_wiki_invalidate_revision", {
                    "repository_id": raw_repository_id,
                    "file_path": raw_file_path,
                    "new_content_hash": new_hash,
                }))
                assert result["success"] is True, result
                assert provider._connect().execute(
                    "SELECT status FROM claims WHERE id=?", (claim_id,)
                ).fetchone()[0] == "archived"

                aliases = {
                    provider._code_graph_identity(raw_repository_id),
                    provider._code_graph_identity(raw_file_path),
                }
                assert provider._connect().execute(
                    "SELECT COUNT(*) FROM code_graph_identity_provenance "
                    "WHERE opaque_id IN (?,?)",
                    tuple(aliases),
                ).fetchone()[0] == len(aliases)
                after = [
                    event for event in provider._iter_journal_events()
                    if event.get("op") == "memory_wiki_invalidate_revision" and event.get("phase") == "after"
                ]
                assert after
                recovery = after[-1]["result"]["recovery"]
                assert recovery["kind"] == "revision_invalidation"
                assert provider._replay_code_recovery_reference(recovery)["invalidated"] == 0
                assert token not in provider.journal_path.read_text(encoding="utf-8")
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
