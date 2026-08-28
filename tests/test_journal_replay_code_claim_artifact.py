#!/usr/bin/env python3
"""Recovery regression: code claims journal immutable artifact references, never claim text."""
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


def test_rebuild_replays_code_claim_from_hashed_artifact_without_journaling_claim_text() -> None:
    keys = ("HERMES_HOME", "HERMES_SECURITY_STRICT", "MEMORY_WIKI_SEMANTIC")
    previous = {key: os.environ.get(key) for key in keys}
    try:
        with tempfile.TemporaryDirectory(prefix="mw-code-claim-artifact-") as tmp:
            os.environ.update({"HERMES_HOME": tmp, "HERMES_SECURITY_STRICT": "0", "MEMORY_WIKI_SEMANTIC": "0"})
            module = load_provider("memory_wiki_code_claim_artifact_replay_test")
            provider = module.MemoryWikiProvider()
            provider.initialize("code-claim-artifact", hermes_home=tmp, agent_context="test")
            try:
                checkpoint = provider._journal_checkpoint("before-code-claim-artifact")
                marker = "CODE_CLAIM_ARTIFACT_SENTINEL_59ac"
                live = json.loads(provider.handle_tool_call(
                    "memory_wiki_code_claim_add",
                    {
                        "claim": f"Verified recovery claim: {marker}",
                        "repository_id": "repo-code-artifact",
                        "file_path": "src/recovery.py",
                        "symbol_id": "restore",
                        "content_hash": "b" * 64,
                        "source_event_id": "code-claim-artifact-regression",
                    },
                ))
                assert live["success"] is True and live["status"] == "committed", live
                claim_id = live["id"]

                journal = provider.journal_path.read_text(encoding="utf-8")
                assert marker not in journal
                assert "code_recovery_artifact/v1" in journal
                plan = provider._rebuild_from_journal(apply=False, checkpoint=checkpoint["path"])
                assert plan["unrecoverable_events"] == 0, plan
                rebuilt = provider._rebuild_from_journal(apply=True, checkpoint=checkpoint["path"])
                assert rebuilt["replayed"] >= 1, rebuilt
                row = provider._connect().execute(
                    """SELECT c.claim,m.repository_id,m.file_path,m.symbol_id
                       FROM claims c JOIN code_claim_metadata m ON m.claim_id=c.id WHERE c.id=?""",
                    (claim_id,),
                ).fetchone()
                assert row is not None
                assert marker in str(row["claim"])
                assert tuple(row[1:]) == ("repo-code-artifact", "src/recovery.py", "restore")
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
    test_rebuild_replays_code_claim_from_hashed_artifact_without_journaling_claim_text()
    print("PASS test_rebuild_replays_code_claim_from_hashed_artifact_without_journaling_claim_text")
