#!/usr/bin/env python3
"""Regression: recovery refuses completed mutations it cannot replay safely."""
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


def test_recovery_fails_closed_for_unreplayable_post_checkpoint_document_mutation() -> None:
    previous = {
        key: os.environ.get(key)
        for key in ("HERMES_HOME", "HERMES_SECURITY_STRICT", "MEMORY_WIKI_SEMANTIC")
    }
    try:
        with tempfile.TemporaryDirectory(prefix="mw-recovery-unreplayable-") as tmp:
            os.environ["HERMES_HOME"] = tmp
            os.environ["HERMES_SECURITY_STRICT"] = "0"
            os.environ["MEMORY_WIKI_SEMANTIC"] = "0"
            module = load_provider("memory_wiki_recovery_unreplayable_test")
            provider = module.MemoryWikiProvider()
            provider.initialize("recovery-unreplayable-test", hermes_home=tmp, agent_context="test")
            try:
                sentinel = "c_unreplayable_recovery_sentinel"
                with provider._connect() as conn:
                    conn.execute(
                        """INSERT INTO claims(
                            id,claim,topic,status,confidence,salience,source,evidence,
                            created_at,updated_at,freshness_at,access_count,last_accessed,hash
                        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (sentinel, "Checkpoint sentinel survives a refused recovery.", "tests", "active",
                         0.9, 0.9, "test", "", 1, 1, 1, 0, 0, "unreplayable-recovery-sentinel"),
                    )
                checkpoint = provider._journal_checkpoint("before-document-ingest")
                assert not provider._should_journal_tool("memory_wiki_semantic_status", {})
                provider._append_journal_event(
                    "memory_wiki_semantic_status",
                    {},
                    phase="after",
                    result={"success": True},
                )
                provider._append_journal_event(
                    "memory_wiki_document_ingest",
                    {"path": str(Path(tmp) / "document.txt")},
                    phase="after",
                    result={"success": True},
                )

                plan = provider._rebuild_from_journal(apply=False, checkpoint=checkpoint["path"])
                assert plan["unrecoverable_events"] == 1
                assert plan["unrecoverable_ops"] == {"memory_wiki_document_ingest": 1}
                assert plan["ignored_events"] == 1
                try:
                    provider._rebuild_from_journal(apply=True, checkpoint=checkpoint["path"])
                except RuntimeError as exc:
                    assert "cannot replay" in str(exc)
                else:
                    raise AssertionError("recovery silently accepted an unreplayable document mutation")
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
    test_recovery_fails_closed_for_unreplayable_post_checkpoint_document_mutation()
    print("PASS test_recovery_fails_closed_for_unreplayable_post_checkpoint_document_mutation")
