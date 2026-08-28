#!/usr/bin/env python3
"""Regression: prune_missing deletion mutations must be included in document scan replay."""
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


def test_document_scan_replay_includes_prune_missing_deletions() -> None:
    keys = ("HERMES_HOME", "HERMES_SECURITY_STRICT", "MEMORY_WIKI_SEMANTIC", "MEMORY_WIKI_DOCUMENT_ROOTS")
    previous = {key: os.environ.get(key) for key in keys}
    try:
        with tempfile.TemporaryDirectory(prefix="mw-scan-prune-recovery-") as tmp:
            home = Path(tmp); docs = home / "docs"; docs.mkdir(); source = docs / "removed.md"
            source.write_text("# Removed\nthis source will be pruned\n", encoding="utf-8")
            os.environ.update({
                "HERMES_HOME": str(home), "HERMES_SECURITY_STRICT": "0", "MEMORY_WIKI_SEMANTIC": "0",
                "MEMORY_WIKI_DOCUMENT_ROOTS": str(docs),
            })
            module = load_provider("memory_wiki_scan_prune_recovery_test")
            provider = module.MemoryWikiProvider(); provider.initialize("scan-prune", hermes_home=str(home), project_id="repo-scan-prune")
            try:
                initial = json.loads(provider.handle_tool_call("memory_wiki_document_ingest", {
                    "path": str(source), "scope_id": "repo-scan-prune", "repository_id": "repo-scan-prune",
                }))
                assert initial["success"] is True, initial
                source_id = initial["source_id"]
                checkpoint = provider._journal_checkpoint("before-prune-scan")
                source.unlink()
                live = json.loads(provider.handle_tool_call("memory_wiki_document_scan", {
                    "root": str(docs), "scope_id": "repo-scan-prune", "repository_id": "repo-scan-prune",
                    "prune_missing": True,
                }))
                assert live["success"] is True and live["pruned"] == 1, live
                assert int(provider._connect().execute("SELECT active FROM document_sources WHERE source_id=?", (source_id,)).fetchone()[0]) == 0
                plan = provider._rebuild_from_journal(apply=False, checkpoint=checkpoint["path"])
                assert plan["unrecoverable_events"] == 0 and plan["incomplete_events"] == 0, plan
                provider._rebuild_from_journal(apply=True, checkpoint=checkpoint["path"])
                restored = provider._connect().execute("SELECT active FROM document_sources WHERE source_id=?", (source_id,)).fetchone()
                assert restored is not None and int(restored[0]) == 0
            finally:
                if provider._conn is not None:
                    provider._conn.close(); provider._conn = None
    finally:
        for key, value in previous.items():
            if value is None: os.environ.pop(key, None)
            else: os.environ[key] = value


if __name__ == "__main__":
    test_document_scan_replay_includes_prune_missing_deletions()
    print("PASS test_document_scan_replay_includes_prune_missing_deletions")
