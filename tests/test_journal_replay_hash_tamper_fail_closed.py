#!/usr/bin/env python3
"""Recovery regression: tampered journal hash chains fail closed before any database swap."""
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


def test_tampered_journal_hash_chain_blocks_rebuild_without_swapping_live_database() -> None:
    keys = ("HERMES_HOME", "HERMES_SECURITY_STRICT", "MEMORY_WIKI_SEMANTIC")
    previous = {key: os.environ.get(key) for key in keys}
    try:
        with tempfile.TemporaryDirectory(prefix="mw-journal-hash-tamper-") as tmp:
            os.environ.update({"HERMES_HOME": tmp, "HERMES_SECURITY_STRICT": "0", "MEMORY_WIKI_SEMANTIC": "0"})
            module = load_provider("memory_wiki_journal_hash_tamper_test")
            provider = module.MemoryWikiProvider(); provider.initialize("journal-hash-tamper", hermes_home=tmp, agent_context="test")
            try:
                sentinel = "c_journal_hash_tamper_sentinel"
                with provider._connect() as conn:
                    conn.execute(
                        """INSERT INTO claims(
                            id,claim,topic,status,confidence,salience,source,evidence,
                            created_at,updated_at,freshness_at,access_count,last_accessed,hash
                        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (sentinel, "Checkpoint sentinel must survive hash-tamper recovery refusal.", "tests", "active",
                         0.9, 0.9, "test", "", 1, 1, 1, 0, 0, "journal-hash-tamper-sentinel"),
                    )
                checkpoint = provider._journal_checkpoint("before-hash-tamper")
                live = json.loads(provider.handle_tool_call("memory_wiki_add_claim", {
                    "claim": "Post-checkpoint claim that should not be replayed from a tampered event.", "topic": "tests",
                }))
                assert live["success"] is True, live
                lines = provider.journal_path.read_text(encoding="utf-8").splitlines()
                last = json.loads(lines[-1]); last["hash"] = "0" * 64
                lines[-1] = json.dumps(last, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                provider.journal_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
                try:
                    provider._rebuild_from_journal(apply=True, checkpoint=checkpoint["path"])
                except RuntimeError as exc:
                    assert "integrity" in str(exc).lower() or "cannot replay" in str(exc).lower()
                else:
                    raise AssertionError("tampered journal hash chain was accepted")
                assert provider._connect().execute("SELECT 1 FROM claims WHERE id=?", (sentinel,)).fetchone()
            finally:
                if provider._conn is not None:
                    provider._conn.close(); provider._conn = None
    finally:
        for key, value in previous.items():
            if value is None: os.environ.pop(key, None)
            else: os.environ[key] = value


if __name__ == "__main__":
    test_tampered_journal_hash_chain_blocks_rebuild_without_swapping_live_database()
    print("PASS test_tampered_journal_hash_chain_blocks_rebuild_without_swapping_live_database")
