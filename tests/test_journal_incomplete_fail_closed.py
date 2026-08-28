#!/usr/bin/env python3
"""Regression: recovery refuses a journal with an unmatched durable before-event."""
from __future__ import annotations

import importlib.util
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


def test_incomplete_before_event_keeps_live_database_unchanged() -> None:
    previous = {key: os.environ.get(key) for key in ("HERMES_HOME", "HERMES_SECURITY_STRICT", "MEMORY_WIKI_SEMANTIC")}
    try:
        with tempfile.TemporaryDirectory(prefix="mw-incomplete-journal-") as tmp:
            os.environ["HERMES_HOME"] = tmp
            os.environ["HERMES_SECURITY_STRICT"] = "0"
            os.environ["MEMORY_WIKI_SEMANTIC"] = "0"
            module = load_provider("memory_wiki_incomplete_journal_test")
            provider = module.MemoryWikiProvider()
            provider.initialize("incomplete-journal-test", hermes_home=tmp, agent_context="test")
            try:
                sentinel = "c_incomplete_journal_sentinel"
                with provider._connect() as conn:
                    conn.execute(
                        """INSERT INTO claims(
                            id,claim,topic,status,confidence,salience,source,evidence,
                            created_at,updated_at,freshness_at,access_count,last_accessed,hash
                        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (sentinel, "Live database survives incomplete journal event.", "tests", "active",
                         0.9, 0.9, "test", "", 1, 1, 1, 0, 0, "incomplete-journal-sentinel"),
                    )
                checkpoint = provider._journal_checkpoint("before-interrupted-document")
                provider._append_journal_event(
                    "memory_wiki_document_ingest", {"path": "interrupted.txt"}, phase="before"
                )
                plan = provider._rebuild_from_journal(apply=False, checkpoint=checkpoint["path"])
                assert plan["incomplete_events"] == 1
                assert plan["incomplete_ops"] == {"memory_wiki_document_ingest": 1}
                try:
                    provider._rebuild_from_journal(apply=True, checkpoint=checkpoint["path"])
                except RuntimeError as exc:
                    assert "incomplete" in str(exc)
                else:
                    raise AssertionError("incomplete mutation did not block recovery")
                assert provider._connect().execute("SELECT 1 FROM claims WHERE id=?", (sentinel,)).fetchone()
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
    test_incomplete_before_event_keeps_live_database_unchanged()
    print("PASS test_incomplete_before_event_keeps_live_database_unchanged")
