#!/usr/bin/env python3
"""Regression: a failed journal replay must never replace the live database."""
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


def test_failed_journal_replay_keeps_original_database() -> None:
    previous = {
        key: os.environ.get(key)
        for key in ("HERMES_HOME", "HERMES_SECURITY_STRICT", "MEMORY_WIKI_SEMANTIC")
    }
    try:
        with tempfile.TemporaryDirectory(prefix="mw-journal-replay-") as tmp:
            os.environ["HERMES_HOME"] = tmp
            os.environ["HERMES_SECURITY_STRICT"] = "0"
            os.environ["MEMORY_WIKI_SEMANTIC"] = "0"
            module = load_provider("memory_wiki_failed_replay_test")
            provider = module.MemoryWikiProvider()
            try:
                provider.initialize("journal-replay-test", hermes_home=tmp, agent_context="test")
                original_id = "c_journal_sentinel"
                with provider._connect() as conn:
                    conn.execute(
                        """INSERT INTO claims(
                            id,claim,topic,status,confidence,salience,source,evidence,
                            created_at,updated_at,freshness_at,access_count,last_accessed,hash
                        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (
                            original_id, "Original database sentinel survives a failed replay.",
                            "tests", "active", 0.9, 0.9, "test", "", 1, 1, 1, 0, 0,
                            "journal-replay-sentinel-hash",
                        ),
                    )
                original_db = provider.db_path

                provider._backup = lambda *_a, **_k: {}
                provider._preserve_db_files = lambda *_a, **_k: []
                provider._rebuild_fts = lambda: None
                provider._render_all = lambda: None
                provider._render_active_dashboard = lambda: None
                provider._audit = lambda *_a, **_k: None
                provider._iter_journal_events = lambda: iter([
                    {"phase": "before", "seq": 1, "op": "memory_wiki_add_claim", "payload": {}},
                    {"phase": "after", "seq": 2, "op": "memory_wiki_add_claim", "payload": {}},
                ])
                provider._journal_status = lambda **_kwargs: {"events_invalid": 0, "hash_errors": 0, "sequence_errors": 0}
                provider._replayable_journal_ops = lambda: {"memory_wiki_add_claim"}
                provider.handle_tool_call = lambda *_a, **_k: json.dumps({"success": False, "error": "synthetic replay failure"})

                try:
                    provider._rebuild_from_journal(apply=True)
                except RuntimeError as exc:
                    assert "journal replay failed" in str(exc)
                else:
                    raise AssertionError("rebuild accepted a failed replay and may have swapped the live DB")

                assert provider.db_path == original_db
                assert provider._connect().execute("SELECT 1 FROM claims WHERE id=?", (original_id,)).fetchone()
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
    test_failed_journal_replay_keeps_original_database()
    print("PASS test_failed_journal_replay_keeps_original_database")
