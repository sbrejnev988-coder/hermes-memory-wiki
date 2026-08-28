#!/usr/bin/env python3
"""Recovery regression: changed source files block document replay and preserve the live DB."""
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


def test_changed_document_source_blocks_rebuild_without_swapping_live_database() -> None:
    keys = ("HERMES_HOME", "HERMES_SECURITY_STRICT", "MEMORY_WIKI_SEMANTIC", "MEMORY_WIKI_DOCUMENT_ROOTS")
    previous = {key: os.environ.get(key) for key in keys}
    try:
        with tempfile.TemporaryDirectory(prefix="mw-document-changed-recovery-") as tmp:
            home = Path(tmp); docs = home / "docs"; docs.mkdir(); source = docs / "source.md"
            source.write_text("# Initial\nORIGINAL_DOCUMENT_RECOVERY_3e2a\n", encoding="utf-8")
            os.environ.update({
                "HERMES_HOME": str(home), "HERMES_SECURITY_STRICT": "0", "MEMORY_WIKI_SEMANTIC": "0",
                "MEMORY_WIKI_DOCUMENT_ROOTS": str(docs),
            })
            module = load_provider("memory_wiki_document_changed_recovery_test")
            provider = module.MemoryWikiProvider()
            provider.initialize("changed-source-recovery", hermes_home=str(home), project_id="repo-changed")
            try:
                checkpoint = provider._journal_checkpoint("before-changed-source")
                live = json.loads(provider.handle_tool_call("memory_wiki_document_ingest", {
                    "path": str(source), "scope_id": "repo-changed", "repository_id": "repo-changed",
                }))
                assert live["success"] is True, live
                source_id = live["source_id"]; original_hash = live["file_hash"]
                source.write_text("# Changed\nDIFFERENT_DOCUMENT_RECOVERY_12ac\n", encoding="utf-8")
                try:
                    provider._rebuild_from_journal(apply=True, checkpoint=checkpoint["path"])
                except RuntimeError as exc:
                    assert "journal replay failed" in str(exc)
                else:
                    raise AssertionError("changed document source was accepted during recovery")
                row = provider._connect().execute(
                    "SELECT file_hash,active FROM document_sources WHERE source_id=?", (source_id,)
                ).fetchone()
                assert row is not None and str(row["file_hash"]) == original_hash and int(row["active"]) == 1
            finally:
                if provider._conn is not None:
                    provider._conn.close(); provider._conn = None
    finally:
        for key, value in previous.items():
            if value is None: os.environ.pop(key, None)
            else: os.environ[key] = value


if __name__ == "__main__":
    test_changed_document_source_blocks_rebuild_without_swapping_live_database()
    print("PASS test_changed_document_source_blocks_rebuild_without_swapping_live_database")
