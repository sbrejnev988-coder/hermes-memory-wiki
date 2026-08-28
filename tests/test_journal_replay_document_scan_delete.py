#!/usr/bin/env python3
"""Recovery integration: scan child refs and a later delete replay in journal order."""
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


def test_rebuild_replays_document_scan_children_then_document_delete() -> None:
    keys = ("HERMES_HOME", "HERMES_SECURITY_STRICT", "MEMORY_WIKI_SEMANTIC", "MEMORY_WIKI_DOCUMENT_ROOTS")
    previous = {key: os.environ.get(key) for key in keys}
    try:
        with tempfile.TemporaryDirectory(prefix="mw-document-scan-replay-") as tmp:
            home = Path(tmp); docs = home / "docs"; docs.mkdir()
            marker_a = "SCAN_RECOVERY_A_231f"; marker_b = "SCAN_RECOVERY_B_892a"
            (docs / "a.md").write_text(f"# A\n{marker_a}\n", encoding="utf-8")
            (docs / "b.md").write_text(f"# B\n{marker_b}\n", encoding="utf-8")
            os.environ.update({
                "HERMES_HOME": str(home), "HERMES_SECURITY_STRICT": "0", "MEMORY_WIKI_SEMANTIC": "0",
                "MEMORY_WIKI_DOCUMENT_ROOTS": str(docs),
            })
            module = load_provider("memory_wiki_document_scan_replay_test")
            provider = module.MemoryWikiProvider()
            provider.initialize("scan-replay", hermes_home=str(home), project_id="repo-scan")
            try:
                checkpoint = provider._journal_checkpoint("before-document-scan")
                scan = json.loads(provider.handle_tool_call("memory_wiki_document_scan", {
                    "root": str(docs), "scope_id": "repo-scan", "repository_id": "repo-scan", "max_files": 10,
                }))
                assert scan["success"] is True and scan["indexed"] == 2, scan
                source_a = next(item["source_id"] for item in scan["results"] if item["path"].endswith("a.md"))
                deleted = json.loads(provider.handle_tool_call("memory_wiki_document_delete", {"source_id": source_a}))
                assert deleted["success"] is True and deleted["status"] == "deleted", deleted
                journal = provider.journal_path.read_text(encoding="utf-8")
                assert marker_a not in journal and marker_b not in journal
                assert str(docs) not in journal
                plan = provider._rebuild_from_journal(apply=False, checkpoint=checkpoint["path"])
                assert plan["unrecoverable_events"] == 0, plan
                rebuilt = provider._rebuild_from_journal(apply=True, checkpoint=checkpoint["path"])
                assert rebuilt["replayed"] >= 2, rebuilt
                rows = provider._connect().execute(
                    "SELECT source_id,active FROM document_sources ORDER BY source_id"
                ).fetchall()
                flags = {str(row["source_id"]): int(row["active"]) for row in rows}
                assert flags[source_a] == 0
                active_text = provider._connect().execute(
                    "SELECT unit_text FROM document_units WHERE active=1"
                ).fetchall()
                assert any(marker_b in str(row[0]) for row in active_text)
            finally:
                if provider._conn is not None:
                    provider._conn.close(); provider._conn = None
    finally:
        for key, value in previous.items():
            if value is None: os.environ.pop(key, None)
            else: os.environ[key] = value


if __name__ == "__main__":
    test_rebuild_replays_document_scan_children_then_document_delete()
    print("PASS test_rebuild_replays_document_scan_children_then_document_delete")
